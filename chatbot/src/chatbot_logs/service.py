"""
Chatbot Log Service
로그 수집 및 품질 평가 서비스
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from chatbot.src.chatbot_logs.models import (
    ConversationSession,
    ConversationMessage,
    ToolCallLog,
    DatasetSample,
    ConversationStatus,
    MessageRole,
    QualityLabel,
    DatasetType
)


class LogService:
    """로그 수집 및 관리 서비스"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ============================================
    # 로그 수집 (Create)
    # ============================================
    
    def create_session(
        self,
        session_id: str,
        user_id: Optional[int] = None,
        client_info: Optional[Dict] = None
    ) -> ConversationSession:
        """새 대화 세션 생성"""
        session = ConversationSession(
            session_id=session_id,
            user_id=user_id,
            client_info=client_info,
            status=ConversationStatus.ACTIVE
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session
    
    def log_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        intent: Optional[str] = None,
        entities: Optional[Dict] = None,
        response_time_ms: Optional[int] = None,
        ui_action: Optional[str] = None,
        ui_data: Optional[Dict] = None,
        error_message: Optional[str] = None
    ) -> ConversationMessage:
        """메시지 로깅"""
        session = self.db.query(ConversationSession).filter(
            ConversationSession.session_id == session_id
        ).first()
        
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        # 턴 번호 계산
        turn_number = session.turn_count + 1
        
        message = ConversationMessage(
            session_id=session.id,
            role=role,
            content=content,
            turn_number=turn_number,
            intent=intent,
            entities=entities,
            response_time_ms=response_time_ms,
            ui_action=ui_action,
            ui_data=ui_data,
            has_error=error_message is not None,
            error_message=error_message
        )
        
        # 세션 통계 업데이트
        session.turn_count += 1
        if role == MessageRole.USER:
            session.user_message_count += 1
        elif role == MessageRole.ASSISTANT:
            session.assistant_message_count += 1
        
        if error_message:
            session.error_count += 1
        
        # 멀티턴 플래그
        if session.turn_count >= 3:
            session.has_multi_turn = True
        
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        
        return message
    
    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        tool_input: Dict,
        tool_output: Optional[Dict] = None,
        execution_status: str = "pending",
        execution_time_ms: Optional[int] = None,
        validation_result: Optional[Dict] = None,
        approval_required: bool = False,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        message_id: Optional[int] = None
    ) -> ToolCallLog:
        """도구 호출 로깅"""
        session = self.db.query(ConversationSession).filter(
            ConversationSession.session_id == session_id
        ).first()
        
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        tool_log = ToolCallLog(
            session_id=session.id,
            message_id=message_id,
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
        
        # 세션 통계 업데이트
        session.tool_call_count += 1
        if execution_status == "success":
            session.has_successful_tool_call = True
        
        self.db.add(tool_log)
        self.db.commit()
        self.db.refresh(tool_log)
        
        return tool_log
    
    def end_session(
        self,
        session_id: str,
        status: ConversationStatus = ConversationStatus.COMPLETED,
        user_satisfaction: Optional[int] = None
    ):
        """세션 종료 및 품질 평가"""
        session = self.db.query(ConversationSession).filter(
            ConversationSession.session_id == session_id
        ).first()
        
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        session.status = status
        session.ended_at = datetime.utcnow()
        
        if user_satisfaction is not None:
            session.user_satisfaction = user_satisfaction
            session.has_user_feedback = True
        
        # 자동 품질 평가
        quality_score = self._calculate_quality_score(session)
        session.quality_score = quality_score
        session.quality_label = self._assign_quality_label(quality_score, session)
        
        self.db.commit()
    
    # ============================================
    # 품질 평가 로직
    # ============================================
    
    def _calculate_quality_score(self, session: ConversationSession) -> float:
        """
        대화 품질 점수 자동 계산 (0.0 ~ 1.0)
        
        평가 기준:
        - 성공적인 도구 호출 (30%)
        - 오류 없음 (20%)
        - 멀티턴 대화 (15%)
        - 사용자 만족도 (20%)
        - 응답 시간 (15%)
        """
        score = 0.0
        
        # 1. 성공적인 도구 호출 (30점)
        if session.has_successful_tool_call and session.tool_call_count > 0:
            # 성공률 계산
            tool_calls = self.db.query(ToolCallLog).filter(
                ToolCallLog.session_id == session.id
            ).all()
            
            success_count = sum(1 for tc in tool_calls if tc.execution_status == "success")
            success_rate = success_count / len(tool_calls) if tool_calls else 0
            score += 0.30 * success_rate
        
        # 2. 오류 없음 (20점)
        if session.error_count == 0:
            score += 0.20
        elif session.turn_count > 0:
            error_rate = session.error_count / session.turn_count
            score += 0.20 * (1 - error_rate)
        
        # 3. 멀티턴 대화 (15점) - 복잡한 시나리오 선호
        if session.has_multi_turn:
            # 3-5턴: 적정, 6턴 이상: 우수
            if session.turn_count >= 6:
                score += 0.15
            elif session.turn_count >= 3:
                score += 0.10
        
        # 4. 사용자 만족도 (20점)
        if session.has_user_feedback and session.user_satisfaction:
            # 1-5점 스케일을 0-1로 정규화
            satisfaction_score = (session.user_satisfaction - 1) / 4
            score += 0.20 * satisfaction_score
        
        # 5. 응답 시간 (15점)
        messages = self.db.query(ConversationMessage).filter(
            and_(
                ConversationMessage.session_id == session.id,
                ConversationMessage.role == MessageRole.ASSISTANT,
                ConversationMessage.response_time_ms.isnot(None)
            )
        ).all()
        
        if messages:
            avg_response_time = sum(m.response_time_ms for m in messages) / len(messages)
            # 3초 이하: 만점, 10초 이상: 0점
            if avg_response_time <= 3000:
                score += 0.15
            elif avg_response_time <= 10000:
                score += 0.15 * (1 - (avg_response_time - 3000) / 7000)
        
        return min(1.0, max(0.0, score))
    
    def _assign_quality_label(
        self, 
        quality_score: float, 
        session: ConversationSession
    ) -> QualityLabel:
        """
        품질 점수 기반 레이블 할당
        
        기준:
        - EXCELLENT (0.8+): 학습 데이터 우선
        - GOOD (0.6-0.8): 평가 데이터 후보
        - FAIR (0.4-0.6): 리뷰 필요
        - POOR (<0.4): 제외
        """
        # 명시적 제외 조건
        if session.status == ConversationStatus.ERROR:
            return QualityLabel.POOR
        
        if session.status == ConversationStatus.ABANDONED and session.turn_count < 2:
            return QualityLabel.POOR
        
        # 점수 기반 분류
        if quality_score >= 0.8:
            return QualityLabel.EXCELLENT
        elif quality_score >= 0.6:
            return QualityLabel.GOOD
        elif quality_score >= 0.4:
            return QualityLabel.FAIR
        else:
            return QualityLabel.POOR
    
    # ============================================
    # 필터링 및 조회
    # ============================================
    
    def get_high_quality_sessions(
        self,
        min_quality_score: float = 0.6,
        quality_labels: List[QualityLabel] = None,
        limit: int = 100
    ) -> List[ConversationSession]:
        """고품질 세션 조회"""
        query = self.db.query(ConversationSession).filter(
            ConversationSession.quality_score >= min_quality_score
        )
        
        if quality_labels:
            query = query.filter(ConversationSession.quality_label.in_(quality_labels))
        
        return query.order_by(
            ConversationSession.quality_score.desc(),
            ConversationSession.created_at.desc()
        ).limit(limit).all()
    
    def get_sessions_by_intent(
        self,
        intent: str,
        min_quality_score: float = 0.5,
        limit: int = 50
    ) -> List[ConversationSession]:
        """특정 의도의 세션 조회"""
        session_ids = self.db.query(ConversationMessage.session_id).filter(
            ConversationMessage.intent == intent
        ).distinct().subquery()
        
        return self.db.query(ConversationSession).filter(
            and_(
                ConversationSession.id.in_(session_ids),
                ConversationSession.quality_score >= min_quality_score
            )
        ).order_by(
            ConversationSession.quality_score.desc()
        ).limit(limit).all()
    
    def get_sessions_by_tool(
        self,
        tool_name: str,
        execution_status: str = "success",
        min_quality_score: float = 0.5,
        limit: int = 50
    ) -> List[ConversationSession]:
        """특정 도구 사용 세션 조회"""
        session_ids = self.db.query(ToolCallLog.session_id).filter(
            and_(
                ToolCallLog.tool_name == tool_name,
                ToolCallLog.execution_status == execution_status
            )
        ).distinct().subquery()
        
        return self.db.query(ConversationSession).filter(
            and_(
                ConversationSession.id.in_(session_ids),
                ConversationSession.quality_score >= min_quality_score
            )
        ).order_by(
            ConversationSession.quality_score.desc()
        ).limit(limit).all()
    
    def get_edge_cases(self, limit: int = 50) -> List[ConversationSession]:
        """엣지 케이스 조회 (오류 있지만 해결된 케이스)"""
        return self.db.query(ConversationSession).filter(
            and_(
                ConversationSession.error_count > 0,
                ConversationSession.status == ConversationStatus.COMPLETED,
                ConversationSession.quality_score >= 0.5
            )
        ).order_by(
            ConversationSession.quality_score.desc()
        ).limit(limit).all()
    
    def get_multi_turn_conversations(
        self,
        min_turns: int = 4,
        min_quality_score: float = 0.6,
        limit: int = 50
    ) -> List[ConversationSession]:
        """멀티턴 대화 조회"""
        return self.db.query(ConversationSession).filter(
            and_(
                ConversationSession.turn_count >= min_turns,
                ConversationSession.has_multi_turn == True,
                ConversationSession.quality_score >= min_quality_score
            )
        ).order_by(
            ConversationSession.turn_count.desc(),
            ConversationSession.quality_score.desc()
        ).limit(limit).all()
    
    # ============================================
    # 통계 및 분석
    # ============================================
    
    def get_quality_distribution(self) -> Dict[str, int]:
        """품질 레이블 분포"""
        results = self.db.query(
            ConversationSession.quality_label,
            func.count(ConversationSession.id)
        ).group_by(ConversationSession.quality_label).all()
        
        return {label.value: count for label, count in results}
    
    def get_tool_usage_stats(self) -> List[Dict[str, Any]]:
        """도구 사용 통계"""
        results = self.db.query(
            ToolCallLog.tool_name,
            func.count(ToolCallLog.id).label('total_calls'),
            func.sum(
                func.case((ToolCallLog.execution_status == 'success', 1), else_=0)
            ).label('success_calls'),
            func.avg(ToolCallLog.execution_time_ms).label('avg_time_ms')
        ).group_by(ToolCallLog.tool_name).all()
        
        return [
            {
                'tool_name': row.tool_name,
                'total_calls': row.total_calls,
                'success_calls': row.success_calls,
                'success_rate': row.success_calls / row.total_calls if row.total_calls > 0 else 0,
                'avg_time_ms': round(row.avg_time_ms, 2) if row.avg_time_ms else None
            }
            for row in results
        ]
    
    def get_intent_distribution(self) -> Dict[str, int]:
        """의도 분포"""
        results = self.db.query(
            ConversationMessage.intent,
            func.count(ConversationMessage.id)
        ).filter(
            ConversationMessage.intent.isnot(None)
        ).group_by(ConversationMessage.intent).all()
        
        return {intent: count for intent, count in results if intent}
