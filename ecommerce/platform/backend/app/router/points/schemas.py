"""
Pydantic Schemas - Points Module
포인트 및 상품권 관련 스키마
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# Enums
# ============================================

class PointType(str, Enum):
    """포인트 유형"""
    EARN = "earn"
    USE = "use"
    EXPIRE = "expire"
    REFUND = "refund"


# ============================================
# PointHistory Schemas
# ============================================

class PointHistoryBase(BaseModel):
    """포인트 내역 기본 스키마"""
    amount: Decimal = Field(..., description="변동 포인트 금액")
    type: PointType = Field(..., description="포인트 유형")
    description: Optional[str] = Field(None, description="포인트 변동 설명")


class PointHistoryCreate(PointHistoryBase):
    """포인트 내역 생성 스키마"""
    order_id: Optional[int] = Field(None, description="주문 ID")


class PointHistoryResponse(PointHistoryBase):
    """포인트 내역 응답 스키마"""
    id: int
    user_id: int
    order_id: Optional[int]
    balance_after: Decimal = Field(description="변동 후 잔액")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PointBalance(BaseModel):
    """포인트 잔액"""
    user_id: int
    current_balance: Decimal = Field(description="현재 포인트 잔액")
    total_earned: Decimal = Field(description="총 적립 포인트")
    total_used: Decimal = Field(description="총 사용 포인트")


# ============================================
# IssuedVoucher Schemas
# ============================================

class IssuedVoucherBase(BaseModel):
    """발급된 상품권 기본 스키마"""
    voucher_code: str = Field(..., max_length=100, description="상품권 코드")
    amount: Decimal = Field(..., gt=0, description="상품권 금액")


class IssuedVoucherCreate(IssuedVoucherBase):
    """발급된 상품권 생성 스키마"""
    pass


class IssuedVoucherUpdate(BaseModel):
    """발급된 상품권 수정 스키마"""
    is_used: Optional[bool] = Field(None, description="사용 여부")


class IssuedVoucherResponse(IssuedVoucherBase):
    """발급된 상품권 응답 스키마"""
    id: int
    user_id: int
    is_used: bool
    used_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VoucherUseRequest(BaseModel):
    """상품권 사용 요청"""
    voucher_code: str = Field(..., description="사용할 상품권 코드")


# ============================================
# Transaction Schemas
# ============================================

class EarnPointsRequest(BaseModel):
    """포인트 적립 요청"""
    amount: Decimal = Field(..., gt=0, description="적립할 포인트")
    description: Optional[str] = Field(None, description="적립 사유")
    order_id: Optional[int] = Field(None, description="관련 주문 ID")


class UsePointsRequest(BaseModel):
    """포인트 사용 요청"""
    amount: Decimal = Field(..., gt=0, description="사용할 포인트")
    description: Optional[str] = Field(None, description="사용 사유")
    order_id: Optional[int] = Field(None, description="관련 주문 ID")


class RefundPointsRequest(BaseModel):
    """포인트 환불 요청"""
    amount: Decimal = Field(..., gt=0, description="환불할 포인트")
    description: Optional[str] = Field(None, description="환불 사유")
    order_id: Optional[int] = Field(None, description="관련 주문 ID")
