"""
챗봇 스트리밍 엔드포인트.

GlobalAgentState 기반으로 재작성.
- 상태 초기화: per-turn 필드 매 요청마다 리셋, 이전 턴 오염 방지.
- 토큰 스트리밍: planner 노드(structured JSON) 제외, 나머지 LLM 토큰 전달.
- UI 액션: on_tool_end 이벤트에서 즉시 전달.
- 메타데이터: completed_tasks, ui_action_required + 다음 턴용 persistent state.
"""

import os
import traceback
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    messages_from_dict,
    messages_to_dict,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tracers import LangChainTracer
from langgraph.types import Command
import orjson

from chatbot.src.graph.workflow import graph_app
from chatbot.src.infrastructure.conversation_logger import SessionConversationLogger
from chatbot.src.schemas.chat import ChatRequest, FeedbackRequest, ReviewDraftRequest
from chatbot.src.tools.service_tools import generate_review_draft
from ecommerce.backend.app.core.auth import get_current_user
from ecommerce.backend.app.router.users.models import User
from ecommerce.backend.app.uploads import CHATBOT_UPLOAD_DIR

class OrjsonResponse(JSONResponse):
    """orjson 기반 고성능 JSON 응답 클래스."""

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)


router = APIRouter(default_response_class=OrjsonResponse)

# ── 노드 진행 상태 메시지 ─────────────────────────────────────────────────────
NODE_STATUS_MESSAGES: dict[str, str] = {
    "guardrail":            "입력 내용을 검토하고 있습니다...",
    "planner":              "요청을 분석하고 있습니다...",
    "supervisor":           "작업을 배분하고 있습니다...",
    "order_entry":          "주문 요청을 준비하고 있습니다...",
    "order_intent_router":  "주문 요청 유형을 확인하고 있습니다...",
    "cancel_subagent":      "주문 취소를 처리하고 있습니다...",
    "refund_subagent":      "반품 신청을 처리하고 있습니다...",
    "exchange_subagent":    "교환 요청을 처리하고 있습니다...",
    "shipping_subagent":    "배송 정보를 확인하고 있습니다...",
    "discovery_subagent":   "상품을 검색하고 있습니다...",
    "policy_rag_subagent":  "정책 문서를 조회하고 있습니다...",
    "form_action_subagent": "요청을 처리하고 있습니다...",
    "final_generator":      "최종 응답을 작성하고 있습니다...",
}

# ── 도구 진행 상태 메시지 ─────────────────────────────────────────────────────
TOOL_STATUS_MESSAGES: dict[str, str] = {
    "cancel":                     "주문 취소를 처리하고 있습니다...",
    "refund":                     "반품 신청을 처리하고 있습니다...",
    "exchange":                   "교환 신청을 처리하고 있습니다...",
    "shipping":                   "배송 정보를 확인하고 있습니다...",
    "change_option":              "주문 옵션을 변경하고 있습니다...",
    "update_payment":             "결제 정보를 수정하고 있습니다...",
    "search_by_text_clip":        "추천 스타일 상품을 검색하고 있습니다...",
    "search_by_image":            "이미지와 유사한 상품을 검색하고 있습니다...",
    "recommend_clothes":          "스타일 추천을 준비하고 있습니다...",
    "search_knowledge_base":      "정책 문서를 검색하고 있습니다...",
    "open_used_sale_form":        "중고 판매 등록 폼을 열고 있습니다...",
    "register_used_sale":         "중고 상품을 등록하고 있습니다...",
    "create_review":              "리뷰를 등록하고 있습니다...",
    "register_gift_card":         "상품권을 등록하고 있습니다...",
}

# 다음 턴에 넘기지 않을 per-turn 필드 (매 요청마다 리셋)
_PER_TURN_FIELDS = frozenset({
    "pending_tasks",
    "completed_tasks",
    "current_active_task",
    "agent_results",
    "guardrail_passed",
    "messages",
    "turn_id",
})

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}

# ── 직렬화 / 역직렬화 ──────────────────────────────────────────────────────────

