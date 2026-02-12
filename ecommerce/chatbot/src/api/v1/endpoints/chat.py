from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from langsmith import traceable
from typing import List, Dict, Any
import json
import asyncio
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from ecommerce.chatbot.src.schemas.chat import ChatRequest, ChatResponse
from ecommerce.chatbot.src.graph.workflow import graph_app
from ecommerce.platform.backend.app.core.auth import get_current_user
from ecommerce.platform.backend.app.router.users.models import User

router = APIRouter()

# 1. 메시지 객체를 JSON으로 변환하는 유틸리티
def serialize_messages(messages: List[BaseMessage]):
    serialized = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            serialized.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            serialized.append({"role": "assistant", "content": msg.content})
        else:
            # 기타 메시지 타입 처리 (기본값)
            serialized.append({"role": "system", "content": str(msg.content)})
    return serialized

# 2. JSON 데이터를 다시 메시지 객체로 변환하는 유틸리티
def deserialize_messages(serialized_messages: List[Dict[str, str]]):
    messages = []
    for msg in serialized_messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages

@router.post("/stream")
@traceable(run_type="chain", name="Chat Streaming Endpoint")
async def chat_streaming_endpoint(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    """
    스트리밍 방식으로 챗봇 응답을 반환합니다.
    LangGraph의 `astream_events`를 사용하여 실시간 토큰 스트리밍과 도구 이벤트를 처리합니다.
    """
    async def event_generator():
        try:
            # 1. 상태 복구
            history = []
            if request.previous_state and "messages" in request.previous_state:
                history = deserialize_messages(request.previous_state["messages"])
            
            # Initialize state with defaults
            default_state = {
                "retry_count": 0,
                "current_task": None,
                "documents": [],
                "tool_outputs": []
            }
            
            # Merge previous_state with defaults
            if request.previous_state:
                current_state = {**default_state, **request.previous_state}
            else:
                current_state = default_state
            
            # Set user context
            current_state["is_authenticated"] = True
            current_state["user_info"] = {
                "id": current_user.id,
                "name": current_user.name,
                "email": current_user.email
            }
            
            current_state["messages"] = history
            current_state["messages"].append(HumanMessage(content=request.message))
            
            # 2. astream_events를 사용하여 실시간 이벤트 스트리밍
            # version="v2"는 LangChain 표준 이벤트 형식을 따름
            final_state = None
            
            async for event in graph_app.astream_events(current_state, version="v2"):
                event_type = event["event"]
                
                # A. 토큰 스트리밍 (LLM이 글자를 생성할 때마다 발생)
                if event_type == "on_chat_model_stream":
                    # 메타데이터 전송 (첫 토큰일 때만 보낼 수도 있지만, 상태가 변할 수 있으므로 상황에 맞게 처리)
                    # 여기서는 data.chunk.content가 있을 때만 전송
                    content = event["data"]["chunk"].content
                    if content:
                        chunk_data = {
                            "type": "text_chunk",
                            "content": content
                        }
                        yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                
                # B. 도구 실행 시작 (상태 메시지 전송)
                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    status_message = None
                    
                    # 도구 이름에 따른 사용자 친화적 메시지 매핑
                    if tool_name == "get_user_orders":
                        status_message = "주문 내역을 조회하고 있습니다..."
                    elif tool_name == "get_order_detail":
                        status_message = "주문 상세 정보를 확인하고 있습니다..."
                    elif tool_name == "get_shipping_details":
                        status_message = "배송 상태를 조회하고 있습니다..."
                    elif tool_name == "register_return_request":
                        status_message = "반품 신청을 처리하고 있습니다..."
                    elif tool_name == "register_exchange_request":
                        status_message = "교환 신청을 처리하고 있습니다..."
                    elif tool_name == "cancel_order":
                        status_message = "주문 취소를 처리하고 있습니다..."
                    elif tool_name == "request_human_handoff":
                        status_message = "상담원 연결을 시도하고 있습니다..."
                    
                    if status_message:
                        status_data = {
                            "type": "status_update",
                            "status": status_message
                        }
                        yield f"data: {json.dumps(status_data, ensure_ascii=False)}\n\n"

                # C. 도구 실행 완료 (UI 액션 감지 및 상태 초기화)
                elif event_type == "on_tool_end":
                    print(f"--- TOOL END: {event['name']} ---")
                    
                    # output이 UI Action 딕셔너리인지 확인
                    tool_output = event["data"].get("output")
                    
                    # ToolMessage 객체인 경우 처리
                    if isinstance(tool_output, BaseMessage):
                         print(f"Tool Output is Message: {tool_output}")
                         if hasattr(tool_output, "content"):
                            try:
                                tool_output = json.loads(tool_output.content)
                            except:
                                pass

                    if isinstance(tool_output, dict):
                        print(f"Tool Output Dict keys: {tool_output.keys()}")
                        ui_action = tool_output.get("ui_action")
                        if ui_action:
                            print(f"emit ui_action: {ui_action}")
                            response_data = {
                                "type": "ui_action",
                                "ui_action": ui_action,
                                "ui_data": tool_output.get("ui_data"),
                                "requires_selection": tool_output.get("requires_selection", False),
                                "message": tool_output.get("message", "")
                            }
                            yield f"data: {json.dumps(response_data, ensure_ascii=False)}\n\n"

                # D. 체인 종료 (최종 상태 획득)
                elif event_type == "on_chain_end" and event["name"] == "LangGraph":
                    # 최종 output (State) 캡처
                    final_state = event["data"].get("output")

            
            # 3. 완료 처리 및 최종 상태 전송
            if final_state:
                # 불필요한 객체 제거 및 직렬화
                processed_state = final_state.copy()
                if "messages" in processed_state:
                    processed_state["messages"] = serialize_messages(processed_state["messages"])
                
                # [Refactoring Compatibility] Map TaskContext back to legacy fields for frontend
                current_task = final_state.get("current_task")
                action_status = "idle"
                action_name = None
                order_id = None
                
                if current_task:
                    action_status = current_task.get("status", "idle")
                    action_name = f"{current_task.get('type')}_requested" if current_task.get("status") == "completed" else None
                    order_id = current_task.get("target_id")

                # 메타데이터 및 완료 신호 전송
                # (UI 액션 등은 이미 스트리밍으로 나갔으므로, 여기서는 State 동기화가 주 목적)
                meta_data = {
                    "type": "metadata",
                    "action_status": action_status,     # Now derived from current_task
                    "action_name": action_name,         # Now derived from current_task
                    "order_id": order_id,               # Now derived from current_task
                    "state": processed_state
                }
                yield f"data: {json.dumps(meta_data, ensure_ascii=False)}\n\n"
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_data = {
                "type": "error",
                "message": f"오류가 발생했습니다: {str(e)}"
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

