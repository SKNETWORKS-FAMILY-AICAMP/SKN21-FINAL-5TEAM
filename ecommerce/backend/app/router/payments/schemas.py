"""
Pydantic Schemas - Payments Module
결제 관련 스키마
"""
from datetime import datetime
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# ==================================================
# Enums
# ==================================================

class PaymentStatus(str, Enum):
    """결제 상태"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ==================================================
# Payment Schemas
# ==================================================

class PaymentBase(BaseModel):
    """결제 기본 스키마"""
    payment_method: str = Field(..., max_length=50, description="결제 수단 (카드, 계좌이체 등)")
    payment_data: Optional[str] = Field(None, description="결제 수단에 관한 데이터 (JSON)")
    card_numbers: Optional[str] = Field(None, max_length=50, description="카드번호 (마스킹 처리)")


class PaymentCreate(PaymentBase):
    """결제 생성 스키마"""
    order_id: int = Field(..., description="주문 ID")
    payment_status: PaymentStatus = Field(default=PaymentStatus.PENDING, description="결제 상태")


class PaymentUpdate(BaseModel):
    """결제 수정 스키마"""
    payment_method: Optional[str] = Field(None, max_length=50)
    payment_data: Optional[str] = None
    payment_status: Optional[PaymentStatus] = None
    card_numbers: Optional[str] = Field(None, max_length=50)


class PaymentResponse(PaymentBase):
    """결제 응답 스키마"""
    id: int
    order_id: int
    payment_status: PaymentStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentStatusUpdate(BaseModel):
    """결제 상태 업데이트 스키마"""
    payment_status: PaymentStatus = Field(..., description="변경할 결제 상태")