def _serialize_messages(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    """BaseMessage 리스트를 LangChain 표준 dict 포맷으로 직렬화."""
    return messages_to_dict(messages)


def _deserialize_messages(serialized: Any) -> List[BaseMessage]:
    """
    state.messages 역직렬화.
    - 표준: LangChain messages_from_dict 포맷
    - 레거시: {role, content} 포맷 (하위호환)
    """
    if not isinstance(serialized, list):
        return []

    # 1) LangChain 표준 포맷
    try:
        if serialized and isinstance(serialized[0], dict) and {"type", "data"}.issubset(serialized[0]):
            return messages_from_dict(serialized)
    except Exception:
        pass

    # 2) 레거시 포맷 하위호환
    messages: List[BaseMessage] = []
    for m in serialized:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


# ── 헬퍼 함수 ──────────────────────────────────────────────────────────────────

def _parse_tool_output(output: Any) -> dict | None:
    """도구 출력을 딕셔너리로 변환. 파싱 실패 시 None 반환."""
    if isinstance(output, dict):
        return output
    if isinstance(output, BaseMessage) and isinstance(output.content, str):
        try:
            return orjson.loads(output.content)
        except Exception:
            pass
    return None


def _normalize_image_extension(filename: str | None, content_type: str | None) -> str:
    name_ext = os.path.splitext((filename or "").lower())[1]
    if name_ext in ALLOWED_IMAGE_EXTENSIONS:
        return name_ext
    if content_type:
        normalized = content_type.split(";")[0].strip().lower()
        if normalized == "image/jpeg":
            return ".jpg"
        if normalized == "image/png":
            return ".png"
        if normalized == "image/webp":
            return ".webp"
        if normalized == "image/gif":
            return ".gif"
        if normalized == "image/bmp":
            return ".bmp"
        if normalized == "image/avif":
            return ".avif"
    return ".jpg"


def _resolve_image_url(raw_image_url: Any) -> str | None:
    if isinstance(raw_image_url, dict):
        value = raw_image_url.get("_url") or raw_image_url.get("url")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    if isinstance(raw_image_url, str) and raw_image_url.strip():
        return raw_image_url.strip()

    return None


def _preprocess_user_message(message: str) -> tuple[str, dict[str, Any]]:
    """
    프론트 구조화 이벤트(JSON 문자열)를 자연어 메시지 + 상태 갱신으로 변환.
    현재는 image_uploaded 이벤트만 특수 처리한다.
    """
    try:
        payload = orjson.loads(message)
    except Exception:
        return message, {}

    if not isinstance(payload, dict):
        return message, {}

    event_name = str(payload.get("event") or "").strip().lower()
    if event_name != "image_uploaded":
        return message, {}

    image_url = _resolve_image_url(payload.get("image_url") or payload.get("imageUrl"))
    query = str(payload.get("query") or "").strip()
    description = str(payload.get("description") or "").strip()
    base_text = query or description or "이미지 업로드 완료"

    normalized_message = base_text
    if image_url:
        normalized_message = f"{base_text}\n[image_url]: {image_url}"

    search_context_update: dict[str, Any] = {}
    if image_url:
        search_context_update["image_url"] = image_url
    if query:
        search_context_update["search_query"] = query

    return normalized_message, search_context_update


def _build_metadata(final_state: dict) -> dict:
    """
    최종 상태 → 프론트엔드 전송용 metadata 이벤트 생성.
    state 필드에는 다음 턴에 재사용할 지속 상태만 포함 (per-turn 필드 제외).
    """
    persistent_state = {
        k: v for k, v in final_state.items()
        if k not in _PER_TURN_FIELDS
    }
    persistent_state["messages"] = _serialize_messages(final_state.get("messages", []))
    persistent_state["awaiting_interrupt"] = False
    persistent_state.pop("pending_interrupt", None)

    return {
        "type":               "metadata",
        "completed_tasks":    final_state.get("completed_tasks", []),
        "ui_action_required": final_state.get("ui_action_required"),
        "state":              persistent_state,
    }


def _get_fallback_text(final_state: dict) -> str | None:
    """
    LLM 토큰 스트리밍이 없었을 때 마지막 AIMessage 텍스트 반환.
    final_generator 가 LLM 호출 없이 messages 를 직접 반환하는 경우 사용.
    """
    for msg in reversed(final_state.get("messages", [])):
        if isinstance(msg, AIMessage):
            content = getattr(msg, "content", "")
            return str(content).strip() or None
    return None


def _get_session_logger(current_user: User, conversation_id: str) -> SessionConversationLogger:
    return SessionConversationLogger(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )


def _resolve_assistant_log_text(
    final_state: dict | None,
    streamed_text_parts: list[str],
    latest_ui_message: str | None,
) -> str | None:
    streamed_text = "".join(streamed_text_parts).strip()
    if streamed_text:
        return streamed_text

    if latest_ui_message and latest_ui_message.strip():
        return latest_ui_message.strip()

    if isinstance(final_state, dict):
        fallback = _get_fallback_text(final_state)
        if fallback:
            return fallback

    return None


def _append_session_turn_log(
    *,
    current_user: User,
    conversation_id: str,
    user_message: str,
    assistant_message: str | None,
    state: dict | None,
) -> None:
    if not assistant_message:
        return

    _get_session_logger(current_user, conversation_id).append_turn(
        user_message=user_message,
        assistant_message=assistant_message,
        state=state,
    )


def _to_sse(payload: dict) -> bytes:
    """dict payload를 SSE data 라인(bytes)으로 변환."""
    return b"data: " + orjson.dumps(payload) + b"\n\n"


def _build_ui_action_payload(tool_output: dict) -> dict:
    """도구 출력 기반 UI 액션 payload 생성."""
    ui_action = str(tool_output["ui_action"])
    ui_data = tool_output.get("ui_data")
    if ui_action == "show_product_list" and ui_data is None:
        # recommendation_tools 계열은 products 키를 사용하므로 호환 처리
        products = tool_output.get("products")
        if isinstance(products, list):
            ui_data = products

    return {
        "type": "ui_action",
        "ui_action": ui_action,
        "ui_data": ui_data,
        "requires_selection": tool_output.get("requires_selection", False),
        "prior_action": tool_output.get("prior_action"),
        "message": tool_output.get("message", ""),
    }


def _get_state_ui_payload(final_state: dict, ui_action: str) -> dict | None:
    order_context = final_state.get("order_context", {})
    if not isinstance(order_context, dict):
        return None

    payload = order_context.get("last_ui_payload")
    if not isinstance(payload, dict):
        return None

    payload_action = str(payload.get("ui_action") or "").strip()
    if payload_action != ui_action:
        return None

    return _build_ui_action_payload(payload)


def _extract_interrupt_payloads(final_state: dict | None) -> list[dict]:
    """LangGraph interrupt 결과를 UI 친화 payload 리스트로 변환."""
    if not isinstance(final_state, dict):
        return []

    raw_interrupts = final_state.get("__interrupt__")
    if raw_interrupts is None:
        return []

    if not isinstance(raw_interrupts, (list, tuple, set)):
        raw_interrupts = [raw_interrupts]

    payloads: list[dict] = []
    for item in raw_interrupts:
        value = None

        if isinstance(item, dict):
            value = item.get("value")
        else:
            value = getattr(item, "value", None)

        if isinstance(value, dict):
            payloads.append(value)
        elif value is not None:
            payloads.append({"message": str(value)})

    return payloads


def _extract_interrupt_payloads_from_snapshot(snapshot: Any) -> list[dict]:
    """checkpointer snapshot에서 interrupt payload 추출 (on_chain_end 누락 대비)."""
    payloads: list[dict] = []

    if snapshot is None:
        return payloads

    # 1) 최신 LangGraph: snapshot.interrupts
    raw_interrupts = getattr(snapshot, "interrupts", None)
    if isinstance(raw_interrupts, (list, tuple, set)):
        for item in raw_interrupts:
            value = getattr(item, "value", None)
            if isinstance(value, dict):
                payloads.append(value)
            elif value is not None:
                payloads.append({"message": str(value)})

    if payloads:
        return payloads

    # 2) 일부 런타임: snapshot.tasks[*].interrupts
    tasks = getattr(snapshot, "tasks", None)
    if isinstance(tasks, (list, tuple, set)):
        for task in tasks:
            task_interrupts = getattr(task, "interrupts", None)
            if not isinstance(task_interrupts, (list, tuple, set)):
                continue
            for item in task_interrupts:
                value = getattr(item, "value", None)
                if isinstance(value, dict):
                    payloads.append(value)
                elif value is not None:
                    payloads.append({"message": str(value)})

    return payloads


def _build_current_state(
    request: ChatRequest,
    current_user: User,
    previous_state: dict,
    provider: str,
    model: str,
    conversation_id: str,
    turn_id: str,
    access_token: str | None = None,
) -> dict:
    """요청/이전 상태 기반 GlobalAgentState 구성."""
    history = _deserialize_messages(previous_state.get("messages", []))
    normalized_message, search_context_update = _preprocess_user_message(request.message)
    turn_defaults = {
        "pending_tasks": [],
        "completed_tasks": [],
        "current_active_task": None,
        "agent_results": {},
        "ui_action_required": None,
        "guardrail_passed": True,
    }

    return {
        # 지속 필드: 이전 턴 컨텍스트 유지 (HITL 다중 턴 시나리오 대응)
        "order_context": previous_state.get("order_context", {}),
        "search_context": {
            **previous_state.get("search_context", {}),
            **search_context_update,
        },
        # 대화 요약: summarize_node가 생성한 압축 이력 (없으면 None)
        "conversation_summary": previous_state.get("conversation_summary"),
        # 메시지: 이전 이력 + 현재 입력
        "messages": history + [HumanMessage(content=normalized_message)],
        # per-turn 초기화 (이전 턴 값 오염 방지)
        **turn_defaults,
        # 사용자 / LLM / 세션
        "user_info": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "site_id": request.site_id,
            "access_token": access_token,
        },
        "llm_provider": provider,
        "llm_model": model,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
    }


