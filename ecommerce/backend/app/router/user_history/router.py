"""
FastAPI Router - User History Module
사용자 행동 히스토리 관련 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import logging

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.user_history import crud, schemas

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["user_history"]
)


# ==================== 히스토리 조회 ====================

@router.get("/users/{user_id}/history", response_model=List[schemas.UserHistoryResponse])
def get_user_history(
    user_id: int,
    action_type: Optional[schemas.ActionType] = Query(None, description="필터링할 행동 유형"),
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    사용자별 히스토리 조회

    Args:
        user_id: 사용자 ID
        action_type: 필터링할 행동 유형 (선택)
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션

    Returns:
        히스토리 목록
    """
    logger.info(f"Fetching history for user: {user_id}, action_type: {action_type}")

    if action_type:
        history = crud.get_history_by_action_type(db, user_id, action_type, skip, limit)
    else:
        history = crud.get_user_history(db, user_id, skip, limit)

    return history


@router.get("/users/{user_id}/summary", response_model=schemas.UserActivitySummary)
def get_user_activity_summary(
    user_id: int,
    days: int = Query(30, ge=1, le=365, description="조회 기간 (일)"),
    db: Session = Depends(get_db)
):
    """
    사용자 활동 요약 통계

    Args:
        user_id: 사용자 ID
        days: 조회 기간 (일)
        db: 데이터베이스 세션

    Returns:
        사용자 활동 요약
    """
    logger.info(f"Fetching activity summary for user: {user_id}, days: {days}")

    summary = crud.get_user_activity_summary(db, user_id, days)

    return summary


# ==================== 히스토리 기록 ====================

@router.post("/users/{user_id}/track/cart-action", response_model=schemas.UserHistoryResponse, status_code=status.HTTP_201_CREATED)
def track_cart_action(
    user_id: int,
    request: schemas.TrackCartActionRequest,
    db: Session = Depends(get_db)
):
    """
    장바구니 행동 기록

    Args:
        user_id: 사용자 ID
        request: 장바구니 행동 정보
        db: 데이터베이스 세션

    Returns:
        생성된 히스토리
    """
    logger.info(f"Tracking cart action for user: {user_id}, action: {request.action_type}")

    try:
        # action_type을 schemas.ActionType으로 변환
        action_type_enum = schemas.ActionType(request.action_type)

        metadata = None
        if request.quantity is not None:
            metadata = {"quantity": request.quantity}

        history = crud.track_cart_action(
            db,
            user_id=user_id,
            action_type=action_type_enum,
            cart_item_id=request.cart_item_id,
            product_option_type=request.product_option_type,
            product_option_id=request.product_option_id,
            metadata=metadata
        )
        return history
    except Exception as e:
        logger.error(f"Failed to track cart action: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/{user_id}/track/order", response_model=schemas.UserHistoryResponse, status_code=status.HTTP_201_CREATED)
def track_order_action(
    user_id: int,
    request: schemas.TrackOrderRequest,
    db: Session = Depends(get_db)
):
    """
    주문 행동 기록 (결제 완료, 주문 취소)

    Args:
        user_id: 사용자 ID
        request: 주문 행동 정보
        db: 데이터베이스 세션

    Returns:
        생성된 히스토리
    """
    logger.info(f"Tracking order action for user: {user_id}, action: {request.action_type}")

    try:
        # action_type을 schemas.ActionType으로 변환
        action_type_enum = schemas.ActionType(request.action_type)

        history = crud.track_order_action(
            db,
            user_id=user_id,
            order_id=request.order_id,
            action_type=action_type_enum
        )
        return history
    except Exception as e:
        logger.error(f"Failed to track order action: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/{user_id}/track/auth", response_model=schemas.UserHistoryResponse, status_code=status.HTTP_201_CREATED)
