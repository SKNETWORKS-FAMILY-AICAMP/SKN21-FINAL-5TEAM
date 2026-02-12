"""
Pydantic Schemas - Inventory Module
재고 거래 내역 관련 스키마
"""
from datetime import datetime
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# Enums
# ============================================

class ProductType(str, Enum):
    """상품 유형"""
    NEW = "new"
    USED = "used"


class TransactionType(str, Enum):
    """재고 거래 유형"""
    PURCHASE = "purchase"  # 입고
    SALE = "sale"  # 판매
    RETURN = "return"  # 반품
    ADJUSTMENT = "adjustment"  # 조정


# ============================================
# InventoryTransaction Schemas
# ============================================

class InventoryTransactionBase(BaseModel):
    """재고 거래 내역 기본 스키마"""
    product_option_type: ProductType = Field(..., description="상품 유형")
    product_option_id: int = Field(..., description="상품 옵션 ID")
    quantity_change: int = Field(..., description="수량 변동 (양수: 입고, 음수: 출고)")
    transaction_type: TransactionType = Field(..., description="거래 유형")
    reference_id: Optional[int] = Field(None, description="Order ID 등 참조 ID")
    notes: Optional[str] = Field(None, description="비고")


class InventoryTransactionCreate(InventoryTransactionBase):
    """재고 거래 내역 생성 스키마"""
    pass


class InventoryTransactionResponse(InventoryTransactionBase):
    """재고 거래 내역 응답 스키마"""
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Request Schemas
# ============================================

class AddInventoryRequest(BaseModel):
    """재고 입고 요청"""
    product_option_type: ProductType
    product_option_id: int
    quantity: int = Field(..., gt=0, description="입고 수량")
    notes: Optional[str] = Field(None, description="비고")


class RemoveInventoryRequest(BaseModel):
    """재고 출고 요청"""
    product_option_type: ProductType
    product_option_id: int
    quantity: int = Field(..., gt=0, description="출고 수량")
    order_id: Optional[int] = Field(None, description="주문 ID")
    notes: Optional[str] = Field(None, description="비고")


class AdjustInventoryRequest(BaseModel):
    """재고 조정 요청"""
    product_option_type: ProductType
    product_option_id: int
    quantity_change: int = Field(..., description="조정 수량 (양수/음수)")
    notes: Optional[str] = Field(None, description="조정 사유")


# ============================================
# Inventory Stats
# ============================================

class InventoryStats(BaseModel):
    """재고 통계"""
    product_option_type: ProductType
    product_option_id: int
    current_stock: int = Field(description="현재 재고")
    total_purchased: int = Field(description="총 입고량")
    total_sold: int = Field(description="총 판매량")
    total_returned: int = Field(description="총 반품량")
    total_adjusted: int = Field(description="총 조정량")
