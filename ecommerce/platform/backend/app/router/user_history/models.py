"""
SQLAlchemy Models - User History Module
사용자 행동 히스토리 관련 모델
"""
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, String, Text, DateTime, Enum, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.users.models import User
    from ecommerce.platform.backend.app.router.orders.models import Order


# ==================================================
# Enums
# ==================================================

class ActionType(str, PyEnum):
    """사용자 행동 유형"""
    # 인증 관련
    LOGIN = "login"
    LOGOUT = "logout"

    # 장바구니 관련
    CART_ADD = "cart_add"
    CART_REMOVE = "cart_remove"

    # 주문 관련
    ORDER_CREATE = "order_create"  # 결제 완료
    ORDER_CANCEL = "order_cancel"

    # 환불 관련
    REFUND_REQUEST = "refund_request"

    # 리뷰 관련
    REVIEW_CREATE = "review_create"


# ==================================================
# User History Models
# ==================================================

class UserHistory(Base):
    """사용자 행동 히스토리"""
    __tablename__ = "userhistory"
    __table_args__ = (
        # 성능 최적화를 위한 인덱스
        Index('idx_user_id', 'user_id'),
        Index('idx_action_type', 'action_type'),
        Index('idx_user_action', 'user_id', 'action_type'),
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_created_at', 'created_at'),
        # 상품 관련 행동 조회 최적화
        Index('idx_product_option', 'product_option_type', 'product_option_id'),
        {'comment': '사용자 행동 히스토리'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment='히스토리 고유 ID'
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )

    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, comment='행동 유형'
    )

    # 선택적 외래키 (행동에 따라 다르게 사용)
    product_option_type: Mapped[Optional[str]] = mapped_column(
        String(20), comment='상품 옵션 유형 (new/used)'
    )

    product_option_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='상품 옵션 ID'
    )

    order_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('orders.id', ondelete='SET NULL'),
        comment='관련 주문 ID'
    )

    cart_item_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('cartitems.id', ondelete='SET NULL'),
        comment='관련 장바구니 항목 ID'
    )

    # JSON 형태의 메타데이터 (유연성 확보)
    action_metadata: Mapped[Optional[str]] = mapped_column(
        Text, comment='추가 메타데이터 (JSON 형식)'
    )

    # 검색어 저장
    search_keyword: Mapped[Optional[str]] = mapped_column(
        String(255), comment='검색 키워드'
    )

    # IP 주소 (선택사항)
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), comment='IP 주소 (IPv4/IPv6)'
    )

    # User Agent (선택사항)
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text, comment='User Agent 정보'
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        comment='행동 발생 시각'
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="user_history"
    )

    order: Mapped[Optional["Order"]] = relationship(
        "Order",
        back_populates="user_history"
    )
