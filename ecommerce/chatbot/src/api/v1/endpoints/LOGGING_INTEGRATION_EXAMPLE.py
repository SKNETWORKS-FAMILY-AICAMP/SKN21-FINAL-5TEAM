"""
챗봇 API에 로깅 적용 예시
"""
import time
from fastapi import Request

from ecommerce.platform.backend.app.router.chatbot_logs.middleware import log_chat_interaction
from ecommerce.platform.backend.app.router.chatbot_logs.models import ConversationStatus


# ============================================
# 예시 1: 기존 Chat API 수정
# ============================================

"""
# chat.py에 추가할 코드:

@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    http_request: Request = None  # FastAPI Request 객체 추가
):
    start_time = time.time()
    
    try:
        # 세션 ID 추출 또는 생성
        session_id = request.previous_state.get("session_id") if request.previous_state else None
        if not session_id:
            import uuid
            session_id = f"session_{uuid.uuid4().hex[:16]}"
        
        # ... 기존 처리 로직 ...
        result = graph_app.invoke(state)
        
        # 실행 시간 계산
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        # 클라이언트 정보
        client_info = {
            "user_agent": http_request.headers.get("user-agent") if http_request else None,
            "ip_address": http_request.client.host if http_request else None
        }
        
        # ✅ 로그 저장
        log_chat_interaction(
            session_id=session_id,
            user_id=current_user.id,
            user_message=request.message,
            assistant_response=result.get("messages", [])[-1].content if result.get("messages") else None,
            graph_state=result,
            execution_time_ms=execution_time_ms,
            client_info=client_info
        )
        
        # 응답에 session_id 포함
        response = ChatResponse(...)
        response.state["session_id"] = session_id
        
        return response
        
    except Exception as e:
        # 오류 발생 시에도 로깅
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        log_chat_interaction(
            session_id=session_id,
            user_id=current_user.id if current_user else None,
            user_message=request.message,
            assistant_response=None,
            graph_state={"error": str(e)},
            execution_time_ms=execution_time_ms
        )
        
        raise
"""


# ============================================
# 예시 2: Context Manager 방식
# ============================================

"""
from ecommerce.platform.backend.app.router.chatbot_logs.middleware import chatbot_logger

@router.post("/chat-v2")
async def chat_endpoint_v2(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    session_id = request.previous_state.get("session_id") if request.previous_state else None
    
    with chatbot_logger.session_context(
        session_id=session_id,
        user_id=current_user.id,
        client_info={"source": "web"}
    ) as logger:
        try:
            # 사용자 메시지 로깅
            logger.log_user_message(
                content=request.message,
                intent=None,  # NLU 결과 있으면 추가
                entities=None
            )
            
            # 그래프 실행
            start_time = time.time()
            result = graph_app.invoke(state)
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # 도구 호출 로깅 (그래프 상태에서 추출)
            for tool_call in extract_tool_calls(result):
                logger.log_tool_call(
                    tool_name=tool_call["name"],
                    tool_input=tool_call["args"],
                    tool_output=tool_call.get("output"),
                    execution_status="success" if tool_call.get("output") else "error"
                )
            
            # 어시스턴트 응답 로깅
            assistant_message = result.get("messages", [])[-1].content
            logger.log_assistant_response(
                content=assistant_message,
                response_time_ms=execution_time_ms,
                ui_action=result.get("ui_action"),
                ui_data=result.get("ui_data")
            )
            
            # 세션 종료 (대화가 끝났을 때)
            if is_conversation_ended(result):
                logger.end_session(
                    status=ConversationStatus.COMPLETED,
                    user_satisfaction=None  # 사용자 피드백 있으면 추가
                )
            
            return ChatResponse(...)
            
        except Exception as e:
            logger.log_assistant_response(
                content="",
                error_message=str(e)
            )
            logger.end_session(status=ConversationStatus.ERROR)
            raise
"""


# ============================================
# 예시 3: 노드 레벨 로깅 (nodes_v2.py에 추가)
# ============================================

"""
from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.router.chatbot_logs.service import LogService

def tool_node(state: AgentState) -> dict:
    '''도구 실행 노드'''
    
    # 로깅 서비스 초기화
    db = SessionLocal()
    log_service = LogService(db)
    session_id = state.get("session_id")  # 상태에 session_id 포함 필요
    
    try:
        messages = state["messages"]
        last_message = messages[-1]
        
        # 도구 호출 추출
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_input = tool_call["args"]
            
            start_time = time.time()
            
            try:
                # 도구 실행
                tool_output = execute_tool(tool_name, tool_input)
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # ✅ 성공 로깅
                if session_id:
                    log_service.log_tool_call(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_output=tool_output,
                        execution_status="success",
                        execution_time_ms=execution_time_ms
                    )
                
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # ✅ 오류 로깅
                if session_id:
                    log_service.log_tool_call(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_input=tool_input,
                        execution_status="error",
                        execution_time_ms=execution_time_ms,
                        error_type=type(e).__name__,
                        error_message=str(e)
                    )
                
                raise
        
        db.commit()
        return state
        
    finally:
        db.close()
"""


# ============================================
# 예시 4: 사용자 피드백 수집 API
# ============================================

"""
from pydantic import BaseModel

class FeedbackRequest(BaseModel):
    session_id: str
    satisfaction: int  # 1-5
    comment: Optional[str] = None

@router.post("/feedback")
async def submit_feedback(
    feedback: FeedbackRequest,
    current_user: User = Depends(get_current_user)
):
    '''사용자 피드백 수집'''
    db = SessionLocal()
    try:
        log_service = LogService(db)
        
        # 세션 종료 및 만족도 기록
        log_service.end_session(
            session_id=feedback.session_id,
            status=ConversationStatus.COMPLETED,
            user_satisfaction=feedback.satisfaction
        )
        
        return {"status": "success", "message": "피드백이 저장되었습니다"}
        
    finally:
        db.close()
"""
