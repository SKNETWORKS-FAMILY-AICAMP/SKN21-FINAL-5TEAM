"""
Pydantic Schemas - User History Module
사용자 행동 히스토리 관련 스키마
"""
from datetime import datetime
from typing import Optional, List, Literal
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# Enums
# ============================================

class ActionType(str, Enum):
    """행동 유형"""
    # 인증 관련
    LOGIN = "login"
    LOGOUT = "logout"

    # 장바구니 관련
    CART_ADD = "cart_add"
    CART_DEL = "cart_del"

    # 주문 관련
    PAYMENT = "payment"  # 결제 완료
    ORDER_DEL = "order_del"

    # 환불 관련
    ORDER_RE = "order_re"

    # 리뷰 관련
    REVIEW_CREATE = "review_create"


# ============================================
# UserHistory Schemas
# ============================================

class UserHistoryBase(BaseModel):
    """히스토리 기본 스키마"""
    action_type: ActionType
    product_option_type: Optional[str] = Field(None, max_length=20)
    product_option_id: Optional[int] = None
    order_id: Optional[int] = None
    cart_item_id: Optional[int] = None
    action_metadata: Optional[str] = Field(None, description="JSON 형식 메타데이터")
    search_keyword: Optional[str] = Field(None, max_length=255)
    ip_address: Optional[str] = Field(None, max_length=45)
    user_agent: Optional[str] = None


class UserHistoryCreate(UserHistoryBase):
    """히스토리 생성 스키마"""
    pass


class UserHistoryResponse(UserHistoryBase):
    """히스토리 응답 스키마"""
    id: int
    user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# 추적용 Request 스키마
# ============================================

class TrackCartActionRequest(BaseModel):
    """장바구니 행동 추적 요청"""
    action_type: Literal["cart_add", "cart_del"]
    cart_item_id: int
    product_option_type: str
    product_option_id: int
    quantity: Optional[int] = None


class TrackAuthRequest(BaseModel):
    """인증 행동 추적 요청"""
    action_type: Literal["login", "logout"]


class TrackOrderRequest(BaseModel):
    """주문 행동 추적 요청"""
    order_id: int
    action_type: Literal["payment", "order_del"]


class TrackRefundRequest(BaseModel):
    """환불 요청 추적 요청"""
    order_id: int


class TrackReviewRequest(BaseModel):
    """리뷰 작성 추적 요청"""
    review_id: int
    product_option_type: str
    product_option_id: int


# ============================================
# 통계 스키마
# ============================================

class ActionStatistics(BaseModel):
    """행동 통계"""
    action_type: ActionType
    count: int
    last_action_at: Optional[datetime] = None


class UserActivitySummary(BaseModel):
    """사용자 활동 요약"""
    user_id: int
    total_actions: int
    actions_by_type: List[ActionStatistics]
    last_login_at: Optional[datetime] = None
