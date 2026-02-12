"""
Pydantic Schemas - Reviews Module
리뷰 관련 스키마
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# Review Schemas
# ============================================

class ReviewBase(BaseModel):
    """리뷰 기본 스키마"""
    rating: int = Field(..., ge=1, le=5, description="평점 (1-5)")
    content: Optional[str] = Field(None, description="리뷰 내용")


class ReviewCreate(ReviewBase):
    """리뷰 생성 스키마"""
    order_item_id: int = Field(..., description="주문 항목 ID")


class ReviewUpdate(BaseModel):
    """리뷰 수정 스키마"""
    rating: Optional[int] = Field(None, ge=1, le=5, description="평점 (1-5)")
    content: Optional[str] = Field(None, description="리뷰 내용")


class ReviewResponse(BaseModel):
    """리뷰 응답 스키마"""
    id: int
    user_id: int
    order_item_id: int
    rating: int
    content: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewWithUserInfo(ReviewResponse):
    """사용자 정보가 포함된 리뷰 응답"""
    user_name: Optional[str] = Field(None, description="작성자 이름")
    user_email: Optional[str] = Field(None, description="작성자 이메일")


class ReviewStats(BaseModel):
    """리뷰 통계"""
    total_reviews: int = Field(description="총 리뷰 수")
    average_rating: float = Field(description="평균 평점")
    rating_distribution: dict = Field(description="평점 분포 (1-5점)")
