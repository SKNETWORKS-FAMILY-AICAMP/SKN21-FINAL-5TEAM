"""
Chatbot Logging Middleware
챗봇 API 호출 시 자동으로 로그를 수집하는 미들웨어
"""
import time
import uuid
from typing import Dict, Any, Optional
from contextlib import contextmanager

from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.router.chatbot_logs.service import LogService
from ecommerce.backend.app.router.chatbot_logs.models import (
    MessageRole,
    ConversationStatus
)


class ChatbotLogger:
    """챗봇 로깅 유틸리티"""
    
    def __init__(self):
        self.db = None
        self.log_service = None
        self.current_session_id = None
        self.start_time = None
    
    @contextmanager
    def session_context(self, session_id: str = None, user_id: int = None, client_info: Dict = None):
        """
        대화 세션 컨텍스트 관리
        
        Usage:
            with logger.session_context(session_id="abc-123", user_id=1) as logger:
                logger.log_user_message("안녕하세요")
                # ... 처리 ...
                logger.log_assistant_response("네, 무엇을 도와드릴까요?")
        """
        self.db = SessionLocal()
        self.log_service = LogService(self.db)
        
        try:
            # 세션 ID 생성 또는 기존 세션 사용
            if session_id:
                # 기존 세션 조회
                session = self.log_service.db.query(
                    self.log_service.db.query(ConversationSession).filter(
                        ConversationSession.session_id == session_id
                    ).first()
                )
                if not session:
                    # 세션이 없으면 새로 생성
                    session = self.log_service.create_session(session_id, user_id, client_info)
            else:
                # 새 세션 생성
                session_id = f"session_{uuid.uuid4().hex[:16]}"
                session = self.log_service.create_session(session_id, user_id, client_info)
            
            self.current_session_id = session_id
            
            yield self
            
        finally:
            if self.db:
                self.db.close()
                self.db = None
                self.log_service = None
                self.current_session_id = None
    
    def log_user_message(
        self,
        content: str,
        intent: Optional[str] = None,
        entities: Optional[Dict] = None
    ):
        """사용자 메시지 로깅"""
        if not self.log_service or not self.current_session_id:
            return
        
        self.log_service.log_message(
            session_id=self.current_session_id,
            role=MessageRole.USER,
            content=content,
            intent=intent,
            entities=entities
        )
    
    def log_assistant_response(
        self,
        content: str,
        response_time_ms: Optional[int] = None,
        ui_action: Optional[str] = None,
        ui_data: Optional[Dict] = None,
        error_message: Optional[str] = None
    ):
        """어시스턴트 응답 로깅"""
        if not self.log_service or not self.current_session_id:
            return
        
        self.log_service.log_message(
            session_id=self.current_session_id,
            role=MessageRole.ASSISTANT,
            content=content or "",
            response_time_ms=response_time_ms,
            ui_action=ui_action,
            ui_data=ui_data,
            error_message=error_message
        )
    
    def log_tool_call(
        self,
        tool_name: str,
        tool_input: Dict,
        tool_output: Optional[Dict] = None,
        execution_status: str = "pending",
        execution_time_ms: Optional[int] = None,
        validation_result: Optional[Dict] = None,
        approval_required: bool = False,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """도구 호출 로깅"""
        if not self.log_service or not self.current_session_id:
            return
        
        self.log_service.log_tool_call(
            session_id=self.current_session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            execution_status=execution_status,
            execution_time_ms=execution_time_ms,
            validation_result=validation_result,
            approval_required=approval_required,
            error_type=error_type,
            error_message=error_message
        )
    
    def end_session(
        self,
        status: ConversationStatus = ConversationStatus.COMPLETED,
        user_satisfaction: Optional[int] = None
    ):
        """세션 종료"""
        if not self.log_service or not self.current_session_id:
            return
        
        self.log_service.end_session(
            session_id=self.current_session_id,
            status=status,
            user_satisfaction=user_satisfaction
        )


# 싱글톤 인스턴스
chatbot_logger = ChatbotLogger()


def log_chat_interaction(
    session_id: str,
    user_id: Optional[int],
    user_message: str,
    assistant_response: Optional[str],
    graph_state: Dict[str, Any],
    execution_time_ms: int,
    client_info: Optional[Dict] = None
):
    """
    단일 턴 대화 로깅 (간편 함수)
    
    Args:
        session_id: 세션 ID
        user_id: 사용자 ID
        user_message: 사용자 메시지
        assistant_response: 어시스턴트 응답
        graph_state: LangGraph 상태 (의도, 엔티티, 도구 호출 등 포함)
        execution_time_ms: 실행 시간
        client_info: 클라이언트 정보
    """
    db = SessionLocal()
    try:
        log_service = LogService(db)
        
        # 세션 생성 또는 조회
        session = db.query(ConversationSession).filter(
            ConversationSession.session_id == session_id
        ).first()
        
        if not session:
            session = log_service.create_session(session_id, user_id, client_info)
        
        # 사용자 메시지 로깅
        intent = graph_state.get("nlu_result", {}).get("intent")
        entities = graph_state.get("nlu_result", {}).get("entities")
        
        log_service.log_message(
            session_id=session_id,
            role=MessageRole.USER,
            content=user_message,
            intent=intent,
            entities=entities
        )
        
        # 도구 호출 로깅
        tool_calls = graph_state.get("messages", [])
        for msg in tool_calls:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    log_service.log_tool_call(
                        session_id=session_id,
                        tool_name=tool_call.get("name"),
                        tool_input=tool_call.get("args", {}),
                        tool_output=None,  # 나중에 업데이트
                        execution_status="pending"
                    )
        
        # 어시스턴트 응답 로깅
        ui_action = graph_state.get("ui_action")
        ui_data = graph_state.get("ui_data")
        error = graph_state.get("error")
        
        log_service.log_message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=assistant_response or "",
            response_time_ms=execution_time_ms,
            ui_action=ui_action,
            ui_data=ui_data,
            error_message=str(error) if error else None
        )
        
        db.commit()
        
    except Exception as e:
        print(f"⚠️  Failed to log chat interaction: {e}")
        db.rollback()
    finally:
        db.close()
