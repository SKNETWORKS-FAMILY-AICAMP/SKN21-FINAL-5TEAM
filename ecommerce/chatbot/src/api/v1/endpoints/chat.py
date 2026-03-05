"""
챗봇 스트리밍 엔드포인트.

GlobalAgentState 기반으로 재작성.
- 상태 초기화: per-turn 필드 매 요청마다 리셋, 이전 턴 오염 방지.
- 토큰 스트리밍: planner 노드(structured JSON) 제외, 나머지 LLM 토큰 전달.
- UI 액션: on_tool_end 이벤트에서 즉시 전달.
- 메타데이터: completed_tasks, ui_action_required + 다음 턴용 persistent state.
"""

import json
import os
import traceback
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tracers import LangChainTracer

from ecommerce.chatbot.src.graph.workflow import graph_app
from ecommerce.chatbot.src.infrastructure.conversation_logger import ConversationRunLogger
from ecommerce.chatbot.src.schemas.chat import ChatRequest, ReviewDraftRequest
from ecommerce.chatbot.src.tools.service_tools import generate_review_draft
from ecommerce.platform.backend.app.core.auth import get_current_user
from ecommerce.platform.backend.app.router.users.models import User
from ecommerce.platform.backend.app.uploads import CHATBOT_UPLOAD_DIR
from pathlib import Path

router = APIRouter()

# ── 노드 진행 상태 메시지 ─────────────────────────────────────────────────────
NODE_STATUS_MESSAGES: dict[str, str] = {
    "guardrail":            "입력 내용을 검토하고 있습니다...",
    "planner":              "요청을 분석하고 있습니다...",
    "supervisor":           "작업을 배분하고 있습니다...",
    "refund_subagent":      "주문/환불 정보를 처리하고 있습니다...",
    "discovery_subagent":   "상품을 검색하고 있습니다...",
    "policy_rag_subagent":  "정책 문서를 조회하고 있습니다...",
    "form_action_subagent": "요청을 처리하고 있습니다...",
    "final_generator":      "최종 응답을 작성하고 있습니다...",
}

