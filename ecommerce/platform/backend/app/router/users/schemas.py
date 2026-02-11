from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# =========================
# Auth / Basic
# =========================

class CheckEmailRequest(BaseModel):
    email: EmailStr


class CheckEmailResponse(BaseModel):
    available: bool


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=100)
    phone: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None

    # 약관/알림(회원가입 때 선택)
    agree_marketing_info: bool = False
    agree_ad_sms: bool = False
    agree_ad_email: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    id: int
    email: EmailStr
    name: str

class WithdrawRequest(BaseModel):
    reason: str

# =========================
# Profile (회원정보 변경/조회)
# =========================

class MeResponse(BaseModel):
    id: int
    email: EmailStr
    name: str
    phone: Optional[str] = None

    agree_marketing: bool = False
    agree_sms: bool = False
    agree_email: bool = False

    address1: Optional[str] = None
    address2: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserProfileUpdateRequest(BaseModel):
    # 부분 업데이트 허용 (안 보낸 값은 유지)
    email: Optional[EmailStr] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)


class UserProfileUpdateResponse(BaseModel):
    ok: bool
    user: MeResponse


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1)


class SimpleOkResponse(BaseModel):
    ok: bool


# =========================
# Notification (알림설정 토글)
# - users 테이블의 agree_* 컬럼을 그대로 사용
# =========================

class NotificationSettingResponse(BaseModel):
    agree_marketing: bool = False
    agree_sms: bool = False
    agree_email: bool = False


class NotificationSettingUpdateRequest(BaseModel):
    # 부분 업데이트 허용
    agree_marketing: Optional[bool] = None
    agree_sms: Optional[bool] = None
    agree_email: Optional[bool] = None


# =========================
# Body Measurement (나의 맞춤정보)
# - UserBodyMeasurements 1:1
# =========================

class BodyMeasurementBase(BaseModel):
    # 기본(키/몸무게)
    height: Optional[Decimal] = Field(None, ge=0, le=300)
    weight: Optional[Decimal] = Field(None, ge=0, le=500)

    # 상의
    upper_total_length: Optional[Decimal] = Field(None, ge=0)
    shoulder_width: Optional[Decimal] = Field(None, ge=0)
    chest_width: Optional[Decimal] = Field(None, ge=0)
    sleeve_length: Optional[Decimal] = Field(None, ge=0)

    # 하의
    lower_total_length: Optional[Decimal] = Field(None, ge=0)
    waist_width: Optional[Decimal] = Field(None, ge=0)
    hip_width: Optional[Decimal] = Field(None, ge=0)
    thigh_width: Optional[Decimal] = Field(None, ge=0)
    rise: Optional[Decimal] = Field(None, ge=0)
    hem_width: Optional[Decimal] = Field(None, ge=0)


class BodyMeasurementUpsertRequest(BodyMeasurementBase):
    pass


class BodyMeasurementResponse(BodyMeasurementBase):
    id: int
    user_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True
    }


class BodyMeasurementUpsertResponse(BaseModel):
    ok: bool
    measurement: BodyMeasurementResponse
# =========================