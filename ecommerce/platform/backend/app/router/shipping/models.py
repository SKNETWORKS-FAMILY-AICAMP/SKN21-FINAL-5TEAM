"""
SQLAlchemy Models - Shipping Module
배송지 및 배송 관련 모델
"""
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger, String, Text, Integer, Boolean,
    DateTime, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.users.models import User
    from ecommerce.platform.backend.app.router.orders.models import Order

# ==================================================
# Shipping Models
# ==================================================

class ShippingAddress(Base):
    """배송지"""
    __tablename__ = "shippingaddresses"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_user_default', 'user_id', 'is_default'),
        {'comment': '배송지'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='배송지 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )
    recipient_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment='수령인 이름'
    )
    address1: Mapped[str] = mapped_column(
        String(255), nullable=False, comment='주소1 (기본 주소)'
    )
    address2: Mapped[Optional[str]] = mapped_column(
        String(255), comment='주소2 (상세 주소)'
    )
    post_code: Mapped[str] = mapped_column(
        String(10), nullable=False, comment='우편번호'
    )
    phone: Mapped[str] = mapped_column(
        String(20), nullable=False, comment='핸드폰번호'
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, comment='기본배송지 여부'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), comment='수정일시'
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='삭제 일시 (소프트 삭제)'
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="shipping_addresses"
    )


class ShippingRequestTemplate(Base):
    """배송요청사항 템플릿"""
    __tablename__ = "shippingrequesttemplates"
    __table_args__ = {'comment': '배송요청사항 템플릿 (UI에서 선택용)'}

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment='배송요청사항 템플릿 고유 ID'
    )
    template_text: Mapped[str] = mapped_column(
        Text, nullable=False, comment='배송요청사항 텍스트'
    )
    display_order: Mapped[int] = mapped_column(
        Integer, default=0, comment='표시 순서'
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment='활성화 여부'
    )


class ShippingInfo(Base):
    """배송 정보"""
    __tablename__ = "shippinginfo"
    __table_args__ = (
        Index('idx_order_id', 'order_id'),
        Index('idx_tracking_number', 'tracking_number'),
        {'comment': '배송 정보'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='배송 정보 고유 ID'
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('orders.id', ondelete='CASCADE'),
        unique=True, nullable=False, comment='주문 ID (1:1 관계)'
    )
    courier_company: Mapped[Optional[str]] = mapped_column(
        String(100), comment='택배사'
    )
    tracking_number: Mapped[Optional[str]] = mapped_column(
        String(100), comment='송장 번호'
    )
    shipped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='배송 시작 일시'
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='배송 완료 일시'
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
        back_populates="shipping_info"
    )
