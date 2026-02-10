"""
SQLAlchemy Models for Orders
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import (
    BigInteger, String, Text, Numeric, Integer,
    DateTime, Enum, ForeignKey, CheckConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.users.models import User
    from ecommerce.platform.backend.app.router.shipping.models import ShippingInfo
    from ecommerce.platform.backend.app.router.payments.models import Payment
    from ecommerce.platform.backend.app.router.points.models import PointHistory
    from ecommerce.platform.backend.app.router.reviews.models import Review

# Enum imports
from ecommerce.platform.backend.app.router.orders import schemas


# ============================================
# Order
# ============================================

class Order(Base):
    """주문"""
    __tablename__ = "orders"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_order_number', 'order_number'),
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_status', 'status'),
        CheckConstraint('subtotal >= 0', name='orders_chk_1'),
        CheckConstraint('discount_amount >= 0', name='orders_chk_2'),
        CheckConstraint('shipping_fee >= 0', name='orders_chk_3'),
        CheckConstraint('total_amount >= 0', name='orders_chk_4'),
        CheckConstraint('points_used >= 0', name='orders_chk_5'),
        {'comment': '주문'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='주문 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='RESTRICT'),
        nullable=False, comment='회원 ID'
    )
    order_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment='주문 번호 (고유값)'
    )
    shipping_address_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('shippingaddresses.id', ondelete='RESTRICT'),
        nullable=False, comment='배송지 ID'
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='상품 금액 합계'
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal('0'), comment='할인 금액'
    )
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal('0'), comment='배송비'
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='최종 결제 금액'
    )
    points_used: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal('0'), comment='사용한 포인트 금액'
    )
    status: Mapped[schemas.OrderStatus] = mapped_column(
        Enum(schemas.OrderStatus, values_callable=lambda x: [e.value for e in x]),
        default=schemas.OrderStatus.PENDING,
        comment='주문 상태'
    )
    payment_method: Mapped[str] = mapped_column(
        String(50), nullable=False, comment='결제 수단'
    )
    shipping_request: Mapped[Optional[str]] = mapped_column(
        Text, comment='배송요청 사항 텍스트 (주문별로 저장)'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment='수정일시'
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="orders")
    shipping_info: Mapped["ShippingInfo"] = relationship(back_populates="order")
    items: Mapped[List["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    payment: Mapped[Optional["Payment"]] = relationship(
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
    point_history: Mapped[List["PointHistory"]] = relationship(
        "PointHistory",
        back_populates="order",
        cascade="all, delete-orphan"
    )

# ============================================
# OrderItem
# ============================================

class OrderItem(Base):
    """주문 항목"""
    __tablename__ = "orderitems"
    __table_args__ = (
        Index('idx_order_id', 'order_id'),
        CheckConstraint('quantity > 0', name='orderitems_chk_1'),
        CheckConstraint('unit_price >= 0', name='orderitems_chk_2'),
        CheckConstraint('subtotal >= 0', name='orderitems_chk_3'),
        {'comment': '주문 항목'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='주문 항목 고유 ID'
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('orders.id', ondelete='CASCADE'),
        nullable=False, comment='주문 ID'
    )
    product_option_type: Mapped[schemas.ProductType] = mapped_column(
        Enum(schemas.ProductType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, comment='옵션 유형 (신상품/중고상품)'
    )
    product_option_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment='품목 옵션 ID (ProductOptions.id 또는 UsedProductOptions.id)'
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, comment='수량'
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='단가 (주문 당시 가격)'
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='소계 (unit_price * quantity)'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )

    # Relationships
    order: Mapped["Order"] = relationship(back_populates="items")

    reviews: Mapped[List["Review"]] = relationship(
        "Review",
        back_populates="order_item",
        cascade="all, delete-orphan"
    )
