from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any
import json
from uuid import uuid4
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from ecommerce.chatbot.src.schemas.chat import ChatRequest, ReviewDraftRequest
from ecommerce.chatbot.src.graph.workflow import graph_app
from ecommerce.chatbot.src.tools.service_tools import generate_review_draft
from ecommerce.chatbot.src.infrastructure.conversation_logger import (
    ConversationRunLogger,
)
from ecommerce.platform.backend.app.core.auth import get_current_user
from ecommerce.platform.backend.app.router.users.models import User

router = APIRouter()

# 도구 이름 → 상태 메시지 매핑
TOOL_STATUS_MESSAGES = {
    "get_user_orders": "주문 내역을 조회하고 있습니다...",
    "get_order_detail": "주문 상세 정보를 확인하고 있습니다...",
    "get_shipping_details": "배송 상태를 조회하고 있습니다...",
    "save_shipping_address_from_ui": "입력하신 주소를 저장하고 있습니다...",
    "register_return_request": "반품 신청을 처리하고 있습니다...",
    "register_exchange_request": "교환 신청을 처리하고 있습니다...",
    "cancel_order": "주문 취소를 처리하고 있습니다...",
    "request_human_handoff": "상담원 연결을 시도하고 있습니다...",
}

# 그래프 노드 이름 → 상태 메시지 매핑
NODE_STATUS_MESSAGES = {
    "preprocess": "요청을 분석하고 있습니다...",
    "validation": "실행 전 안전성/유효성을 검토하고 있습니다...",
    "approval": "승인 필요 여부를 확인하고 있습니다...",
    "tools": "필요한 도구를 호출하고 있습니다...",
    "agent": "답변을 구성하고 있습니다...",
    "process_output": "최종 응답을 정리하고 있습니다...",
}


