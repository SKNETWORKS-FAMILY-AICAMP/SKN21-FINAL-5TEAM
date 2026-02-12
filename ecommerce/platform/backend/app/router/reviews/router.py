"""
FastAPI Router - Reviews Module
리뷰 관련 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, Path
from sqlalchemy.orm import Session
from typing import List
import logging

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.reviews import crud, schemas

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"]
)


# ==================== 리뷰 조회 ====================

@router.get("/{review_id}", response_model=schemas.ReviewResponse)
def get_review(
    review_id: int,
    db: Session = Depends(get_db)
):
    """
    리뷰 ID로 조회
    
    Args:
        review_id: 리뷰 ID
        db: 데이터베이스 세션
    
    Returns:
        리뷰 정보
    """
    logger.info(f"Fetching review: {review_id}")
    
    review = crud.get_review_by_id(db, review_id)
    
    if not review:
        logger.warning(f"Review not found: {review_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="리뷰를 찾을 수 없습니다"
        )
    
    return review


@router.get("/users/{user_id}/reviews", response_model=List[schemas.ReviewResponse])
def get_user_reviews(
    user_id: int,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    사용자별 리뷰 목록 조회
    
    Args:
        user_id: 사용자 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        리뷰 목록
    """
    logger.info(f"Fetching reviews for user: {user_id}")
    
    reviews = crud.get_reviews_by_user_id(db, user_id, skip, limit)
    
    return reviews


@router.get("/products/{product_option_type}/{product_option_id}/reviews", response_model=List[schemas.ReviewResponse])
def get_product_reviews(
    product_option_type: str,
    product_option_id: int,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    상품별 리뷰 목록 조회
    
    Args:
        product_option_type: 상품 유형 (new/used)
        product_option_id: 상품 옵션 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        리뷰 목록
    """
    logger.info(f"Fetching reviews for product: {product_option_type}/{product_option_id}")
    
    reviews = crud.get_reviews_by_product_option(
        db, product_option_type, product_option_id, skip, limit
    )
    
    return reviews


@router.get("/rating/{rating}/reviews", response_model=List[schemas.ReviewResponse])
def get_reviews_by_rating(
    rating: int = Path(..., ge=1, le=5, description="평점 (1-5)"),
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    평점별 리뷰 조회
    
    Args:
        rating: 평점 (1-5)
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        리뷰 목록
    """
    logger.info(f"Fetching reviews with rating: {rating}")
    
    reviews = crud.get_reviews_by_rating(db, rating, skip, limit)
    
    return reviews


# ==================== 리뷰 생성 ====================

@router.post("", response_model=schemas.ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_review(
    user_id: int = Query(..., description="사용자 ID"),
    review_data: schemas.ReviewCreate = Body(...),
    db: Session = Depends(get_db)
):
    """
    새 리뷰 작성
    
    Args:
        user_id: 사용자 ID
        review_data: 리뷰 생성 데이터
        db: 데이터베이스 세션
    
    Returns:
        생성된 리뷰 정보
    """
    logger.info(f"Creating review for user: {user_id}, order_item: {review_data.order_item_id}")
    
    # 리뷰 작성 가능 여부 확인
    if not crud.can_write_review(db, user_id, review_data.order_item_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="리뷰를 작성할 수 없습니다"
        )
    
    try:
        review = crud.create_review(db, user_id, review_data)
        logger.info(f"Created review: {review.id}")
        return review
    except ValueError as e:
        logger.error(f"Failed to create review: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 리뷰 수정 ====================

@router.put("/{review_id}", response_model=schemas.ReviewResponse)
def update_review(
    review_id: int,
    user_id: int = Query(..., description="사용자 ID"),
    review_update: schemas.ReviewUpdate = Body(...),
    db: Session = Depends(get_db)
):
    """
    리뷰 수정
    
    Args:
        review_id: 리뷰 ID
        user_id: 사용자 ID
        review_update: 수정할 리뷰 정보
        db: 데이터베이스 세션
    
    Returns:
        수정된 리뷰 정보
    """
    logger.info(f"Updating review: {review_id}")
    
    # 소유권 확인
    if not crud.verify_review_ownership(db, review_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인의 리뷰만 수정할 수 있습니다"
        )
    
    review = crud.update_review(db, review_id, review_update)
    
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="리뷰를 찾을 수 없습니다"
        )
    
    logger.info(f"Review updated: {review_id}")
    return review


# ==================== 리뷰 삭제 ====================

@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(
    review_id: int,
    user_id: int = Query(..., description="사용자 ID"),
    db: Session = Depends(get_db)
):
    """
    리뷰 삭제
    
    Args:
        review_id: 리뷰 ID
        user_id: 사용자 ID
        db: 데이터베이스 세션
    
    Returns:
        None
    """
    logger.info(f"Deleting review: {review_id}")
    
    # 소유권 확인
    if not crud.verify_review_ownership(db, review_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인의 리뷰만 삭제할 수 있습니다"
        )
    
    success = crud.delete_review(db, review_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="리뷰를 찾을 수 없습니다"
        )
    
    logger.info(f"Review deleted: {review_id}")
    return None


# ==================== 리뷰 통계 ====================

@router.get("/products/{product_option_type}/{product_option_id}/stats", response_model=schemas.ReviewStats)
def get_product_review_stats(
    product_option_type: str,
    product_option_id: int,
    db: Session = Depends(get_db)
):
    """
    상품별 리뷰 통계
    
    Args:
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        db: 데이터베이스 세션
    
    Returns:
        리뷰 통계
    """
    logger.info(f"Fetching review stats for product: {product_option_type}/{product_option_id}")
    
    stats = crud.get_review_stats_by_product_option(
        db, product_option_type, product_option_id
    )
    
    return stats


@router.get("/users/{user_id}/stats")
def get_user_review_stats(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    사용자별 리뷰 통계
    
    Args:
        user_id: 사용자 ID
        db: 데이터베이스 세션
    
    Returns:
        사용자 리뷰 통계
    """
    logger.info(f"Fetching review stats for user: {user_id}")
    
    stats = crud.get_review_stats_by_user(db, user_id)
    
    return stats


# ==================== 검증 엔드포인트 ====================

@router.get("/order-items/{order_item_id}/can-write")
def check_can_write_review(
    order_item_id: int,
    user_id: int = Query(..., description="사용자 ID"),
    db: Session = Depends(get_db)
):
    """
    리뷰 작성 가능 여부 확인
    
    Args:
        order_item_id: 주문 항목 ID
        user_id: 사용자 ID
        db: 데이터베이스 세션
    
    Returns:
        작성 가능 여부
    """
    can_write = crud.can_write_review(db, user_id, order_item_id)
    
    return {
        "order_item_id": order_item_id,
        "user_id": user_id,
        "can_write": can_write
    }


# ==================== 헬스 체크 ====================

@router.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    리뷰 API 헬스 체크
    
    Returns:
        상태 정보
    """
    return {
        "status": "healthy",
        "service": "reviews"
    }