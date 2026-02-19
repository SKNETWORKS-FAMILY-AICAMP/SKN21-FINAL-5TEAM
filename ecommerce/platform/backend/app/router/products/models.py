"""
SQLAlchemy Models - Products Module
카테고리, 신상품, 중고상품 관련 모델
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, String, Text, Numeric, Integer, Boolean,
    DateTime, Enum, ForeignKey, CheckConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.users.models import User
    from ecommerce.platform.backend.app.router.carts.models import CartItem


# ==================================================
# Enums
# ==================================================

class ProductType(str, PyEnum):
    """상품 유형"""
    NEW = "new"
    USED = "used"


class UsedProductStatus(str, PyEnum):
    """중고 상품 판매 상태"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SOLD = "sold"


# ==================================================
# Category Model
# ==================================================

class Category(Base):
    """카테고리"""
    __tablename__ = "categories"
    __table_args__ = (
        Index('idx_parent_id', 'parent_id'),
        {'comment': '카테고리'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='카테고리 고유 ID'
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment='카테고리명'
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('categories.id', ondelete='SET NULL'),
        comment='상위 카테고리 ID (계층 구조 지원)'
    )
    display_order: Mapped[int] = mapped_column(
        Integer, default=0, comment='표시 순서'
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment='활성화 여부'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), comment='수정일시'
    )

    # Relationships
    products: Mapped[List["Product"]] = relationship(
        "Product",
        back_populates="category"
    )
    used_products: Mapped[List["UsedProduct"]] = relationship(
        "UsedProduct",
        back_populates="category"
    )
    parent: Mapped[Optional["Category"]] = relationship(
        "Category",
        remote_side=[id],
        back_populates="children"
    )
    children: Mapped[List["Category"]] = relationship(
        "Category",
        back_populates="parent",
        cascade="all, delete-orphan"
    )


# ==================================================
# Product Models
# ==================================================

class Product(Base):
    """신상품"""
    __tablename__ = "products"
    __table_args__ = (
        Index('idx_category_id', 'category_id'),
        Index('idx_active_created', 'is_active', 'created_at'),
        CheckConstraint('price > 0', name='products_chk_1'),
        {'comment': '신상품'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='품목 고유 ID'
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('categories.id', ondelete='RESTRICT'),
        nullable=False, comment='카테고리 ID'
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment='품목명'
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, comment='상품 설명'
    )
    tags: Mapped[Optional[str]] = mapped_column(
        Text, comment='태그 (콤마 구분 또는 JSON)'
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='가격 (양수여야 함)'
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment='판매 활성화 여부'
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
    category: Mapped["Category"] = relationship(
        "Category",
        back_populates="products"
    )
    options: Mapped[List["ProductOption"]] = relationship(
        "ProductOption",
        back_populates="product",
        cascade="all, delete-orphan"
    )


class ProductOption(Base):
    """신상품 옵션 (사이즈, 색상, 재고)"""
    __tablename__ = "productoptions"
    __table_args__ = (
        Index('idx_product_id', 'product_id'),
        Index('idx_sku', 'sku'),
        CheckConstraint('quantity >= 0', name='productoptions_chk_1'),
        {'comment': '신상품 옵션 (사이즈, 색상, 재고)'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='품목 옵션 고유 ID'
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('products.id', ondelete='CASCADE'),
        nullable=False, comment='신상품 ID'
    )
    size_name: Mapped[Optional[str]] = mapped_column(
        String(20), comment='사이즈명 (S, M, L, XL 등)'
    )
    color: Mapped[Optional[str]] = mapped_column(
        String(50), comment='색상'
    )
    quantity: Mapped[int] = mapped_column(
        Integer, default=0, comment='수량 (재고, 음수 불가)'
    )
    sku: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, comment='SKU (Stock Keeping Unit)'
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment='옵션 활성화 여부'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), comment='수정일시'
    )

    # Relationships
    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="options"
    )
    cart_items: Mapped[List["CartItem"]] = relationship(
        "CartItem",
        foreign_keys="CartItem.product_option_id",
        primaryjoin="and_(ProductOption.id==CartItem.product_option_id, "
                    "CartItem.product_option_type=='new')",
        viewonly=True
    )


# ==================================================
# Used Product Models
# ==================================================

