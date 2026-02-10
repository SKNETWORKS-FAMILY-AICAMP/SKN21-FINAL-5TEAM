"""
Pydantic Schemas - Orders Module
주문 관련 스키마
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_validator


# ==================================================
# Enums
# ==================================================

class OrderStatus(str, Enum):
    """주문 상태"""
    PENDING = "pending"              # 결제 대기
    PAYMENT_COMPLETED = "payment_completed"  # 결제 완료
    PREPARING = "preparing"          # 상품 준비중
    SHIPPED = "shipped"              # 배송중
    DELIVERED = "delivered"          # 배송 완료
    CANCELLED = "cancelled"          # 주문 취소
    REFUNDED = "refunded"            # 환불 완료


class ProductType(str, Enum):
    """상품 유형"""
    NEW = "new"
    USED = "used"


# ==================================================
# OrderItem Schemas
# ==================================================

class OrderItemBase(BaseModel):
    """주문 항목 기본 스키마"""
    product_option_type: ProductType = Field(..., description="옵션 유형 (신상품/중고상품)")
    product_option_id: int = Field(..., description="품목 옵션 ID")
    quantity: int = Field(..., gt=0, description="수량")
    unit_price: Decimal = Field(..., ge=0, description="단가")

    @field_validator('unit_price')
    @classmethod
    def validate_price(cls, v):
        if v < 0:
            raise ValueError('단가는 0 이상이어야 합니다')
        return v


class OrderItemCreate(OrderItemBase):
    """주문 항목 생성 스키마"""
    pass


class OrderItemResponse(OrderItemBase):
    """주문 항목 응답 스키마"""
    id: int
    order_id: int
    subtotal: Decimal
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================================================
# Order Schemas
# ==================================================

class OrderBase(BaseModel):
    """주문 기본 스키마"""
    shipping_address_id: int = Field(..., description="배송지 ID")
    payment_method: str = Field(..., max_length=50, description="결제 수단")
    shipping_request: Optional[str] = Field(None, description="배송요청 사항")
    points_used: Decimal = Field(default=Decimal('0'), ge=0, description="사용한 포인트")

    @field_validator('points_used')
    @classmethod
    def validate_points(cls, v):
        if v < 0:
            raise ValueError('포인트는 0 이상이어야 합니다')
        return v


class OrderCreate(OrderBase):
    """주문 생성 스키마"""
    items: List[OrderItemCreate] = Field(..., min_length=1, description="주문 항목 리스트")


class OrderUpdate(BaseModel):
    """주문 수정 스키마"""
    shipping_address_id: Optional[int] = None
    status: Optional[OrderStatus] = None
    shipping_request: Optional[str] = None


class OrderResponse(OrderBase):
    """주문 응답 스키마"""
    id: int
    user_id: int
    order_number: str
    subtotal: Decimal
    discount_amount: Decimal
    shipping_fee: Decimal
    total_amount: Decimal
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class OrderDetailResponse(OrderResponse):
    """주문 상세 응답 스키마 (결제 및 배송 정보 포함)"""
    from ecommerce.platform.backend.app.router.payments.schemas import PaymentResponse
    from ecommerce.platform.backend.app.router.shipping.schemas import ShippingInfoResponse
    
    payment: Optional[PaymentResponse] = None
    shipping_info: Optional[ShippingInfoResponse] = None


class OrderListResponse(BaseModel):
    """주문 목록 응답 스키마"""
    orders: List[OrderResponse]
    total: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    """주문 상태 업데이트 스키마"""
    status: OrderStatus = Field(..., description="변경할 주문 상태")


class OrderSummary(BaseModel):
    """주문 요약 스키마"""
    id: int
    order_number: str
    total_amount: Decimal
    status: OrderStatus
    created_at: datetime
    item_count: int = Field(..., description="주문 항목 개수")

    model_config = ConfigDict(from_attributes=True)