def _build_stream_config(
    current_user: User,
    provider: str,
    model: str,
    conversation_id: str,
    turn_id: str,
) -> RunnableConfig:
    """LangSmith 사용 설정 시 RunnableConfig 생성."""
    base_config = RunnableConfig(
        configurable={"thread_id": conversation_id},
        run_name=f"chat/{conversation_id}/{turn_id}",
        metadata={
            "user_id": str(current_user.id),
            "user_email": current_user.email,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "llm_provider": provider,
            "llm_model": model,
        },
        tags=["chatbot", provider, model],
    )

    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() != "true":
        return base_config

    langsmith_project = os.getenv("LANGCHAIN_PROJECT", "Ecommerce-Chatbot")
    tracer = LangChainTracer(project_name=langsmith_project)
    base_config["callbacks"] = [tracer]
    return base_config


def _get_text_chunk_payload(event: Any) -> dict | None:
    """final_generator의 토큰 스트리밍 payload 생성."""
    if event.get("event") != "on_chat_model_stream":
        return None
    node_name = event.get("metadata", {}).get("langgraph_node", "")
    if node_name != "final_generator":
        return None

    chunk = event.get("data", {}).get("chunk")
    content = chunk.content if chunk else None
    if not content:
        return None
    return {"type": "text_chunk", "content": content}


