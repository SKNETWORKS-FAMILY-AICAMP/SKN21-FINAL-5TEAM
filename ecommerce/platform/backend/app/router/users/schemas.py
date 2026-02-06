from pydantic import BaseModel, EmailStr
from typing import Optional


# ===== Request Schemas =====

class CheckEmailRequest(BaseModel):
    email: EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    phone: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ===== Response Schemas =====

class CheckEmailResponse(BaseModel):
    available: bool


class LoginResponse(BaseModel):
    id: int
    email: EmailStr
    name: str
