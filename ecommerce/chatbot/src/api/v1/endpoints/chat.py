from fastapi import APIRouter, HTTPException
from langsmith import traceable
from typing import List, Dict, Any
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from ecommerce.chatbot.src.schemas.chat import ChatRequest, ChatResponse
from ecommerce.chatbot.src.graph.workflow import graph_app
# [Auth Integration] Import existing auth dependency
from ecommerce.platform.backend.app.router.users.router import get_current_user
from fastapi import Depends

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
    current_user = Depends(get_current_user) # [Auth Integration] Verify X-User-Id header
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
        
        # [Auth Integration] Force override user context from trusted token (DB Model)
        current_state = request.previous_state or {
            "retry_count": 0,
            "action_status": "idle",
            "order_id": None,
            "action_name": None,
            "documents": [],
            "tool_outputs": []
        }
        
        # SECURE OVERRIDE: Trust the server-side authentication, NOT the client JSON
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
        
        # 5. 최종 응답 구성
        return ChatResponse(
            answer=result.get("generation"),
            action_status=result.get("action_status"),
            action_name=result.get("action_name"),
            order_id=result.get("order_id"),
            state=processed_result  # 프론트엔드가 다음 전송을 위해 저장해야 함
        )

    except Exception as e:
        # 상세 에러 로그 출력 (서버 터미널용)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"상담 처리 중 오류가 발생했습니다: {str(e)}")