def track_auth_action(
    user_id: int,
    request: schemas.TrackAuthRequest,
    db: Session = Depends(get_db)
):
    """
    인증 행동 기록 (로그인/로그아웃)

    Args:
        user_id: 사용자 ID
        request: 인증 행동 정보
        db: 데이터베이스 세션

    Returns:
        생성된 히스토리
    """
    logger.info(f"Tracking auth action for user: {user_id}, action: {request.action_type}")

    try:
        # action_type을 schemas.ActionType으로 변환
        action_type_enum = schemas.ActionType(request.action_type)

        history = crud.track_auth_action(
            db,
            user_id=user_id,
            action_type=action_type_enum
        )
        return history
    except Exception as e:
        logger.error(f"Failed to track auth action: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/{user_id}/track/refund", response_model=schemas.UserHistoryResponse, status_code=status.HTTP_201_CREATED)
def track_refund_request(
    user_id: int,
    request: schemas.TrackRefundRequest,
    db: Session = Depends(get_db)
):
    """
    환불 요청 기록

    Args:
        user_id: 사용자 ID
        request: 환불 요청 정보
        db: 데이터베이스 세션

    Returns:
        생성된 히스토리
    """
    logger.info(f"Tracking refund request for user: {user_id}, order: {request.order_id}")

    try:
        history = crud.track_refund_request(
            db,
            user_id=user_id,
            order_id=request.order_id
        )
        return history
    except Exception as e:
        logger.error(f"Failed to track refund request: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/{user_id}/track/review", response_model=schemas.UserHistoryResponse, status_code=status.HTTP_201_CREATED)
def track_review_create(
    user_id: int,
    request: schemas.TrackReviewRequest,
    db: Session = Depends(get_db)
):
    """
    리뷰 작성 기록

    Args:
        user_id: 사용자 ID
        request: 리뷰 작성 정보
        db: 데이터베이스 세션

    Returns:
        생성된 히스토리
    """
    logger.info(f"Tracking review create for user: {user_id}, review: {request.review_id}")

    try:
        history = crud.track_review_create(
            db,
            user_id=user_id,
            review_id=request.review_id,
            product_option_type=request.product_option_type,
            product_option_id=request.product_option_id
        )
        return history
    except Exception as e:
        logger.error(f"Failed to track review create: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 관리자 기능 ====================

@router.delete("/admin/cleanup", status_code=status.HTTP_200_OK)
def cleanup_old_history(
    days: int = Query(180, ge=30, le=730, description="보관 기간 (일)"),
    db: Session = Depends(get_db)
):
    """
    오래된 히스토리 삭제 (관리자 기능)

    Args:
        days: 보관 기간 (일)
        db: 데이터베이스 세션

    Returns:
        삭제 결과
    """
    logger.info(f"Cleaning up history older than {days} days")

    try:
        deleted_count = crud.delete_old_history(db, days)
        logger.info(f"Deleted {deleted_count} old history records")

        return {
            "status": "success",
            "deleted_count": deleted_count,
            "message": f"{deleted_count}개의 오래된 히스토리가 삭제되었습니다"
        }
    except Exception as e:
        logger.error(f"Failed to cleanup history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/admin/users/{user_id}/anonymize", status_code=status.HTTP_200_OK)
def anonymize_user_history(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    사용자 히스토리 익명화 (관리자 기능, 탈퇴 시 사용)

    Args:
        user_id: 사용자 ID
        db: 데이터베이스 세션

    Returns:
        익명화 결과
    """
    logger.info(f"Anonymizing history for user: {user_id}")

    try:
        affected_count = crud.anonymize_user_history(db, user_id)
        logger.info(f"Anonymized {affected_count} history records for user: {user_id}")

        return {
            "status": "success",
            "affected_count": affected_count,
            "message": f"{affected_count}개의 히스토리가 익명화되었습니다"
        }
    except Exception as e:
        logger.error(f"Failed to anonymize history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ==================== 헬스 체크 ====================

@router.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    User History API 헬스 체크

    Returns:
        상태 정보
    """
    return {
        "status": "healthy",
        "service": "user_history"
    }