def _get_chain_status_payload(event: Any) -> dict | None:
    """노드 시작 이벤트의 상태 메시지 payload 생성."""
    if event.get("event") != "on_chain_start":
        return None
    node_name = event.get("name", "")
    status_msg = NODE_STATUS_MESSAGES.get(node_name)
    if not status_msg:
        return None
    return {"type": "status_update", "status": status_msg, "node": node_name}


def _get_tool_status_payload(event: Any) -> dict | None:
    """도구 시작 이벤트의 상태 메시지 payload 생성."""
    if event.get("event") != "on_tool_start":
        return None
    tool_name = event.get("name", "unknown_tool")
    status_msg = TOOL_STATUS_MESSAGES.get(tool_name)
    if not status_msg:
        return None
    return {"type": "status_update", "status": status_msg}


def _get_tool_ui_payload(event: Any) -> dict | None:
    """도구 종료 이벤트에서 UI 액션 payload 생성."""
    if event.get("event") != "on_tool_end":
        return None
    raw_output = event.get("data", {}).get("output")
    tool_output = _parse_tool_output(raw_output)
    if not tool_output or not tool_output.get("ui_action"):
        return None
    return _build_ui_action_payload(tool_output)


def _is_langgraph_end_event(event: Any) -> bool:
    """최상위/그래프 종료 이벤트 후보 여부 (런타임별 name 차이 대응)."""
    if event.get("event") != "on_chain_end":
        return False

    output = event.get("data", {}).get("output")
    if isinstance(output, dict) and (
        "messages" in output or "__interrupt__" in output or "ui_action_required" in output
    ):
        return True

    return event.get("name") == "LangGraph"


