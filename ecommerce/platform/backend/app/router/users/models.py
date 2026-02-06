# from db.models import User

"""
SQLAlchemy Models for E-commerce Platform
FastAPI + SQLAlchemy ORM
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, String, Text, Numeric, Integer, Boolean, 
    DateTime, Enum, ForeignKey, CheckConstraint, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from ecommerce.platform.backend.app.database import Base # 일단 내가 수정 한 부분


# ============================================
# Enums
# ============================================

class UserStatus(str, PyEnum):
    """사용자 계정 상태"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


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


class OrderStatus(str, PyEnum):
    """주문 상태"""
    PENDING = "pending"
    PAID = "paid"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, PyEnum):
    """결제 상태"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PointType(str, PyEnum):
    """포인트 유형"""
    EARN = "earn"
    USE = "use"
    EXPIRE = "expire"
    REFUND = "refund"


class TransactionType(str, PyEnum):
    """재고 거래 유형"""
    PURCHASE = "purchase"
    SALE = "sale"
    RETURN = "return"
    ADJUSTMENT = "adjustment"


# ============================================
# User Management
# ============================================

class User(Base):
    """회원 정보"""
    __tablename__ = "Users"
    __table_args__ = (
        Index('idx_email', 'email'),
        {'comment': '회원 정보'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='회원 고유 ID'
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, comment='이메일 (로그인용) - 고유값'
    )
    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255), comment='암호화된 비밀번호'
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment='회원 이름'
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(20), comment='핸드폰번호'
    )
    # status: Mapped[UserStatus] = mapped_column(
    #     Enum(UserStatus), default=UserStatus.ACTIVE, comment='계정상태'
    # )
    status: Mapped[UserStatus] = mapped_column(
    Enum(
        UserStatus,
        values_callable=lambda enum: [e.value for e in enum],
        name="userstatus",
        ),
        default=UserStatus.ACTIVE,
        comment='계정상태'
    )
    address1: Mapped[Optional[str]] = mapped_column(
        String(255), comment='주소1 (기본 주소)'
    )
    address2: Mapped[Optional[str]] = mapped_column(
        String(255), comment='주소2 (상세 주소)'
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
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='마지막 로그인 일시'
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='삭제 일시 (소프트 삭제)'
    )

    # Relationships
    body_measurements: Mapped[Optional["UserBodyMeasurement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    carts: Mapped[Optional["Cart"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    shipping_addresses: Mapped[List["ShippingAddress"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    orders: Mapped[List["Order"]] = relationship(
        back_populates="user"
    )
    reviews: Mapped[List["Review"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    point_history: Mapped[List["PointHistory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    vouchers: Mapped[List["IssuedVoucher"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    used_products: Mapped[List["UsedProduct"]] = relationship(
        back_populates="seller", cascade="all, delete-orphan"
    )


class UserBodyMeasurement(Base):
    """사용자 신체 치수"""
    __tablename__ = "UserBodyMeasurements"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        {'comment': '사용자 신체 치수'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='신체 치수 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Users.id', ondelete='CASCADE'), 
        unique=True, nullable=False, comment='회원 ID (1:1 관계)'
    )
    
    # 기본 정보
    height: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='키 (cm)'
    )
    weight: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='몸무게 (kg)'
    )
    
    # 상체 정보
    upper_total_length: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='상체 총장 (cm)'
    )
    shoulder_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='어깨너비 (cm)'
    )
    chest_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='가슴단면 (cm)'
    )
    sleeve_length: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='소매길이 (cm)'
    )
    
    # 하체 정보
    lower_total_length: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='하체 총장 (cm)'
    )
    waist_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='허리단면 (cm)'
    )
    hip_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='엉덩이단면 (cm)'
    )
    thigh_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='허벅지단면 (cm)'
    )
    rise: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='밑위 (cm)'
    )
    hem_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='밑단단면 (cm)'
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
    user: Mapped["User"] = relationship(back_populates="body_measurements")


# ============================================
# Product Management
# ============================================

class Category(Base):
    """카테고리"""
    __tablename__ = "Categories"
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
        BigInteger, ForeignKey('Categories.id', ondelete='SET NULL'), 
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
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment='수정일시'
    )

    # Relationships
    products: Mapped[List["Product"]] = relationship(back_populates="category")
    used_products: Mapped[List["UsedProduct"]] = relationship(back_populates="category")
    parent: Mapped[Optional["Category"]] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[List["Category"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class Product(Base):
    """신상품"""
    __tablename__ = "Products"
    __table_args__ = (
        Index('idx_category_id', 'category_id'),
        Index('idx_active_created', 'is_active', 'created_at'),
        CheckConstraint('price > 0', name='chk_products_price'),
        {'comment': '신상품'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='품목 고유 ID'
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Categories.id', ondelete='RESTRICT'),
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
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment='수정일시'
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='삭제 일시 (소프트 삭제)'
    )

    # Relationships
    category: Mapped["Category"] = relationship(back_populates="products")
    options: Mapped[List["ProductOption"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class UsedProductCondition(Base):
    """중고 품목 상태"""
    __tablename__ = "UsedProductConditions"
    __table_args__ = (
        CheckConstraint(
            'depreciation_percent BETWEEN 0 AND 100', 
            name='chk_depreciation_percent'
        ),
        {'comment': '중고 품목 상태'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, 
        comment='중고 품목 상태 고유 ID'
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
        back_populates="condition"
    )


class UsedProduct(Base):
    """중고 품목"""
    __tablename__ = "UsedProducts"
    __table_args__ = (
        Index('idx_category_id', 'category_id'),
        Index('idx_seller_id', 'seller_id'),
        Index('idx_status_created', 'status', 'created_at'),
        CheckConstraint('price > 0', name='chk_used_products_price'),
        {'comment': '중고 품목'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='중고 품목 고유 ID'
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Categories.id', ondelete='RESTRICT'),
        nullable=False, comment='카테고리 ID'
    )
    seller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Users.id', ondelete='CASCADE'),
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
        BigInteger, ForeignKey('UsedProductConditions.id', ondelete='RESTRICT'),
        nullable=False, comment='중고 품목 상태 ID'
    )
    status: Mapped[UsedProductStatus] = mapped_column(
        Enum(UsedProductStatus), default=UsedProductStatus.PENDING, 
        comment='판매 상태'
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
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='삭제 일시 (소프트 삭제)'
    )

    # Relationships
    category: Mapped["Category"] = relationship(back_populates="used_products")
    seller: Mapped["User"] = relationship(back_populates="used_products")
    condition: Mapped["UsedProductCondition"] = relationship(
        back_populates="used_products"
    )
    options: Mapped[List["UsedProductOption"]] = relationship(
        back_populates="used_product", cascade="all, delete-orphan"
    )


class ProductOption(Base):
    """신상품 옵션 (사이즈, 색상, 재고)"""
    __tablename__ = "ProductOptions"
    __table_args__ = (
        Index('idx_product_id', 'product_id'),
        Index('idx_sku', 'sku'),
        CheckConstraint('quantity >= 0', name='chk_product_option_quantity'),
        {'comment': '신상품 옵션 (사이즈, 색상, 재고)'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, 
        comment='품목 옵션 고유 ID'
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Products.id', ondelete='CASCADE'),
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
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment='수정일시'
    )

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="options")


class UsedProductOption(Base):
    """중고상품 옵션 - 신상품과 분리"""
    __tablename__ = "UsedProductOptions"
    __table_args__ = (
        Index('idx_used_product_id', 'used_product_id'),
        CheckConstraint('quantity >= 0', name='chk_used_product_option_quantity'),
        {'comment': '중고상품 옵션 - 신상품과 분리'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, 
        comment='중고 품목 옵션 고유 ID'
    )
    used_product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('UsedProducts.id', ondelete='CASCADE'),
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
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment='수정일시'
    )

    # Relationships
    used_product: Mapped["UsedProduct"] = relationship(back_populates="options")


class ProductImage(Base):
    """상품 이미지"""
    __tablename__ = "ProductImages"
    __table_args__ = (
        Index('idx_product', 'product_type', 'product_id'),
        {'comment': '상품 이미지'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='이미지 고유 ID'
    )
    product_type: Mapped[ProductType] = mapped_column(
        Enum(ProductType), nullable=False, 
        comment='상품 유형 (신상품/중고상품)'
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, 
        comment='상품 ID (Products.id 또는 UsedProducts.id)'
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
        BigInteger, ForeignKey('Users.id', ondelete='CASCADE'),
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
    product_option_type: Mapped[ProductType] = mapped_column(
        Enum(ProductType), nullable=False, 
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


# ============================================
# Shipping (Moved to router/shipping/models.py)
# ============================================

# class ShippingAddress(Base):
#     """배송지"""
#     __tablename__ = "ShippingAddresses"
#     __table_args__ = (
#         Index('idx_user_id', 'user_id'),
#         Index('idx_user_default', 'user_id', 'is_default'),
#         {'comment': '배송지'}
#     )
# 
#     id: Mapped[int] = mapped_column(
#         BigInteger, primary_key=True, autoincrement=True, comment='배송지 고유 ID'
#     )
#     user_id: Mapped[int] = mapped_column(
#         BigInteger, ForeignKey('Users.id', ondelete='CASCADE'),
#         nullable=False, comment='회원 ID'
#     )
#     recipient_name: Mapped[str] = mapped_column(
#         String(100), nullable=False, comment='수령인 이름'
#     )
#     address1: Mapped[str] = mapped_column(
#         String(255), nullable=False, comment='주소1 (기본 주소)'
#     )
#     address2: Mapped[Optional[str]] = mapped_column(
#         String(255), comment='주소2 (상세 주소)'
#     )
#     phone: Mapped[str] = mapped_column(
#         String(20), nullable=False, comment='핸드폰번호'
#     )
#     is_default: Mapped[bool] = mapped_column(
#         Boolean, default=False, comment='기본배송지 여부'
#     )
#     created_at: Mapped[datetime] = mapped_column(
#         DateTime, server_default=func.current_timestamp(), comment='생성일시'
#     )
#     updated_at: Mapped[datetime] = mapped_column(
#         DateTime,
#         server_default=func.current_timestamp(),
#         onupdate=func.current_timestamp(),
#         comment='수정일시'
#     )
#     deleted_at: Mapped[Optional[datetime]] = mapped_column(
#         DateTime, comment='삭제 일시 (소프트 삭제)'
#     )
# 
#     # Relationships
#     user: Mapped["User"] = relationship(back_populates="shipping_addresses")
#     orders: Mapped[List["Order"]] = relationship(back_populates="shipping_address")
# 
# 
# class ShippingRequestTemplate(Base):
#     """배송요청사항 템플릿 (UI에서 선택용)"""
#     __tablename__ = "ShippingRequestTemplates"
#     __table_args__ = {'comment': '배송요청사항 템플릿 (UI에서 선택용)'}
# 
#     id: Mapped[int] = mapped_column(
#         BigInteger, primary_key=True, autoincrement=True, 
#         comment='배송요청사항 템플릿 고유 ID'
#     )
#     template_text: Mapped[str] = mapped_column(
#         Text, nullable=False, comment='배송요청사항 텍스트'
#     )
#     display_order: Mapped[int] = mapped_column(
#         Integer, default=0, comment='표시 순서'
#     )
#     is_active: Mapped[bool] = mapped_column(
#         Boolean, default=True, comment='활성화 여부'
#     )


# ============================================
# Orders and Payments
# ============================================

class Order(Base):
    """주문"""
    __tablename__ = "Orders"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_order_number', 'order_number'),
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_status', 'status'),
        CheckConstraint('subtotal >= 0', name='chk_order_subtotal'),
        CheckConstraint('discount_amount >= 0', name='chk_order_discount'),
        CheckConstraint('shipping_fee >= 0', name='chk_order_shipping_fee'),
        CheckConstraint('total_amount >= 0', name='chk_order_total'),
        CheckConstraint('points_used >= 0', name='chk_order_points'),
        {'comment': '주문'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='주문 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Users.id', ondelete='RESTRICT'),
        nullable=False, comment='회원 ID'
    )
    order_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment='주문 번호 (고유값)'
    )
    shipping_address_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('ShippingAddresses.id', ondelete='RESTRICT'),
        nullable=False, comment='배송지 ID'
    )
    
    # 금액 관련
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='상품 금액 합계'
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal('0.00'), comment='할인 금액'
    )
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal('0.00'), comment='배송비'
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, comment='최종 결제 금액'
    )
    
    # 할인 관련
    points_used: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal('0.00'), comment='사용한 포인트 금액'
    )
    
    # 상태 관련
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.PENDING, comment='주문 상태'
    )
    payment_method: Mapped[str] = mapped_column(
        String(50), nullable=False, comment='결제 수단'
    )
    
    # 배송 관련
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
    shipping_address: Mapped["ShippingAddress"] = relationship(
        back_populates="orders"
    )
    items: Mapped[List["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    payment: Mapped[Optional["Payment"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )
    shipping_info: Mapped[Optional["ShippingInfo"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )
    status_history: Mapped[List["OrderStatusHistory"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    """주문 항목"""
    __tablename__ = "OrderItems"
    __table_args__ = (
        Index('idx_order_id', 'order_id'),
        CheckConstraint('quantity > 0', name='chk_order_item_quantity'),
        CheckConstraint('unit_price >= 0', name='chk_order_item_unit_price'),
        CheckConstraint('subtotal >= 0', name='chk_order_item_subtotal'),
        {'comment': '주문 항목'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='주문 항목 고유 ID'
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Orders.id', ondelete='CASCADE'),
        nullable=False, comment='주문 ID'
    )
    product_option_type: Mapped[ProductType] = mapped_column(
        Enum(ProductType), nullable=False, 
        comment='옵션 유형 (신상품/중고상품)'
    )
    product_option_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, 
        comment='품목 옵션 ID (ProductOptions.id 또는 UsedProductOptions.id)'
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
        back_populates="order_item", cascade="all, delete-orphan"
    )


class Payment(Base):
    """결제"""
    __tablename__ = "Payments"
    __table_args__ = (
        Index('idx_order_id', 'order_id'),
        {'comment': '결제'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='결제 고유 ID'
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Orders.id', ondelete='CASCADE'),
        unique=True, nullable=False, comment='주문 ID (1:1 관계)'
    )
    payment_method: Mapped[str] = mapped_column(
        String(50), nullable=False, comment='결제 수단 (카드, 계좌이체 등)'
    )
    payment_data: Mapped[Optional[str]] = mapped_column(
        Text, comment='결제 수단에 관한 데이터 (JSON)'
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), nullable=False, comment='결제 상태'
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
    order: Mapped["Order"] = relationship(back_populates="payment")


class ShippingInfo(Base):
    """배송 정보"""
    __tablename__ = "ShippingInfo"
    __table_args__ = (
        Index('idx_order_id', 'order_id'),
        Index('idx_tracking_number', 'tracking_number'),
        {'comment': '배송 정보'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='배송 정보 고유 ID'
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Orders.id', ondelete='CASCADE'),
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
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment='수정일시'
    )

    # Relationships
    order: Mapped["Order"] = relationship(back_populates="shipping_info")


class OrderStatusHistory(Base):
    """주문 상태 이력"""
    __tablename__ = "OrderStatusHistory"
    __table_args__ = (
        Index('idx_order_id', 'order_id'),
        {'comment': '주문 상태 이력'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, 
        comment='주문 상태 이력 고유 ID'
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Orders.id', ondelete='CASCADE'),
        nullable=False, comment='주문 ID'
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, comment='변경된 상태'
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, comment='비고 (상태 변경 사유 등)'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='상태 변경 일시'
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='변경자 (관리자 또는 시스템)'
    )

    # Relationships
    order: Mapped["Order"] = relationship(back_populates="status_history")


# ============================================
# Reviews
# ============================================

class Review(Base):
    """리뷰"""
    __tablename__ = "Reviews"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_order_item_id', 'order_item_id'),
        UniqueConstraint('order_item_id', name='uk_order_item_review'),
        CheckConstraint('rating BETWEEN 1 AND 5', name='chk_review_rating'),
        {'comment': '리뷰'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='리뷰 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )
    order_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('OrderItems.id', ondelete='CASCADE'),
        nullable=False, comment='주문 항목 ID'
    )
    content: Mapped[Optional[str]] = mapped_column(
        Text, comment='리뷰 내용'
    )
    rating: Mapped[int] = mapped_column(
        Integer, nullable=False, comment='평점 (1-5)'
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
    user: Mapped["User"] = relationship(back_populates="reviews")
    order_item: Mapped["OrderItem"] = relationship(back_populates="reviews")


# ============================================
# Points and Vouchers
# ============================================

class PointHistory(Base):
    """포인트 내역"""
    __tablename__ = "PointHistory"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_user_created', 'user_id', 'created_at'),
        {'comment': '포인트 내역'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, 
        comment='포인트 내역 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('Orders.id', ondelete='SET NULL'),
        comment='주문 ID (선택사항, 출처 추적용)'
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, 
        comment='변동 포인트 금액 (양수: 적립, 음수: 사용)'
    )
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, 
        comment='변동 후 잔액 (현재 포인트 계산용)'
    )
    type: Mapped[PointType] = mapped_column(
        Enum(PointType), nullable=False, comment='포인트 유형'
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, comment='포인트 변동 설명'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="point_history")


class IssuedVoucher(Base):
    """발급된 상품권"""
    __tablename__ = "IssuedVouchers"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_voucher_code', 'voucher_code'),
        CheckConstraint('amount > 0', name='chk_voucher_amount'),
        {'comment': '발급된 상품권'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, 
        comment='발급된 상품권 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('Users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )
    voucher_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, 
        comment='상품권 코드 (고유값)'
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
    user: Mapped["User"] = relationship(back_populates="vouchers")


# ============================================
# Inventory Management
# ============================================

class InventoryTransaction(Base):
    """재고 거래 내역"""
    __tablename__ = "InventoryTransactions"
    __table_args__ = (
        Index('idx_option', 'product_option_type', 'product_option_id'),
        Index('idx_created', 'created_at'),
        {'comment': '재고 거래 내역'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, 
        comment='재고 거래 내역 고유 ID'
    )
    product_option_type: Mapped[ProductType] = mapped_column(
        Enum(ProductType), nullable=False, comment='옵션 유형'
    )
    product_option_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment='품목 옵션 ID'
    )
    quantity_change: Mapped[int] = mapped_column(
        Integer, nullable=False, comment='수량 변동 (양수: 입고, 음수: 출고)'
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False, comment='거래 유형'
    )
    reference_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='Order ID 등 참조 ID'
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, comment='비고'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )

