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

@router.post("/", response_model=ChatResponse)
@traceable(run_type="chain", name="Chat Endpoint")
async def chat_endpoint(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    """
    사용자의 메시지를 받아 에이전트의 응답을 반환합니다.
    JSON 기반의 상태 정보를 주고받아 Stateless 환경에서도 대화 맥락을 유지합니다.
    """
    try:
        # 1. 상태(State) 복구
        history = []
        if request.previous_state and "messages" in request.previous_state:
            # 클라이언트가 보낸 텍스트 메시지를 LangChain 메시지 객체로 복구
            history = deserialize_messages(request.previous_state["messages"])
        
        # Initialize state
        current_state = request.previous_state or {
            "retry_count": 0,
            "action_status": "idle",
            "order_id": None,
            "action_name": None,
            "documents": [],
            "tool_outputs": []
        }
        
        # Set user context from JWT authentication (authentication required)
        current_state["user_id"] = current_user.id
        current_state["is_authenticated"] = True
        current_state["user_info"] = {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email
        }
        
        current_state["messages"] = history
        
        # 2. 새로운 사용자 메시지 추가
        current_state["messages"].append(HumanMessage(content=request.message))
        
        # 3. 에이전트 실행 (LangGraph)
        # 턴 사이의 상태가 current_state를 통해 전달됨
        result = await graph_app.ainvoke(current_state)
        
        # 4. 결과 직렬화 (JSON 변환 불가능한 객체들을 텍스트/리스트로 변환)
        processed_result = result.copy()
        
        # 메시지 객체 리스트를 JSON 직렬화 가능한 딕셔너리 리스트로 변환
        processed_result["messages"] = serialize_messages(result.get("messages", []))
        
        # 5. Extract UI data from tool_outputs
        ui_action = None
        ui_data = None
        tool_outputs = result.get("tool_outputs", [])
        
        # Check if any tool returned UI rendering data
        for tool_output in tool_outputs:
            if isinstance(tool_output, dict):
                if tool_output.get("ui_action") == "show_order_list":
                    ui_action = "show_order_list"
                    ui_data = tool_output.get("ui_data", [])
                    break
        
        # 6. 최종 응답 구성
        return ChatResponse(
            answer=result.get("generation"),
            action_status=result.get("action_status"),
            action_name=result.get("action_name"),
            order_id=result.get("order_id"),
            ui_action=ui_action,
            ui_data=ui_data,
            state=processed_result  # 프론트엔드가 다음 전송을 위해 저장해야 함
        )

    except Exception as e:
        # 상세 에러 로그 출력 (서버 터미널용)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"상담 처리 중 오류가 발생했습니다: {str(e)}")


@router.post("/stream")
@traceable(run_type="chain", name="Chat Streaming Endpoint")
async def chat_streaming_endpoint(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    """
    스트리밍 방식으로 챗봇 응답을 반환합니다.
    답변이 생성되는 동안 글자 단위로 전송하여 타이핑 효과를 제공합니다.
    """
    async def event_generator():
        try:
            # 1. 상태 복구
            history = []
            if request.previous_state and "messages" in request.previous_state:
                history = deserialize_messages(request.previous_state["messages"])
            
            # Initialize state
            current_state = request.previous_state or {
                "retry_count": 0,
                "action_status": "idle",
                "order_id": None,
                "action_name": None,
                "documents": [],
                "tool_outputs": []
            }
            
            # Set user context from JWT authentication (authentication required)
            current_state["user_id"] = current_user.id
            current_state["is_authenticated"] = True
            current_state["user_info"] = {
                "id": current_user.id,
                "name": current_user.name,
                "email": current_user.email
            }
            
            current_state["messages"] = history
            current_state["messages"].append(HumanMessage(content=request.message))
            
            # 2. 에이전트 실행
            result = await graph_app.ainvoke(current_state)
            
            # 3. 결과 직렬화
            processed_result = result.copy()
            processed_result["messages"] = serialize_messages(result.get("messages", []))
            
            # 4. UI 데이터 추출
            ui_action = None
            ui_data = None
            tool_outputs = result.get("tool_outputs", [])
            
            for tool_output in tool_outputs:
                if isinstance(tool_output, dict):
                    if tool_output.get("ui_action") == "show_order_list":
                        ui_action = "show_order_list"
                        ui_data = tool_output.get("ui_data", [])
                        break
            
            # 5. UI 액션이 있는 경우 즉시 전송
            if ui_action and ui_data:
                response_data = {
                    "type": "ui_action",
                    "ui_action": ui_action,
                    "ui_data": ui_data,
                    "state": processed_result
                }
                yield f"data: {json.dumps(response_data, ensure_ascii=False)}\n\n"
            else:
                # 6. 일반 텍스트 응답을 글자 단위로 스트리밍
                answer = result.get("generation", "")
                
                # 먼저 메타데이터 전송
                meta_data = {
                    "type": "metadata",
                    "action_status": result.get("action_status"),
                    "action_name": result.get("action_name"),
                    "order_id": result.get("order_id"),
                    "state": processed_result
                }
                yield f"data: {json.dumps(meta_data, ensure_ascii=False)}\n\n"
                
                # 답변을 글자 단위로 스트리밍
                for char in answer:
                    chunk_data = {
                        "type": "text_chunk",
                        "content": char
                    }
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.02)  # 타이핑 효과를 위한 딜레이
                
                # 완료 신호
                done_data = {"type": "done"}
                yield f"data: {json.dumps(done_data)}\n\n"
                
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

