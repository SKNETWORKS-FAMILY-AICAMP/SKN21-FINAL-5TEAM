"""
Pydantic Schemas for Cart
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict

# Product 모듈의 ProductType enum 사용
from ecommerce.platform.backend.app.router.products.models import ProductType, UsedProductStatus


# ============================================
# Cart Item Schemas
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


# ============================================
# Cart Schemas
# ============================================

class CartResponse(BaseModel):
    """장바구니 응답"""
    id: int
    user_id: int
    items: List[CartItemResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Request Schemas (API 입력용)
# ============================================

class AddToCartRequest(BaseModel):
    """장바구니 추가 요청"""
    product_option_type: ProductType
    product_option_id: int
    quantity: int = Field(default=1, gt=0)


class UpdateCartItemRequest(BaseModel):
    """장바구니 항목 수정 요청"""
    quantity: int = Field(..., gt=0)


class RemoveFromCartRequest(BaseModel):
    """장바구니 항목 일괄 삭제 요청"""
    item_ids: List[int] = Field(..., min_length=1)


# ============================================
# Product Info Schemas (Frontend용 상품 정보)
# ============================================

class ProductOptionInfo(BaseModel):
    """상품 옵션 정보"""
    size: Optional[str] = None
    color: Optional[str] = None
    condition: Optional[str] = None  # 중고상품의 경우


class ProductInfo(BaseModel):
    """상품 상세 정보 (Frontend 표시용)"""
    id: int
    name: str
    brand: str
    price: Decimal
    original_price: Optional[Decimal] = None
    stock: int
    shipping_fee: Decimal
    shipping_text: str
    is_used: bool
    image: str
    option: ProductOptionInfo


class CartItemDetailResponse(BaseModel):
    """장바구니 항목 상세 응답 (상품 정보 포함)"""
    id: int
    cart_id: int
    quantity: int
    product_option_type: ProductType
    product_option_id: int
    created_at: datetime
    updated_at: datetime
    product: ProductInfo

    model_config = ConfigDict(from_attributes=True)


class CartDetailResponse(BaseModel):
    """장바구니 상세 응답"""
    id: int
    user_id: int
    items: List[CartItemDetailResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Summary Schemas
# ============================================

class CartSummary(BaseModel):
    """장바구니 요약 정보"""
    total_items: int = Field(description="총 상품 종류 수")
    total_quantity: int = Field(description="총 상품 수량")
    total_price: Decimal = Field(description="총 상품 금액")
    total_shipping_fee: Decimal = Field(description="총 배송비")
    final_total: Decimal = Field(description="최종 결제 금액")


class CartDetailWithSummary(BaseModel):
    """장바구니 상세 + 요약 정보"""
    cart: CartDetailResponse
    summary: CartSummary