@router.post("/upload-image")
async def upload_chat_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """이미지 업로드 후 챗봇 접근 가능한 URL 반환."""
    _ = current_user
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드할 수 있습니다.")

    filename = f"{uuid4().hex}{_normalize_image_extension(file.filename, content_type)}"
    target_path = CHATBOT_UPLOAD_DIR / filename

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="빈 이미지 파일은 업로드할 수 없습니다.")
        target_path.write_bytes(contents)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="이미지를 저장하는 중 오류가 발생했습니다.",
        ) from exc

    image_url = request.url_for("chatbot_uploads", path=filename)
    return {"url": str(image_url)}



# ── 스트리밍 엔드포인트 ────────────────────────────────────────────────────────
@router.post("/stream")
async def chat_streaming_endpoint(
    http_request: Request,
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """SSE 스트리밍으로 챗봇 응답 반환."""

    async def event_generator():
        try:
            previous_state: dict = request.previous_state or {}
            provider = (
                (request.provider or previous_state.get("llm_provider") or "openai")
                .strip().lower()
            )
            model = (request.model or previous_state.get("llm_model") or "gpt-4o-mini").strip()
            conversation_id = previous_state.get("conversation_id") or f"conv_{uuid4().hex[:12]}"
            turn_id = f"turn_{uuid4().hex[:12]}"

            pending_interrupt = previous_state.get("pending_interrupt")

            stream_input: dict | Command
            if pending_interrupt:
                if not request.resume_payload:
                    first_payload = (
                        pending_interrupt[0]
                        if isinstance(pending_interrupt, list) and pending_interrupt
                        else None
                    )
                    ui_action = "confirm_order_action"
                    message = "진행을 위해 선택값이 필요합니다."
                    if isinstance(first_payload, dict):
                        ui_action = str(first_payload.get("ui_action") or ui_action)
                        message = str(first_payload.get("message") or message)

                    if isinstance(first_payload, dict) and first_payload.get("ui_action"):
                        ui_payload = _build_ui_action_payload(first_payload)
                    else:
                        ui_payload = {
                            "type": "ui_action",
                            "ui_action": ui_action,
                            "message": message,
                            "ui_data": first_payload,
                        }

                    yield _to_sse(ui_payload)
                    yield _to_sse(
                        {
                            "type": "metadata",
                            "completed_tasks": previous_state.get("completed_tasks", []),
                            "ui_action_required": ui_action,
                            "state": {
                                **previous_state,
                                "awaiting_interrupt": True,
                                "pending_interrupt": pending_interrupt,
                            },
                        }
                    )
                    yield _to_sse({"type": "done"})
                    return

                stream_input = Command(resume=request.resume_payload)
            else:
                current_state = _build_current_state(
                    request=request,
                    current_user=current_user,
                    previous_state=previous_state,
                    provider=provider,
                    model=model,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    access_token=(
                        http_request.cookies.get("access_token")
                        or http_request.cookies.get("session_token")
                    ),
                )
                stream_input = current_state

            stream_config = _build_stream_config(
                current_user=current_user,
                provider=provider,
                model=model,
                conversation_id=conversation_id,
                turn_id=turn_id,
            )

            # ── 이벤트 스트리밍 ──────────────────────────────────────────────
            final_state: dict | None = None
            has_streamed_text = False
            streamed_ui_actions: set[str] = set()
            suppress_text_stream = False
            streamed_text_parts: list[str] = []
            latest_ui_message: str | None = None

            async for event in graph_app.astream_events(stream_input, version="v2", config=stream_config):
                text_payload = _get_text_chunk_payload(event)
                if text_payload:
                    if suppress_text_stream:
                        continue
                    has_streamed_text = True
                    streamed_text_parts.append(str(text_payload["content"]))
                    yield _to_sse(text_payload)
                    continue

                chain_status_payload = _get_chain_status_payload(event)
                if chain_status_payload:
                    yield _to_sse(chain_status_payload)
                    continue

                tool_status_payload = _get_tool_status_payload(event)
                if tool_status_payload:
                    yield _to_sse(tool_status_payload)
                    continue

                tool_ui_payload = _get_tool_ui_payload(event)
                if tool_ui_payload:
                    streamed_ui_actions.add(tool_ui_payload["ui_action"])
                    ui_message = str(tool_ui_payload.get("message") or "").strip()
                    if ui_message:
                        latest_ui_message = ui_message
                    # UI 액션이 나온 턴은 텍스트를 함께 흘리지 않음
                    suppress_text_stream = True
                    yield _to_sse(tool_ui_payload)
                    continue

                if _is_langgraph_end_event(event):
                    output = event.get("data", {}).get("output")
                    if isinstance(output, dict):
                        final_state = output

            # ── 스트림 종료 후 처리 ──────────────────────────────────────────
            interrupt_payloads: list[dict] = []
            if isinstance(final_state, dict):
                interrupt_payloads = _extract_interrupt_payloads(final_state)

            # on_chain_end 누락/비정형 이벤트 대비: snapshot에서 interrupt 복구
            if not interrupt_payloads:
                try:
                    snapshot = await graph_app.aget_state(stream_config)
                    interrupt_payloads = _extract_interrupt_payloads_from_snapshot(snapshot)
                except Exception:
                    interrupt_payloads = []

            # interrupt가 있으면 반드시 pending_interrupt를 저장해 다음 턴 resume 가능하게 함
            if interrupt_payloads:
                first_ui_action = "confirm_order_action"
                if isinstance(interrupt_payloads[0], dict):
                    first_ui_action = str(interrupt_payloads[0].get("ui_action") or first_ui_action)

                for payload in interrupt_payloads:
                    ui_name = str(payload.get("ui_action") or "confirm_order_action")

                    # 이미 on_tool_end에서 같은 UI를 보냈으면 중복 전송 생략
                    if ui_name in streamed_ui_actions:
                        continue

                    if payload.get("ui_action"):
                        ui_payload = _build_ui_action_payload(payload)
                        ui_message = str(ui_payload.get("message") or "").strip()
                        if ui_message:
                            latest_ui_message = ui_message
                        yield _to_sse(ui_payload)
                    else:
                        message = payload.get("message", "진행 여부를 확인해주세요.")
                        latest_ui_message = str(message).strip() or latest_ui_message
                        yield _to_sse(
                            {
                                "type": "ui_action",
                                "ui_action": "confirm_order_action",
                                "message": message,
                                "ui_data": payload,
                            }
                        )

                persisted_state = {
                    **previous_state,
                    "conversation_id": conversation_id,
                    "llm_provider": provider,
                    "llm_model": model,
                    "awaiting_interrupt": True,
                    "pending_interrupt": interrupt_payloads,
                }

                yield _to_sse(
                    {
                        "type": "metadata",
                        "completed_tasks": previous_state.get("completed_tasks", []),
                        "ui_action_required": first_ui_action,
                        "state": persisted_state,
                    }
                )
                _append_session_turn_log(
                    current_user=current_user,
                    conversation_id=conversation_id,
                    user_message=request.message,
                    assistant_message=latest_ui_message,
                    state=persisted_state,
                )
                yield _to_sse({"type": "done"})
                return

            if isinstance(final_state, dict):
                ui_req = final_state.get("ui_action_required")

                # final_generator 가 직접 messages만 반환한 경우(토큰 스트리밍 없음)
                # 마지막 AIMessage를 text_chunk로 보강 전송
                if not has_streamed_text and not ui_req and not streamed_ui_actions:
                    fallback = _get_fallback_text(final_state)
                    if fallback:
                        yield _to_sse({"type": "text_chunk", "content": fallback})

                # ui_action_required 가 on_tool_end 에서 미전송된 경우 보강 시그널
                if ui_req and ui_req not in streamed_ui_actions:
                    state_ui_payload = _get_state_ui_payload(final_state, ui_req)
                    if state_ui_payload:
                        ui_msg = str(state_ui_payload.get("message") or "").strip()
                        if ui_msg:
                            latest_ui_message = ui_msg
                        yield _to_sse(state_ui_payload)
                    else:
                        ui_data = None
                        if ui_req == "show_product_list":
                            ui_data = (
                                final_state.get("search_context", {}).get("retrieved_products", [])
                                if isinstance(final_state.get("search_context"), dict)
                                else []
                            )
                        try:
                            ui_len = len(ui_data) if isinstance(ui_data, list) else "n/a"
                            print(f"[chat.stream] emit ui_action={ui_req}, ui_len={ui_len}")
                        except Exception:
                            pass
                        latest_ui_message = str(final_state.get("generation") or "").strip() or latest_ui_message
                        yield _to_sse({"type": "ui_action", "ui_action": ui_req, "ui_data": ui_data})

                metadata_payload = _build_metadata(final_state)
                yield _to_sse(metadata_payload)
                _append_session_turn_log(
                    current_user=current_user,
                    conversation_id=conversation_id,
                    user_message=request.message,
                    assistant_message=_resolve_assistant_log_text(
                        final_state=final_state,
                        streamed_text_parts=streamed_text_parts,
                        latest_ui_message=latest_ui_message,
                    ),
                    state=metadata_payload.get("state"),
                )

            yield _to_sse({"type": "done"})

        except Exception as e:
            traceback.print_exc()
            yield _to_sse({"type": "error", "message": f"오류가 발생했습니다: {str(e)}"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/feedback")
async def submit_chat_feedback(
    request: FeedbackRequest,
    current_user: User = Depends(get_current_user),
):
    session_logger = _get_session_logger(current_user, request.conversation_id)

    if not session_logger.file_path.exists():
        raise HTTPException(status_code=404, detail="대화 로그를 찾을 수 없습니다.")

    finalized = session_logger.record_feedback(request.feedback_label)
    return {
        "conversation_id": finalized["conversation_id"],
        "status": finalized["status"],
        "feedback_label": finalized["feedback_label"],
        "reset_required": finalized["reset_required"],
        "state": None,
        "messages": [],
    }


# ── 리뷰 초안 엔드포인트 ──────────────────────────────────────────────────────

@router.post("/review-draft")
async def generate_review_draft_endpoint(
    request: ReviewDraftRequest,
    current_user: User = Depends(get_current_user),
):
    """만족도 + 상품명 기반 리뷰 초안 생성."""
    try:
        result = await generate_review_draft.ainvoke({
            "product_name": request.product_name,
            "satisfaction": request.satisfaction,
            "keywords":     request.keywords or [],
        })
        if isinstance(result, str):
            try:
                result = orjson.loads(result)
            except Exception:
                pass
        if isinstance(result, dict) and "drafts" in result:
            return result
        return {"success": True, "drafts": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
