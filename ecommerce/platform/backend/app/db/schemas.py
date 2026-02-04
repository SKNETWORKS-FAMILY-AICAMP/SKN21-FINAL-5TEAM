"""
Pydantic Schemas for E-commerce Platform
FastAPI + Pydantic V2
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ============================================
# Enums (모델과 동일)
# ============================================

class UserStatus(str, Enum):
    """사용자 계정 상태"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class ProductType(str, Enum):
    """상품 유형"""
    NEW = "new"
    USED = "used"


class UsedProductStatus(str, Enum):
    """중고 상품 판매 상태"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SOLD = "sold"


class OrderStatus(str, Enum):
    """주문 상태"""
    PENDING = "pending"
    PAID = "paid"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, Enum):
    """결제 상태"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PointType(str, Enum):
    """포인트 유형"""
    EARN = "earn"
    USE = "use"
    EXPIRE = "expire"
    REFUND = "refund"


# ============================================
# User Schemas
# ============================================

class UserBase(BaseModel):
    """사용자 기본 스키마"""
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    address1: Optional[str] = Field(None, max_length=255)
    address2: Optional[str] = Field(None, max_length=255)


class UserCreate(UserBase):
    """사용자 생성"""
    password: str = Field(..., min_length=8, max_length=100)


class UserUpdate(BaseModel):
    """사용자 수정"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    address1: Optional[str] = Field(None, max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    status: Optional[UserStatus] = None


class UserResponse(UserBase):
    """사용자 응답"""
    id: int
    status: UserStatus
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================
# UserBodyMeasurement Schemas
# ============================================

class BodyMeasurementBase(BaseModel):
    """신체 치수 기본"""
    height: Optional[Decimal] = Field(None, ge=0, le=300)
    weight: Optional[Decimal] = Field(None, ge=0, le=500)
    upper_total_length: Optional[Decimal] = Field(None, ge=0)
    shoulder_width: Optional[Decimal] = Field(None, ge=0)
    chest_width: Optional[Decimal] = Field(None, ge=0)
    sleeve_length: Optional[Decimal] = Field(None, ge=0)
    lower_total_length: Optional[Decimal] = Field(None, ge=0)
    waist_width: Optional[Decimal] = Field(None, ge=0)
    hip_width: Optional[Decimal] = Field(None, ge=0)
    thigh_width: Optional[Decimal] = Field(None, ge=0)
    rise: Optional[Decimal] = Field(None, ge=0)
    hem_width: Optional[Decimal] = Field(None, ge=0)


class BodyMeasurementCreate(BodyMeasurementBase):
    """신체 치수 생성"""
    pass


class BodyMeasurementUpdate(BodyMeasurementBase):
    """신체 치수 수정"""
    pass


class BodyMeasurementResponse(BodyMeasurementBase):
    """신체 치수 응답"""
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Category Schemas
# ============================================

class CategoryBase(BaseModel):
    """카테고리 기본"""
    name: str = Field(..., min_length=1, max_length=100)
    parent_id: Optional[int] = None
    display_order: int = Field(default=0)
    is_active: bool = Field(default=True)


class CategoryCreate(CategoryBase):
    """카테고리 생성"""
    pass


class CategoryUpdate(BaseModel):
    """카테고리 수정"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    parent_id: Optional[int] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class CategoryResponse(CategoryBase):
    """카테고리 응답"""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryWithChildren(CategoryResponse):
    """하위 카테고리 포함"""
    children: List['CategoryWithChildren'] = []


# ============================================
# Product Schemas
# ============================================

class ProductBase(BaseModel):
    """신상품 기본"""
    category_id: int
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[str] = None
    price: Decimal = Field(..., gt=0, decimal_places=2)
    is_active: bool = Field(default=True)


class ProductCreate(ProductBase):
    """신상품 생성"""
    pass


class ProductUpdate(BaseModel):
    """신상품 수정"""
    category_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[str] = None
    price: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    """신상품 응답"""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# ProductOption Schemas
# ============================================

class ProductOptionBase(BaseModel):
    """상품 옵션 기본"""
    size_name: Optional[str] = Field(None, max_length=20)
    color: Optional[str] = Field(None, max_length=50)
    quantity: int = Field(default=0, ge=0)
    sku: Optional[str] = Field(None, max_length=100)
    is_active: bool = Field(default=True)


class ProductOptionCreate(ProductOptionBase):
    """상품 옵션 생성"""
    product_id: int


class ProductOptionUpdate(BaseModel):
    """상품 옵션 수정"""
    size_name: Optional[str] = Field(None, max_length=20)
    color: Optional[str] = Field(None, max_length=50)
    quantity: Optional[int] = Field(None, ge=0)
    sku: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class ProductOptionResponse(ProductOptionBase):
    """상품 옵션 응답"""
    id: int
    product_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductWithOptions(ProductResponse):
    """옵션 포함 상품"""
    options: List[ProductOptionResponse] = []


# ============================================
# UsedProduct Schemas
# ============================================

class UsedProductBase(BaseModel):
    """중고 상품 기본"""
    category_id: int
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[str] = None
    price: Decimal = Field(..., gt=0, decimal_places=2)
    condition_id: int