class UsedProductCondition(Base):
    """중고 품목 상태"""
    __tablename__ = "usedproductconditions"
    __table_args__ = (
        CheckConstraint('depreciation_percent BETWEEN 0 AND 100',
                       name='usedproductconditions_chk_1'),
        {'comment': '중고 품목 상태'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='중고 품목 상태 고유 ID'
    )
    condition_name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment='중고 품목 상태 (최상, 상, 중, 하)'
    )
    depreciation_percent: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='감가 퍼센트 (0-100 사이)'
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, comment='상태 설명'
    )

    # Relationships
    used_products: Mapped[List["UsedProduct"]] = relationship(
        "UsedProduct",
        back_populates="condition"
    )


class UsedProduct(Base):
    """중고 품목"""
    __tablename__ = "usedproducts"
    __table_args__ = (
        Index('idx_category_id', 'category_id'),
        Index('idx_seller_id', 'seller_id'),
        Index('idx_status_created', 'status', 'created_at'),
        CheckConstraint('price > 0', name='usedproducts_chk_1'),
        {'comment': '중고 품목'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='중고 품목 고유 ID'
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('categories.id', ondelete='RESTRICT'),
        nullable=False, comment='카테고리 ID'
    )
    seller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, comment='판매자 ID (Users 참조)'
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment='품목명'
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, comment='상품 설명'
    )
    tags: Mapped[Optional[str]] = mapped_column(
        Text, comment='태그'
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='가격'
    )
    condition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('usedproductconditions.id', ondelete='RESTRICT'),
        nullable=False, comment='중고 품목 상태 ID'
    )
    status: Mapped[UsedProductStatus] = mapped_column(
        Enum(UsedProductStatus, values_callable=lambda x: [e.value for e in x]),
        default=UsedProductStatus.PENDING, comment='판매 상태'
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
    category: Mapped["Category"] = relationship(
        "Category",
        back_populates="used_products"
    )
    seller: Mapped["User"] = relationship(
        "User",
        back_populates="used_products"
    )
    condition: Mapped["UsedProductCondition"] = relationship(
        "UsedProductCondition",
        back_populates="used_products"
    )
    options: Mapped[List["UsedProductOption"]] = relationship(
        "UsedProductOption",
        back_populates="used_product",
        cascade="all, delete-orphan"
    )


class UsedProductOption(Base):
    """중고상품 옵션"""
    __tablename__ = "usedproductoptions"
    __table_args__ = (
        Index('idx_used_product_id', 'used_product_id'),
        CheckConstraint('quantity >= 0', name='usedproductoptions_chk_1'),
        {'comment': '중고상품 옵션 - 신상품과 분리'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='중고 품목 옵션 고유 ID'
    )
    used_product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('usedproducts.id', ondelete='CASCADE'),
        nullable=False, comment='중고 품목 ID'
    )
    size_name: Mapped[Optional[str]] = mapped_column(
        String(20), comment='사이즈명'
    )
    color: Mapped[Optional[str]] = mapped_column(
        String(50), comment='색상'
    )
    quantity: Mapped[int] = mapped_column(
        Integer, default=1, comment='수량 (중고는 보통 1개)'
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment='옵션 활성화 여부'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), comment='수정일시'
    )

    # Relationships
    used_product: Mapped["UsedProduct"] = relationship(
        "UsedProduct",
        back_populates="options"
    )
    cart_items: Mapped[List["CartItem"]] = relationship(
        "CartItem",
        foreign_keys="CartItem.product_option_id",
        primaryjoin="and_(UsedProductOption.id==CartItem.product_option_id, "
                    "CartItem.product_option_type=='used')",
        viewonly=True
    )


# ==================================================
# Product Image Model
# ==================================================

class ProductImage(Base):
    """상품 이미지"""
    __tablename__ = "productimages"
    __table_args__ = (
        Index('idx_product', 'product_type', 'product_id'),
        {'comment': '상품 이미지'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='이미지 고유 ID'
    )
    product_type: Mapped[ProductType] = mapped_column(
        Enum(ProductType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, comment='상품 유형 (신상품/중고상품)'
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment='상품 ID (Products.id 또는 UsedProducts.id)'
    )
    image_url: Mapped[str] = mapped_column(
        String(500), nullable=False, comment='이미지 URL'
    )
    display_order: Mapped[int] = mapped_column(
        Integer, default=0, comment='표시 순서 (정렬용)'
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, comment='대표 이미지 여부'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
