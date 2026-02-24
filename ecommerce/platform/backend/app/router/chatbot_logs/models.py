"""
SQLAlchemy Models - Chatbot Logs
챗봇 대화 로그 및 품질 평가 모델
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, String, Boolean, DateTime, Enum, ForeignKey, 
    Text, JSON, Float, Integer, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.users.models import User


# ==================================================
# Enums
# ==================================================

class ConversationStatus(str, PyEnum):
    """대화 세션 상태"""
    ACTIVE = "active"           # 진행 중
    COMPLETED = "completed"     # 정상 완료
    ABANDONED = "abandoned"     # 중도 이탈
    ERROR = "error"             # 오류 발생


class MessageRole(str, PyEnum):
    """메시지 역할"""
    USER = "user"               # 사용자 메시지
    ASSISTANT = "assistant"     # 챗봇 응답
    SYSTEM = "system"           # 시스템 메시지


class QualityLabel(str, PyEnum):
    """품질 레이블"""
    EXCELLENT = "excellent"     # 매우 우수 (학습 데이터 우선)
    GOOD = "good"              # 좋음 (평가 데이터 후보)
    FAIR = "fair"              # 보통 (리뷰 필요)
    POOR = "poor"              # 나쁨 (제외)
    UNLABELED = "unlabeled"    # 미평가


class DatasetType(str, PyEnum):
    """데이터셋 유형"""
    TRAINING = "training"       # 학습 데이터
    EVALUATION = "evaluation"   # 평가 데이터
    VALIDATION = "validation"   # 검증 데이터
    EXCLUDED = "excluded"       # 제외


# ==================================================
# Main Models
# ==================================================

class ConversationSession(Base):
    """대화 세션 (하나의 대화 전체)"""
    __tablename__ = "chatbot_conversation_sessions"

    # Primary Key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Session Info
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True, index=True)
    
    # Metadata
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus),
        default=ConversationStatus.ACTIVE,
        nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Conversation Stats
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 총 대화 턴 수
    user_message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assistant_message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Quality Metrics (자동 계산)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0.0 ~ 1.0
    quality_label: Mapped[QualityLabel] = mapped_column(
        Enum(QualityLabel),
        default=QualityLabel.UNLABELED,
        nullable=False,
        index=True
    )
    
    # Dataset Assignment
    dataset_type: Mapped[Optional[DatasetType]] = mapped_column(
        Enum(DatasetType),
        nullable=True,
        index=True
    )
    
    # Quality Signals
    has_successful_tool_call: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_multi_turn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # 3턴 이상
    has_user_feedback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_satisfaction: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5 점수
    
    # Technical Info
    client_info: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # User agent, IP 등
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 분류 태그
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        nullable=False, 
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Relationships
    messages: Mapped[List["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="session",
        cascade="all, delete-orphan"
    )
    tool_calls: Mapped[List["ToolCallLog"]] = relationship(
        "ToolCallLog",
        back_populates="session",
        cascade="all, delete-orphan"
    )
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    
    # Indexes
    __table_args__ = (
        Index('idx_session_quality', 'quality_label', 'quality_score'),
        Index('idx_session_dataset', 'dataset_type', 'quality_label'),
        Index('idx_session_user_created', 'user_id', 'created_at'),
    )


class ConversationMessage(Base):
    """개별 메시지 (턴)"""
    __tablename__ = "chatbot_conversation_messages"

    # Primary Key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Foreign Keys
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chatbot_conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Message Info
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 대화 순서
    
    # Metadata
    intent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)  # 의도 분류
    entities: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 추출된 엔티티
    
    # Response Metadata (Assistant 메시지만)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # UI Actions
    ui_action: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ui_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Quality Flags
    has_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    
    # Relationships
    session: Mapped["ConversationSession"] = relationship(
        "ConversationSession",
        back_populates="messages"
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_message_session_turn', 'session_id', 'turn_number'),
        Index('idx_message_intent', 'intent'),
    )


class ToolCallLog(Base):
    """도구 호출 로그"""
    __tablename__ = "chatbot_tool_call_logs"

    # Primary Key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Foreign Keys
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chatbot_conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    message_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("chatbot_conversation_messages.id", ondelete="CASCADE"),
        nullable=True
    )
    
    # Tool Info
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tool_input: Mapped[dict] = mapped_column(JSON, nullable=False)
    tool_output: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Execution Info
    execution_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending"
    )  # pending, success, error, validation_failed, approval_required
    execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Validation & Approval
    validation_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Error Info
    error_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    
    # Relationships
    session: Mapped["ConversationSession"] = relationship(
        "ConversationSession",
        back_populates="tool_calls"
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_tool_name_status', 'tool_name', 'execution_status'),
        Index('idx_tool_session', 'session_id', 'created_at'),
    )


class DatasetSample(Base):
    """추출된 데이터셋 샘플 (학습/평가용)"""
    __tablename__ = "chatbot_dataset_samples"

    # Primary Key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Source
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chatbot_conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Sample Type
    sample_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True
    )  # single_turn, multi_turn, tool_call, edge_case
    
    dataset_type: Mapped[DatasetType] = mapped_column(
        Enum(DatasetType),
        nullable=False,
        index=True
    )
    
    # Content (정제된 형태)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_output: Mapped[dict] = mapped_column(JSON, nullable=False)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Metadata
    intent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    difficulty_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # easy, medium, hard
    
    # Quality
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    human_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Tags
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_sample_type_dataset', 'sample_type', 'dataset_type'),
        Index('idx_sample_intent_tool', 'intent', 'tool_name'),
    )