class UsedProductCreate(UsedProductBase):
    """중고 상품 생성"""
    pass


class UsedProductUpdate(BaseModel):
    """중고 상품 수정"""
    category_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[str] = None
    price: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    condition_id: Optional[int] = None
    status: Optional[UsedProductStatus] = None


class UsedProductResponse(UsedProductBase):
    """중고 상품 응답"""
    id: int
    seller_id: int
    status: UsedProductStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Cart Schemas
# ============================================

class CartItemBase(BaseModel):
    """장바구니 항목 기본"""
    product_option_type: ProductType
    product_option_id: int
    quantity: int = Field(..., gt=0)


class CartItemCreate(CartItemBase):
    """장바구니 항목 추가"""
    pass


class CartItemUpdate(BaseModel):
    """장바구니 항목 수정"""
    quantity: int = Field(..., gt=0)


class CartItemResponse(CartItemBase):
    """장바구니 항목 응답"""
    id: int
    cart_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CartResponse(BaseModel):
    """장바구니 응답"""
    id: int
    user_id: int
    items: List[CartItemResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# ShippingAddress Schemas
# ============================================

class ShippingAddressBase(BaseModel):
    """배송지 기본"""
    recipient_name: str = Field(..., min_length=1, max_length=100)
    address1: str = Field(..., min_length=1, max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    phone: str = Field(..., min_length=1, max_length=20)
    is_default: bool = Field(default=False)


class ShippingAddressCreate(ShippingAddressBase):
    """배송지 생성"""
    pass


class ShippingAddressUpdate(BaseModel):
    """배송지 수정"""
    recipient_name: Optional[str] = Field(None, min_length=1, max_length=100)
    address1: Optional[str] = Field(None, min_length=1, max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, min_length=1, max_length=20)
    is_default: Optional[bool] = None


class ShippingAddressResponse(ShippingAddressBase):
    """배송지 응답"""
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Order Schemas
# ============================================

class OrderItemBase(BaseModel):
    """주문 항목 기본"""
    product_option_type: ProductType
    product_option_id: int
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0, decimal_places=2)
    subtotal: Decimal = Field(..., ge=0, decimal_places=2)


class OrderItemCreate(BaseModel):
    """주문 항목 생성 (주문 시)"""
    product_option_type: ProductType
    product_option_id: int
    quantity: int = Field(..., gt=0)


class OrderItemResponse(OrderItemBase):
    """주문 항목 응답"""
    id: int
    order_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    """주문 생성"""
    shipping_address_id: int
    items: List[OrderItemCreate] = Field(..., min_length=1)
    payment_method: str = Field(..., min_length=1, max_length=50)
    points_used: Decimal = Field(default=Decimal('0.00'), ge=0)
    shipping_request: Optional[str] = None


class OrderUpdate(BaseModel):
    """주문 수정 (관리자용)"""
    status: Optional[OrderStatus] = None


class OrderResponse(BaseModel):
    """주문 응답"""
    id: int
    user_id: int
    order_number: str
    shipping_address_id: int
    subtotal: Decimal
    discount_amount: Decimal
    shipping_fee: Decimal
    total_amount: Decimal
    points_used: Decimal
    status: OrderStatus
    payment_method: str
    shipping_request: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderDetailResponse(OrderResponse):
    """주문 상세 (항목 포함)"""
    items: List[OrderItemResponse] = []


# ============================================
# Payment Schemas
# ============================================

class PaymentCreate(BaseModel):
    """결제 생성"""
    order_id: int
    payment_method: str = Field(..., min_length=1, max_length=50)
    payment_data: Optional[str] = None


class PaymentResponse(BaseModel):
    """결제 응답"""
    id: int
    order_id: int
    payment_method: str
    payment_status: PaymentStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Review Schemas
# ============================================

class ReviewBase(BaseModel):
    """리뷰 기본"""
    content: Optional[str] = None
    rating: int = Field(..., ge=1, le=5)


class ReviewCreate(ReviewBase):
    """리뷰 생성"""
    order_item_id: int


class ReviewUpdate(BaseModel):
    """리뷰 수정"""
    content: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)


class ReviewResponse(ReviewBase):
    """리뷰 응답"""
    id: int
    user_id: int
    order_item_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Point Schemas
# ============================================

class PointHistoryResponse(BaseModel):
    """포인트 내역 응답"""
    id: int
    user_id: int
    order_id: Optional[int]
    amount: Decimal
    balance_after: Decimal
    type: PointType
    description: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserPointBalance(BaseModel):
    """사용자 포인트 잔액"""
    user_id: int
    current_balance: Decimal
    history: List[PointHistoryResponse] = []


# ============================================
# Common Response Schemas
# ============================================

class PaginationParams(BaseModel):
    """페이지네이션 파라미터"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    """페이지네이션 응답"""
    items: List
    total: int
    page: int
    page_size: int
    total_pages: int


class MessageResponse(BaseModel):
    """메시지 응답"""
    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    """에러 응답"""
    error: str
    detail: Optional[str] = None
    field: Optional[str] = None