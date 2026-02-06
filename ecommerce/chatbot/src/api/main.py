from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import sys

# 프로젝트 루트 경로 추가 (상대 경로 임포트 문제 해결)
sys.path.append(os.getcwd())

from ecommerce.chatbot.src.graph.workflow import graph_app
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

app = FastAPI(title="🛍️ 무신사 CS 에이전트 API")

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

class ChatRequest(BaseModel):
    message: str
    user_id: str = "guest"
    # 이전 대화 상태 (메시지 이력 포함)
    previous_state: Optional[Dict[str, Any]] = None

@app.get("/")
async def root():
    return {"message": "Musinsa CS Agent API is running!", "version": "1.0.0"}

@app.post("/chat")
async def chat(request: ChatRequest):
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
        
        current_state = request.previous_state or {
            "retry_count": 0,
            "user_info": {"id": request.user_id, "name": "사용자"},
            "action_status": "idle",
            "order_id": None,
            "action_name": None,
            "documents": [],
            "tool_outputs": []
        }
        current_state["messages"] = history
        
        # 2. 새로운 사용자 메시지 추가
        current_state["messages"].append(HumanMessage(content=request.message))
        
        # 3. 에이전트 실행 (LangGraph)
        # 턴 사이의 상태가 current_state를 통해 전달됨
        result = graph_app.invoke(current_state)
        
        # 4. 결과 직렬화 (JSON 변환 불가능한 객체들을 텍스트/리스트로 변환)
        processed_result = result.copy()
        
        # 메시지 객체 리스트를 JSON 직렬화 가능한 딕셔너리 리스트로 변환
        processed_result["messages"] = serialize_messages(result.get("messages", []))
        
        # 5. 최종 응답 구성
        return {
            "answer": result.get("generation"),
            "action_status": result.get("action_status"),  # 'pending_approval' 등 상태 확인용
            "action_name": result.get("action_name"),
            "order_id": result.get("order_id"),
            "state": processed_result  # 프론트엔드가 다음 전송을 위해 저장해야 함
        }
        
    except Exception as e:
        # 상세 에러 로그 출력 (서버 터미널용)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"상담 처리 중 오류가 발생했습니다: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # 로컬 테스트용: python ecommerce/chatbot/src/api/main.py 실행 시 활성화
    uvicorn.run(app, host="0.0.0.0", port=8000)
