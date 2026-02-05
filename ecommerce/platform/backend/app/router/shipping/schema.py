from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime

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