# 메시지 직렬화/역직렬화 (컴프리헨션)
def serialize_messages(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    role_map = {HumanMessage: "user", AIMessage: "assistant"}
    return [
        {"role": role_map.get(type(m), "system"), "content": m.content}
        for m in messages
    ]


def deserialize_messages(serialized: List[Dict[str, Any]]) -> List[BaseMessage]:
    msg_map = {"user": HumanMessage, "assistant": AIMessage}
    return [
        msg_map[m["role"]](content=m.get("content", ""))
        for m in serialized
        if m["role"] in msg_map
    ]


def _parse_tool_output(output) -> dict | None:
    """도구 출력을 딕셔너리로 변환"""
    if isinstance(output, dict):
        return output
    if isinstance(output, BaseMessage) and hasattr(output, "content"):
        try:
            if isinstance(output.content, str):
                return json.loads(output.content)
        except Exception:
            pass
    return None


def _build_metadata(final_state: dict | None) -> dict:
    """최종 상태에서 메타데이터 추출"""
    state_data = final_state if isinstance(final_state, dict) else {}
    raw_current_task = state_data.get("current_task")
    current_task = raw_current_task if isinstance(raw_current_task, dict) else None
    fallback_task = state_data.get("last_completed_task")
    task_context = current_task or (
        fallback_task if isinstance(fallback_task, dict) else None
    )
    status = (
        task_context.get("status", "idle") if isinstance(task_context, dict) else "idle"
    )

    action_name = (
        f"{task_context.get('type')}_requested"
        if isinstance(task_context, dict) and status == "completed"
        else None
    )
    order_id = task_context.get("target_id") if isinstance(task_context, dict) else None
    return {
        "type": "metadata",
        "action_status": status,
        "action_name": action_name,
        "order_id": order_id,
        "state": {
            **state_data,
            "messages": serialize_messages(state_data.get("messages", [])),
        },
    }


def _extract_ui_actions(final_state: dict) -> List[dict]:
    """최종 상태에서 UI 액션 목록을 안전하게 추출"""
    if not isinstance(final_state, dict):
        return []

    outputs = final_state.get("tool_outputs")
    if not isinstance(outputs, list):
        return []

    ui_actions: List[dict] = []
    for output in outputs:
        parsed = _parse_tool_output(output)
        if isinstance(parsed, dict) and parsed.get("ui_action"):
            ui_actions.append(parsed)

    return ui_actions


@router.post("/stream")
async def chat_streaming_endpoint(
    request: ChatRequest, current_user: User = Depends(get_current_user)
):
    """스트리밍 방식으로 챗봇 응답 반환 (astream_events 사용)"""

    async def event_generator():
        run_logger = None
        try:
            previous_state = request.previous_state or {}
            requested_provider = (
                (request.provider or previous_state.get("llm_provider") or "openai")
                .strip()
                .lower()
            )
            requested_model = (
                request.model or previous_state.get("llm_model") or ""
            ).strip()
            conversation_id = (
                previous_state.get("conversation_id") or f"conv_{uuid4().hex[:12]}"
            )
            turn_id = f"turn_{uuid4().hex[:12]}"

            # 1. 상태 초기화
            current_state = {
                **previous_state,
                "retry_count": 0,
                "current_task": previous_state.get("current_task"),
                "documents": [],
                "tool_outputs": [],
                "task_list": [],
                "task_results": [],
                "is_authenticated": True,
                "user_info": {
                    "id": current_user.id,
                    "name": current_user.name,
                    "email": current_user.email,
                },
                "llm_provider": requested_provider,
                "llm_model": requested_model or None,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
            }

            # 메시지 복구 및 추가
            serialized_history = (
                previous_state.get("messages", []) if previous_state else []
            )
            history = deserialize_messages(serialized_history) if previous_state else []

            current_state["messages"] = history + [
                HumanMessage(content=request.message)
            ]

            run_logger = ConversationRunLogger(
                conversation_id=conversation_id,
                turn_id=turn_id,
                user_id=current_user.id,
                provider=requested_provider,
                model=requested_model or None,
            )
            run_logger.set_input(request.message, current_state)

            # 2. 이벤트 스트리밍
            final_state = None
            has_streamed_text = False
            streamed_ui_actions: set[str] = set()
            last_langgraph_input = None
            async for event in graph_app.astream_events(current_state, version="v2"):
                event_type = event["event"]

                # A. 토큰 스트리밍
                if event_type == "on_chat_model_stream":
                    # 내부 LLM(승인용, 가드레일, Decomposer 등)에서 발생한 스트림은 사용자에게 전달하지 않음
                    tags = event.get("tags", [])
                    name = event.get("name", "")
                    internal_llms = {
                        "approval_llm",
                        "guardrail_llm",
                        "summary_llm",
                    }

                    if "approval_llm" in tags or name in internal_llms:
                        continue

                    chunk = event.get("data", {}).get("chunk")
                    content = chunk.content if chunk else None
                    if content:
                        has_streamed_text = True
                        yield f"data: {json.dumps({'type': 'text_chunk', 'content': content}, ensure_ascii=False)}\n\n"

                # B. 도구 실행 시작 (상태 메시지)
                elif event_type == "on_tool_start":
                    tool_start_data = event.get("data", {})
                    run_logger.log_tool_start(
                        event.get("name", "unknown_tool"),
                        tool_start_data.get("input")
                        if tool_start_data.get("input") is not None
                        else tool_start_data,
                    )
                    status_msg = TOOL_STATUS_MESSAGES.get(event["name"])
                    if status_msg:
                        yield f"data: {json.dumps({'type': 'status_update', 'status': status_msg}, ensure_ascii=False)}\n\n"

                # B-1. 그래프 노드 실행 시작 (실제 진행 단계 표시)
                elif event_type == "on_chain_start":
                    node_name = event.get("name")
                    if node_name == "LangGraph":
                        last_langgraph_input = event.get("data", {}).get("input")
                    else:
                        node_start_data = event.get("data", {})
                        run_logger.log_node_start(
                            node_name or "unknown_node",
                            node_start_data.get("input")
                            if node_start_data.get("input") is not None
                            else node_start_data,
                        )
                    status_msg = NODE_STATUS_MESSAGES.get(node_name)
                    if status_msg:
                        yield f"data: {json.dumps({'type': 'status_update', 'status': status_msg, 'node': node_name}, ensure_ascii=False)}\n\n"

                # B-2. 모델 호출 시작 (모델 실행 단계 표시)
                elif event_type == "on_chat_model_start":
                    model_name = event.get("name") or "chat_model"
                    model_start_data = event.get("data", {})
                    run_logger.log_model_start(
                        model_name,
                        model_start_data.get("input")
                        if model_start_data.get("input") is not None
                        else model_start_data,
                    )
                    status_msg = f"모델이 응답을 생성하고 있습니다... ({model_name})"
                    yield f"data: {json.dumps({'type': 'status_update', 'status': status_msg, 'model': model_name}, ensure_ascii=False)}\n\n"

                elif event_type == "on_chat_model_end":
                    model_end_data = event.get("data", {})
                    run_logger.log_model_end(
                        event.get("name") or "chat_model",
                        model_end_data.get("output")
                        if model_end_data.get("output") is not None
                        else model_end_data,
                    )

                # C. 도구 실행 완료 (UI 액션)
                elif event_type == "on_tool_end":
                    tool_end_data = event.get("data", {})
                    run_logger.log_tool_end(
                        event.get("name", "unknown_tool"),
                        tool_end_data.get("output")
                        if tool_end_data.get("output") is not None
                        else tool_end_data,
                    )
                    tool_output = _parse_tool_output(event["data"].get("output"))

                    if tool_output and tool_output.get("ui_action"):
                        ui_action_name = str(tool_output.get("ui_action"))
                        streamed_ui_actions.add(ui_action_name)
                        ui_data = {
                            "type": "ui_action",
                            "ui_action": ui_action_name,
                            "ui_data": tool_output.get("ui_data"),
                            "requires_selection": tool_output.get(
                                "requires_selection", False
                            ),
                            "message": tool_output.get("message", ""),
                        }
                        yield f"data: {json.dumps(ui_data, ensure_ascii=False)}\n\n"

                # D. 최종 상태 캡처
                elif event_type == "on_chain_end" and event["name"] == "LangGraph":
                    final_state = event["data"].get("output")
                    if isinstance(last_langgraph_input, dict) and isinstance(
                        final_state, dict
                    ):
                        run_logger.log_state_change(last_langgraph_input, final_state)
                elif event_type == "on_chain_end":
                    node_end_data = event.get("data", {})
                    run_logger.log_node_end(
                        event.get("name") or "unknown_node",
                        node_end_data.get("output")
                        if node_end_data.get("output") is not None
                        else node_end_data,
                    )

            # 3. 메타데이터 전송
            if final_state:
                final_ui_actions = _extract_ui_actions(final_state)
                has_ui_action = len(final_ui_actions) > 0

                # 일부 경로에서는 on_tool_end 이벤트가 없을 수 있어
                # 최종 상태의 UI 액션을 보강 전송한다.
                for item in final_ui_actions:
                    ui_action_name = str(item.get("ui_action"))
                    if ui_action_name in streamed_ui_actions:
                        continue
                    ui_data = {
                        "type": "ui_action",
                        "ui_action": ui_action_name,
                        "ui_data": item.get("ui_data"),
                        "requires_selection": item.get("requires_selection", False),
                        "message": item.get("message", ""),
                    }
                    yield f"data: {json.dumps(ui_data, ensure_ascii=False)}\n\n"

                final_text = (
                    final_state.get("generation")
                    if isinstance(final_state, dict)
                    else None
                )
                if (
                    (not has_ui_action)
                    and (not has_streamed_text)
                    and isinstance(final_text, str)
                    and final_text.strip()
                ):
                    yield f"data: {json.dumps({'type': 'text_chunk', 'content': final_text}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps(_build_metadata(final_state), ensure_ascii=False)}\n\n"
                log_path = run_logger.finalize(final_state, success=True)
                yield f"data: {json.dumps({'type': 'audit_log', 'conversation_id': conversation_id, 'turn_id': turn_id, 'log_path': log_path}, ensure_ascii=False)}\n\n"
            else:
                log_path = run_logger.finalize(
                    {"messages": current_state.get("messages", [])}, success=True
                )
                yield f"data: {json.dumps({'type': 'audit_log', 'conversation_id': conversation_id, 'turn_id': turn_id, 'log_path': log_path}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            import traceback

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


@router.post("/review-draft")
async def generate_review_draft_endpoint(
    request: ReviewDraftRequest, current_user: User = Depends(get_current_user)
):
    """
    Generate review drafts based on satisfaction and product name.
    """
    try:
        # generate_review_draft is a langchain component (StructuredTool)
        result = generate_review_draft.invoke(
            {
                "product_name": request.product_name,
                "satisfaction": request.satisfaction,
                "keywords": request.keywords or [],
            }
        )
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                pass

        # If result is already a dict from the tool, it contains 'success' and 'drafts'
        if isinstance(result, dict) and "drafts" in result:
            return result

        return {"success": True, "drafts": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
