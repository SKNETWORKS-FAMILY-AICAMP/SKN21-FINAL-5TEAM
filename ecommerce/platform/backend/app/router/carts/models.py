"""
SQLAlchemy Models for E-commerce Platform
FastAPI + SQLAlchemy ORM
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, String, Text, Numeric, Integer, Boolean, 
    DateTime, Enum, ForeignKey, CheckConstraint, Index, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base
from ecommerce.platform.backend.app.router.carts import schemas

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.users.models import User
    from ecommerce.platform.backend.app.router.products.models import ProductOption, UsedProductOption
# ============================================
# Cart
# ============================================

class Cart(Base):
    """장바구니"""
    __tablename__ = "Carts"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        {'comment': '장바구니'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='장바구니 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        unique=True, nullable=False, comment='회원 ID (사용자당 1개)'
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
    user: Mapped["User"] = relationship(back_populates="carts")
    items: Mapped[List["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItem(Base):
    """장바구니 항목"""
    __tablename__ = "CartItems"
    __table_args__ = (
        Index('idx_cart_id', 'cart_id'),
        UniqueConstraint(
            'cart_id', 'product_option_type', 'product_option_id',
            name='uk_cart_option'
        ),
        CheckConstraint('quantity > 0', name='chk_cart_item_quantity'),
        {'comment': '장바구니 항목'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, 
        comment='장바구니 항목 고유 ID'
    )
    cart_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Carts.id', ondelete='CASCADE'),
        nullable=False, comment='장바구니 ID'
    )
    product_option_type: Mapped[schemas.ProductType] = mapped_column(
        Enum(schemas.ProductType, values_callable=lambda x: [e.value for e in x]), nullable=False, 
        comment='옵션 유형 구분 (신상품/중고상품)'
    )
    product_option_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, 
        comment='품목 옵션 ID (ProductOptions.id 또는 UsedProductOptions.id)'
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment='수량 (양수여야 함)'
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
    cart: Mapped["Cart"] = relationship(back_populates="items")

    # 신상품 옵션 관계
    product_option: Mapped[Optional["ProductOption"]] = relationship(
        "ProductOption",
        primaryjoin="and_(CartItem.product_option_id==foreign(ProductOption.id), "
                    "CartItem.product_option_type=='new')",
        viewonly=True
    )

    # 중고상품 옵션 관계
    used_product_option: Mapped[Optional["UsedProductOption"]] = relationship(
        "UsedProductOption",
        primaryjoin="and_(CartItem.product_option_id==foreign(UsedProductOption.id), "
                    "CartItem.product_option_type=='used')",
        viewonly=True
    )