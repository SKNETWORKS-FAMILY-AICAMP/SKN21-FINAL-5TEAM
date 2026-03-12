"""
Pydantic Schemas - Shipping Module
배송지 및 배송 관련 스키마
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ==================================================
# ShippingAddress Schemas
# ==================================================

class ShippingAddressBase(BaseModel):
    """배송지 기본 스키마"""
    recipient_name: str = Field(..., max_length=100, description="수령인 이름")
    address1: str = Field(..., max_length=255, description="주소1 (기본 주소)")
    address2: Optional[str] = Field(None, max_length=255, description="주소2 (상세 주소)")
    post_code: str = Field(..., max_length=10, description="우편번호")
    phone: str = Field(..., max_length=20, description="핸드폰번호")
    is_default: bool = Field(default=False, description="기본배송지 여부")


class ShippingAddressCreate(ShippingAddressBase):
    """배송지 생성 스키마"""
    pass


class ShippingAddressUpdate(BaseModel):
    """배송지 수정 스키마"""
    recipient_name: Optional[str] = Field(None, max_length=100)
    address1: Optional[str] = Field(None, max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    post_code: Optional[str] = Field(None, max_length=10)
    phone: Optional[str] = Field(None, max_length=20)
    is_default: Optional[bool] = None


class ShippingAddressResponse(ShippingAddressBase):
    """배송지 응답 스키마"""
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================================================
# ShippingRequestTemplate Schemas
# ==================================================

class ShippingRequestTemplateBase(BaseModel):
    """배송요청사항 템플릿 기본 스키마"""
    template_text: str = Field(..., description="배송요청사항 텍스트")
    display_order: int = Field(default=0, description="표시 순서")
    is_active: bool = Field(default=True, description="활성화 여부")


class ShippingRequestTemplateCreate(ShippingRequestTemplateBase):
    """배송요청사항 템플릿 생성 스키마"""
    pass


class ShippingRequestTemplateUpdate(BaseModel):
    """배송요청사항 템플릿 수정 스키마"""
    template_text: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class ShippingRequestTemplateResponse(ShippingRequestTemplateBase):
    """배송요청사항 템플릿 응답 스키마"""
    id: int

    model_config = ConfigDict(from_attributes=True)


# ==================================================
# ShippingInfo Schemas
# ==================================================

class ShippingInfoBase(BaseModel):
    """배송 정보 기본 스키마"""
    courier_company: Optional[str] = Field(None, max_length=100, description="택배사")
    tracking_number: Optional[str] = Field(None, max_length=100, description="송장 번호")
    shipped_at: Optional[datetime] = Field(None, description="배송 시작 일시")
    delivered_at: Optional[datetime] = Field(None, description="배송 완료 일시")


class ShippingInfoCreate(ShippingInfoBase):
    """배송 정보 생성 스키마"""
    order_id: int = Field(..., description="주문 ID")


class ShippingInfoUpdate(BaseModel):
    """배송 정보 수정 스키마"""
    courier_company: Optional[str] = Field(None, max_length=100)
    tracking_number: Optional[str] = Field(None, max_length=100)
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None


class ShippingInfoResponse(ShippingInfoBase):
    """배송 정보 응답 스키마"""
    id: int
    order_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)