"""
FastAPI Router - Points Module
포인트 및 상품권 관련 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
import logging

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.points import crud, schemas

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["points"]
)


# ==================== 포인트 내역 조회 ====================

@router.get("/users/{user_id}/history", response_model=List[schemas.PointHistoryResponse])
def get_point_history(
    user_id: int,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    사용자별 포인트 내역 조회
    
    Args:
        user_id: 사용자 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        포인트 내역 목록
    """
    logger.info(f"Fetching point history for user: {user_id}")
    
    history = crud.get_point_history_by_user(db, user_id, skip, limit)
    
    return history


@router.get("/users/{user_id}/history/type/{point_type}", response_model=List[schemas.PointHistoryResponse])
def get_point_history_by_type(
    user_id: int,
    point_type: schemas.PointType,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    포인트 유형별 내역 조회
    
    Args:
        user_id: 사용자 ID
        point_type: 포인트 유형
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        포인트 내역 목록
    """
    logger.info(f"Fetching {point_type} point history for user: {user_id}")
    
    history = crud.get_point_history_by_type(db, user_id, point_type, skip, limit)
    
    return history


@router.get("/users/{user_id}/balance", response_model=schemas.PointBalance)
def get_point_balance(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    현재 포인트 잔액 및 통계 조회
    
    Args:
        user_id: 사용자 ID
        db: 데이터베이스 세션
    
    Returns:
        포인트 잔액 및 통계
    """
    logger.info(f"Fetching point balance for user: {user_id}")
    
    balance = crud.get_point_statistics(db, user_id)
    
    return balance


# ==================== 포인트 거래 ====================

@router.post("/users/{user_id}/earn", response_model=schemas.PointHistoryResponse, status_code=status.HTTP_201_CREATED)
def earn_points(
    user_id: int,
    request: schemas.EarnPointsRequest,
    db: Session = Depends(get_db)
):
    """
    포인트 적립
    
    Args:
        user_id: 사용자 ID
        request: 적립 요청 데이터
        db: 데이터베이스 세션
    
    Returns:
        생성된 포인트 내역
    """
    logger.info(f"Earning {request.amount} points for user: {user_id}")
    
    try:
        history = crud.earn_points(
            db,
            user_id=user_id,
            amount=request.amount,
            description=request.description,
            order_id=request.order_id
        )
        logger.info(f"Points earned: {history.id}")
        return history
    except ValueError as e:
        logger.error(f"Failed to earn points: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/{user_id}/use", response_model=schemas.PointHistoryResponse, status_code=status.HTTP_201_CREATED)
def use_points(
    user_id: int,
    request: schemas.UsePointsRequest,
    db: Session = Depends(get_db)
):
    """
    포인트 사용
    
    Args:
        user_id: 사용자 ID
        request: 사용 요청 데이터
        db: 데이터베이스 세션
    
    Returns:
        생성된 포인트 내역
    """
    logger.info(f"Using {request.amount} points for user: {user_id}")
    
    try:
        history = crud.use_points(
            db,
            user_id=user_id,
            amount=request.amount,
            description=request.description,
            order_id=request.order_id
        )
        logger.info(f"Points used: {history.id}")
        return history
    except ValueError as e:
        logger.error(f"Failed to use points: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/{user_id}/refund", response_model=schemas.PointHistoryResponse, status_code=status.HTTP_201_CREATED)
def refund_points(
    user_id: int,
    request: schemas.RefundPointsRequest,
    db: Session = Depends(get_db)
):
    """
    포인트 환불
    
    Args:
        user_id: 사용자 ID
        request: 환불 요청 데이터
        db: 데이터베이스 세션
    
    Returns:
        생성된 포인트 내역
    """
    logger.info(f"Refunding {request.amount} points for user: {user_id}")
    
    try:
        history = crud.refund_points(
            db,
            user_id=user_id,
            amount=request.amount,
            description=request.description,
            order_id=request.order_id
        )
        logger.info(f"Points refunded: {history.id}")
        return history
    except ValueError as e:
        logger.error(f"Failed to refund points: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 상품권 조회 ====================

@router.get("/vouchers/{voucher_id}", response_model=schemas.IssuedVoucherResponse)
def get_voucher(
    voucher_id: int,
    db: Session = Depends(get_db)
):
    """
    상품권 ID로 조회
    
    Args:
        voucher_id: 상품권 ID
        db: 데이터베이스 세션
    
    Returns:
        상품권 정보
    """
    logger.info(f"Fetching voucher: {voucher_id}")
    
    voucher = crud.get_voucher_by_id(db, voucher_id)
    
    if not voucher:
        logger.warning(f"Voucher not found: {voucher_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="상품권을 찾을 수 없습니다"
        )
    
    return voucher


@router.get("/vouchers/code/{voucher_code}", response_model=schemas.IssuedVoucherResponse)
def get_voucher_by_code(
    voucher_code: str,
    db: Session = Depends(get_db)
):
    """
    상품권 코드로 조회
    
    Args:
        voucher_code: 상품권 코드
        db: 데이터베이스 세션
    
    Returns:
        상품권 정보
    """
    logger.info(f"Fetching voucher by code: {voucher_code}")
    
    voucher = crud.get_voucher_by_code(db, voucher_code)
    
    if not voucher:
        logger.warning(f"Voucher not found: {voucher_code}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="상품권을 찾을 수 없습니다"
        )
    
    return voucher


@router.get("/users/{user_id}/vouchers", response_model=List[schemas.IssuedVoucherResponse])
def get_user_vouchers(
    user_id: int,
    include_used: bool = Query(False, description="사용된 상품권 포함 여부"),
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    사용자별 상품권 목록 조회
    
    Args:
        user_id: 사용자 ID
        include_used: 사용된 상품권 포함 여부
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        상품권 목록
    """
    logger.info(f"Fetching vouchers for user: {user_id}")
    
    vouchers = crud.get_vouchers_by_user(db, user_id, include_used, skip, limit)
    
    return vouchers


# ==================== 상품권 발급 및 사용 ====================

@router.post("/users/{user_id}/vouchers", response_model=schemas.IssuedVoucherResponse, status_code=status.HTTP_201_CREATED)
def issue_voucher(
    user_id: int,
    voucher_data: schemas.IssuedVoucherCreate,
    db: Session = Depends(get_db)
):
    """
    상품권 발급
    
    Args:
        user_id: 사용자 ID
        voucher_data: 상품권 데이터
        db: 데이터베이스 세션
    
    Returns:
        발급된 상품권 정보
    """
    logger.info(f"Issuing voucher for user: {user_id}")
    
    try:
        voucher = crud.create_voucher(db, user_id, voucher_data)
        logger.info(f"Voucher issued: {voucher.id}")
        return voucher
    except ValueError as e:
        logger.error(f"Failed to issue voucher: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/{user_id}/vouchers/use", response_model=schemas.IssuedVoucherResponse)
def use_voucher(
    user_id: int,
    request: schemas.VoucherUseRequest,
    db: Session = Depends(get_db)
):
    """
    상품권 사용
    
    Args:
        user_id: 사용자 ID
        request: 상품권 사용 요청
        db: 데이터베이스 세션
    
    Returns:
        사용 처리된 상품권 정보
    """
    logger.info(f"Using voucher {request.voucher_code} for user: {user_id}")
    
    try:
        voucher = crud.use_voucher(db, request.voucher_code, user_id)
        logger.info(f"Voucher used: {voucher.id}")
        return voucher
    except ValueError as e:
        logger.error(f"Failed to use voucher: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 상품권 삭제 ====================

@router.delete("/vouchers/{voucher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voucher(
    voucher_id: int,
    db: Session = Depends(get_db)
):
    """
    상품권 삭제
    
    Args:
        voucher_id: 상품권 ID
        db: 데이터베이스 세션
    
    Returns:
        None
    """
    logger.info(f"Deleting voucher: {voucher_id}")
    
    success = crud.delete_voucher(db, voucher_id)
    
    if not success:
        logger.warning(f"Voucher not found for deletion: {voucher_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="상품권을 찾을 수 없습니다"
        )
    
    logger.info(f"Voucher deleted: {voucher_id}")
    return None


# ==================== 헬스 체크 ====================

@router.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    포인트 API 헬스 체크
    
    Returns:
        상태 정보
    """
    return {
        "status": "healthy",
        "service": "points"
    }
