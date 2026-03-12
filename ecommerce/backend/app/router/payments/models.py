"""
SQLAlchemy Models - Payments Module
결제 관련 모델
"""
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, String, Text,
    DateTime, Enum, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.orders.models import Order


# ==================================================
# Enums
# ==================================================

class PaymentStatus(str, PyEnum):
    """결제 상태"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ==================================================
# Payment Model
# ==================================================

class Payment(Base):
    """결제"""
    __tablename__ = "payments"
    __table_args__ = (
        Index('idx_order_id', 'order_id'),
        {'comment': '결제'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='결제 고유 ID'
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('orders.id', ondelete='CASCADE'),
        unique=True, nullable=False, comment='주문 ID (1:1 관계)'
    )
    payment_method: Mapped[str] = mapped_column(
        String(50), nullable=False, comment='결제 수단 (카드, 계좌이체 등)'
    )
    payment_data: Mapped[Optional[str]] = mapped_column(
        Text, comment='결제 수단에 관한 데이터 (JSON)'
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False, comment='결제 상태'
    )
    card_numbers: Mapped[Optional[str]] = mapped_column(
        String(50), comment='카드번호 (마스킹 처리된 값 저장 권장)'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), comment='수정일시'
    )

    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="payment"
    )