# ── 도구 진행 상태 메시지 ─────────────────────────────────────────────────────
TOOL_STATUS_MESSAGES: dict[str, str] = {
    "get_user_orders":            "주문 내역을 조회하고 있습니다...",
    "get_order_details":          "주문 상세 정보를 확인하고 있습니다...",
    "cancel_order":               "주문 취소를 처리하고 있습니다...",
    "check_refund_eligibility":   "환불 가능 여부를 확인하고 있습니다...",
    "register_return_request":    "반품 신청을 처리하고 있습니다...",
    "check_exchange_eligibility": "교환 가능 여부를 확인하고 있습니다...",
    "register_exchange_request":  "교환 신청을 처리하고 있습니다...",
    "open_address_search":        "주소 검색 창을 열고 있습니다...",
    "search_products_vector":     "유사 상품을 검색하고 있습니다...",
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



# ── 직렬화 / 역직렬화 ──────────────────────────────────────────────────────────

def serialize_messages(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    """BaseMessage 리스트 → JSON 직렬화 가능한 dict 리스트."""
    role_map = {HumanMessage: "user", AIMessage: "assistant"}
    return [
        {"role": role_map.get(type(m), "system"), "content": m.content}
        for m in messages
    ]


def deserialize_messages(serialized: List[Dict[str, Any]]) -> List[BaseMessage]:
    """JSON dict 리스트 → BaseMessage 리스트."""
    msg_map = {"user": HumanMessage, "assistant": AIMessage}
    return [
        msg_map[m["role"]](content=m.get("content", ""))
        for m in serialized
        if m.get("role") in msg_map
    ]


# ── 헬퍼 함수 ──────────────────────────────────────────────────────────────────

def _parse_tool_output(output: Any) -> dict | None:
    """도구 출력을 딕셔너리로 변환. 파싱 실패 시 None 반환."""
    if isinstance(output, dict):
        return output
    if isinstance(output, BaseMessage) and isinstance(output.content, str):
        try:
            return json.loads(output.content)
        except Exception:
            pass
    return None


def _build_metadata(final_state: dict) -> dict:
    """
    최종 상태 → 프론트엔드 전송용 metadata 이벤트 생성.
    state 필드에는 다음 턴에 재사용할 지속 상태만 포함 (per-turn 필드 제외).
    """
    persistent_state = {
        k: v for k, v in final_state.items()
        if k not in _PER_TURN_FIELDS
    }
    persistent_state["messages"] = serialize_messages(final_state.get("messages", []))

    return {
        "type":               "metadata",
        "completed_tasks":    final_state.get("completed_tasks", []),
        "ui_action_required": final_state.get("ui_action_required"),
        "state":              persistent_state,
    }


def _get_fallback_text(final_state: dict) -> str | None:
    """
    LLM 토큰 스트리밍이 없었을 때 마지막 AIMessage 텍스트 반환.
    final_generator 가 LLM 호출 없이 agent_results 를 직접 반환하는 경우 사용.
    """
    for msg in reversed(final_state.get("messages", [])):
        if isinstance(msg, AIMessage):
            content = getattr(msg, "content", "")
            return str(content).strip() or None
    return None



# ── 스트리밍 엔드포인트 ────────────────────────────────────────────────────────

@router.post("/stream")
async def chat_streaming_endpoint(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """SSE 스트리밍으로 챗봇 응답 반환."""

    async def event_generator():
        run_logger = None
        try:
            previous_state: dict = request.previous_state or {}
            provider = (
                (request.provider or previous_state.get("llm_provider") or "openai")
                .strip().lower()
            )
            model = (request.model or previous_state.get("llm_model") or "gpt-4o-mini").strip()
            conversation_id = previous_state.get("conversation_id") or f"conv_{uuid4().hex[:12]}"
            turn_id = f"turn_{uuid4().hex[:12]}"

            # 대화 이력 복원
            history = deserialize_messages(previous_state.get("messages", []))

            # ── GlobalAgentState 초기화 ──────────────────────────────────────
            current_state: dict = {
                # 지속 필드: 이전 턴 컨텍스트 유지 (HITL 다중 턴 시나리오 대응)
                "order_context":  previous_state.get("order_context", {}),
                "search_context": previous_state.get("search_context", {}),

                # 대화 요약: summarize_node가 생성한 압축 이력 (없으면 None)
                "conversation_summary": previous_state.get("conversation_summary"),

                # 메시지: 이전 이력 + 현재 입력
                "messages": history + [HumanMessage(content=request.message)],

                # per-turn 초기화 (이전 턴 값 오염 방지)
                "pending_tasks":       [],
                "completed_tasks":     [],
                "current_active_task": None,
                "agent_results":       {},
                "ui_action_required":  None,
                "guardrail_passed":    True,

                # 사용자 / LLM / 세션
                "user_info": {
                    "id":    current_user.id,
                    "name":  current_user.name,
                    "email": current_user.email,
                },
                "llm_provider":    provider,
                "llm_model":       model,
                "conversation_id": conversation_id,
                "turn_id":         turn_id,
            }

            run_logger = ConversationRunLogger(
                conversation_id=conversation_id,
                turn_id=turn_id,
                user_id=current_user.id,
                provider=provider,
                model=model,
            )
            run_logger.set_input(request.message, current_state)

            # ── LangSmith 트레이싱 config ────────────────────────────────────
            langsmith_config: dict = {}
            if os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true":
                langsmith_project = os.getenv("LANGCHAIN_PROJECT", "Ecommerce-Chatbot")
                tracer = LangChainTracer(project_name=langsmith_project)
                langsmith_config = {
                    "run_name": f"chat/{conversation_id}/{turn_id}",
                    "metadata": {
                        "user_id":         str(current_user.id),
                        "user_email":      current_user.email,
                        "conversation_id": conversation_id,
                        "turn_id":         turn_id,
                        "llm_provider":    provider,
                        "llm_model":       model,
                    },
                    "tags": ["chatbot", provider, model],
                    "callbacks": [tracer],
                }

            # ── 이벤트 스트리밍 ──────────────────────────────────────────────
            final_state: dict | None = None
            has_streamed_text = False
            streamed_ui_actions: set[str] = set()
            last_langgraph_input = None

            async for event in graph_app.astream_events(current_state, version="v2", config=RunnableConfig(**langsmith_config) if langsmith_config else None):
                etype = event["event"]

                # A. LLM 토큰 스트리밍
                #    planner 는 structured JSON 출력 → 사용자에게 전달하지 않음
                if etype == "on_chat_model_stream":
                    node_name = event.get("metadata", {}).get("langgraph_node", "")
                    if node_name == "planner":
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    content = chunk.content if chunk else None
                    if content:
                        has_streamed_text = True
                        yield f"data: {json.dumps({'type': 'text_chunk', 'content': content}, ensure_ascii=False)}\n\n"

                # B. 노드 실행 시작 (진행 상태 표시 + 로깅)
                elif etype == "on_chain_start":
                    node_name = event.get("name", "")
                    if node_name == "LangGraph":
                        last_langgraph_input = event.get("data", {}).get("input")
                    else:
                        run_logger.log_node_start(node_name, event.get("data", {}).get("input"))
                    status_msg = NODE_STATUS_MESSAGES.get(node_name)
                    if status_msg:
                        yield f"data: {json.dumps({'type': 'status_update', 'status': status_msg, 'node': node_name}, ensure_ascii=False)}\n\n"

                # C. 도구 실행 시작 (진행 상태 표시 + 로깅)
                elif etype == "on_tool_start":
                    tool_name = event.get("name", "unknown_tool")
                    run_logger.log_tool_start(tool_name, event.get("data", {}).get("input"))
                    status_msg = TOOL_STATUS_MESSAGES.get(tool_name)
                    if status_msg:
                        yield f"data: {json.dumps({'type': 'status_update', 'status': status_msg}, ensure_ascii=False)}\n\n"

                # D. 도구 실행 완료 (UI 액션 즉시 전달)
                elif etype == "on_tool_end":
                    tool_name = event.get("name", "unknown_tool")
                    raw_output = event.get("data", {}).get("output")
                    run_logger.log_tool_end(tool_name, raw_output)

                    tool_output = _parse_tool_output(raw_output)
                    if tool_output and tool_output.get("ui_action"):
                        ui_action_name = str(tool_output["ui_action"])
                        streamed_ui_actions.add(ui_action_name)
                        yield f"data: {json.dumps({'type': 'ui_action', 'ui_action': ui_action_name, 'ui_data': tool_output.get('ui_data'), 'requires_selection': tool_output.get('requires_selection', False), 'prior_action': tool_output.get('prior_action'), 'message': tool_output.get('message', '')}, ensure_ascii=False)}\n\n"

                # E. 모델 호출 시작/종료 로깅
                elif etype == "on_chat_model_start":
                    run_logger.log_model_start(
                        event.get("name") or "chat_model",
                        event.get("data", {}).get("input"),
                    )
                elif etype == "on_chat_model_end":
                    run_logger.log_model_end(
                        event.get("name") or "chat_model",
                        event.get("data", {}).get("output"),
                    )

                # F. 노드 실행 완료 (최종 상태 캡처 + 로깅)
                elif etype == "on_chain_end":
                    if event.get("name") == "LangGraph":
                        final_state = event["data"].get("output")
                        if isinstance(last_langgraph_input, dict) and isinstance(final_state, dict):
                            run_logger.log_state_change(last_langgraph_input, final_state)
                    else:
                        run_logger.log_node_end(
                            event.get("name") or "unknown_node",
                            event.get("data", {}).get("output"),
                        )

            # ── 스트림 종료 후 처리 ──────────────────────────────────────────
            if isinstance(final_state, dict):
                # 토큰 스트림이 없었던 경우 (final_generator가 LLM 호출 없이 직접 반환)
                # → 마지막 AIMessage 텍스트를 폴백으로 전송
                if not has_streamed_text:
                    fallback = _get_fallback_text(final_state)
                    if fallback:
                        yield f"data: {json.dumps({'type': 'text_chunk', 'content': fallback}, ensure_ascii=False)}\n\n"

                # ui_action_required 가 on_tool_end 에서 미전송된 경우 보강 시그널
                ui_req = final_state.get("ui_action_required")
                if ui_req and ui_req not in streamed_ui_actions:
                    yield f"data: {json.dumps({'type': 'ui_action', 'ui_action': ui_req, 'ui_data': None}, ensure_ascii=False)}\n\n"

                yield f"data: {json.dumps(_build_metadata(final_state), ensure_ascii=False)}\n\n"
                log_path = run_logger.finalize(final_state, success=True)
            else:
                log_path = run_logger.finalize(
                    {"messages": current_state.get("messages", [])}, success=True
                )

            yield f"data: {json.dumps({'type': 'audit_log', 'conversation_id': conversation_id, 'turn_id': turn_id, 'log_path': log_path}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            traceback.print_exc()
            try:
                if run_logger:
                    run_logger.log_error("chat_streaming_endpoint", str(e))
                    run_logger.finalize(None, success=False, error_message=str(e))
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': f'오류가 발생했습니다: {str(e)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── 리뷰 초안 엔드포인트 ──────────────────────────────────────────────────────

@router.post("/review-draft")
async def generate_review_draft_endpoint(
    request: ReviewDraftRequest,
    current_user: User = Depends(get_current_user),
):
    """만족도 + 상품명 기반 리뷰 초안 생성."""
    try:
        result = generate_review_draft.invoke({
            "product_name": request.product_name,
            "satisfaction": request.satisfaction,
            "keywords":     request.keywords or [],
        })
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                pass
        if isinstance(result, dict) and "drafts" in result:
            return result
        return {"success": True, "drafts": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
