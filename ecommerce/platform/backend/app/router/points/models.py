"""
SQLAlchemy Models - Points Module
포인트 및 상품권 관련 모델
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, String, Text, Numeric, Boolean,
    DateTime, Enum, ForeignKey, CheckConstraint, Index
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

class PointType(str, PyEnum):
    """포인트 유형"""
    EARN = "earn"
    USE = "use"
    EXPIRE = "expire"
    REFUND = "refund"


# ==================================================
# Point & Voucher Models
# ==================================================

class PointHistory(Base):
    """포인트 내역"""
    __tablename__ = "pointhistory"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_user_created', 'user_id', 'created_at'),
        {'comment': '포인트 내역'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='포인트 내역 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('orders.id', ondelete='SET NULL'),
        comment='주문 ID (선택사항, 출처 추적용)'
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='변동 포인트 금액 (양수: 적립, 음수: 사용)'
    )
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='변동 후 잔액 (현재 포인트 계산용)'
    )
    type: Mapped[PointType] = mapped_column(
        Enum(PointType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, comment='포인트 유형'
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, comment='포인트 변동 설명'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="point_history"
    )
    order: Mapped[Optional["Order"]] = relationship(
        "Order",
        back_populates="point_history"
    )


class IssuedVoucher(Base):
    """발급된 상품권"""
    __tablename__ = "issuedvouchers"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_voucher_code', 'voucher_code'),
        CheckConstraint('amount > 0', name='issuedvouchers_chk_1'),
        {'comment': '발급된 상품권'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='발급된 상품권 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )
    voucher_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, comment='상품권 코드 (고유값)'
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='상품권 금액'
    )
    is_used: Mapped[bool] = mapped_column(
        Boolean, default=False, comment='사용 여부'
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='사용 일시'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="issued_vouchers"
    )
