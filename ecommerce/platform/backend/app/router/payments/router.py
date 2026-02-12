"""
FastAPI Router - Payments Module
결제 관련 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.payments import crud, schemas

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["payments"]
)


# ==================== 결제 조회 ====================

@router.get("/{payment_id}", response_model=schemas.PaymentResponse)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db)
):
    """
    결제 ID로 조회
    
    Args:
        payment_id: 결제 ID
        db: 데이터베이스 세션
    
    Returns:
        결제 정보
    """
    logger.info(f"Fetching payment: {payment_id}")
    
    payment = crud.get_payment_by_id(db, payment_id)
    
    if not payment:
        logger.warning(f"Payment not found: {payment_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="결제 정보를 찾을 수 없습니다"
        )
    
    return payment


@router.get("/order/{order_id}", response_model=schemas.PaymentResponse)
def get_payment_by_order(
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    주문 ID로 결제 조회
    
    Args:
        order_id: 주문 ID
        db: 데이터베이스 세션
    
    Returns:
        결제 정보
    """
    logger.info(f"Fetching payment for order: {order_id}")
    
    payment = crud.get_payment_by_order_id(db, order_id)
    
    if not payment:
        logger.warning(f"Payment not found for order: {order_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 주문의 결제 정보를 찾을 수 없습니다"
        )
    
    return payment


@router.get("/status/{payment_status}", response_model=List[schemas.PaymentResponse])
def get_payments_by_status(
    payment_status: schemas.PaymentStatus,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    결제 상태별 조회
    
    Args:
        payment_status: 결제 상태
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        결제 목록
    """
    logger.info(f"Fetching payments with status: {payment_status}")
    
    payments = crud.get_payments_by_status(db, payment_status, skip, limit)
    
    return payments


@router.get("/method/{payment_method}", response_model=List[schemas.PaymentResponse])
def get_payments_by_method(
    payment_method: str,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    결제 수단별 조회
    
    Args:
        payment_method: 결제 수단
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        결제 목록
    """
    logger.info(f"Fetching payments with method: {payment_method}")
    
    payments = crud.get_payments_by_method(db, payment_method, skip, limit)
    
    return payments


# ==================== 결제 생성 ====================

@router.post("", response_model=schemas.PaymentResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    payment_data: schemas.PaymentCreate,
    db: Session = Depends(get_db)
):
    """
    새 결제 생성
    
    Args:
        payment_data: 결제 생성 데이터
        db: 데이터베이스 세션
    
    Returns:
        생성된 결제 정보
    """
    logger.info(f"Creating payment for order: {payment_data.order_id}")
    
    try:
        payment = crud.create_payment(db, payment_data)
        logger.info(f"Created payment: {payment.id}")
        return payment
    except ValueError as e:
        logger.error(f"Failed to create payment: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 결제 처리 ====================

@router.post("/orders/{order_id}/process", response_model=schemas.PaymentResponse)
def process_payment(
    order_id: int,
    payment_method: str = Query(..., description="결제 수단"),
    payment_data: Optional[str] = Query(None, description="결제 데이터 (JSON)"),
    card_numbers: Optional[str] = Query(None, description="카드번호 (마스킹)"),
    db: Session = Depends(get_db)
):
    """
    결제 처리 (결제 생성 및 완료 처리)
    
    Args:
        order_id: 주문 ID
        payment_method: 결제 수단
        payment_data: 결제 데이터
        card_numbers: 카드번호
        db: 데이터베이스 세션
    
    Returns:
        처리된 결제 정보
    """
    logger.info(f"Processing payment for order: {order_id}")
    
    try:
        payment = crud.process_payment(
            db,
            order_id=order_id,
            payment_method=payment_method,
            payment_data=payment_data,
            card_numbers=card_numbers
        )
        logger.info(f"Payment processed successfully: {payment.id}")
        return payment
    except ValueError as e:
        logger.error(f"Failed to process payment: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 결제 수정 ====================

@router.put("/{payment_id}", response_model=schemas.PaymentResponse)
def update_payment(
    payment_id: int,
    payment_update: schemas.PaymentUpdate,
    db: Session = Depends(get_db)
):
    """
    결제 정보 수정
    
    Args:
        payment_id: 결제 ID
        payment_update: 수정할 결제 정보
        db: 데이터베이스 세션
    
    Returns:
        수정된 결제 정보
    """
    logger.info(f"Updating payment: {payment_id}")
    
    payment = crud.update_payment(db, payment_id, payment_update)
    
    if not payment:
        logger.warning(f"Payment not found for update: {payment_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="결제 정보를 찾을 수 없습니다"
        )
    
    logger.info(f"Payment updated: {payment_id}")
    return payment


@router.patch("/{payment_id}/status", response_model=schemas.PaymentResponse)
def update_payment_status(
    payment_id: int,
    status_update: schemas.PaymentStatusUpdate,
    update_order: bool = Query(True, description="주문 상태도 함께 업데이트할지 여부"),
    db: Session = Depends(get_db)
):
    """
    결제 상태 변경
    
    Args:
        payment_id: 결제 ID
        status_update: 변경할 결제 상태
        update_order: 주문 상태도 함께 업데이트할지 여부
        db: 데이터베이스 세션
    
    Returns:
        수정된 결제 정보
    """
    logger.info(f"Updating payment status: {payment_id} -> {status_update.payment_status}")
    
    payment = crud.update_payment_status(
        db,
        payment_id,
        status_update.payment_status,
        update_order_status=update_order
    )
    
    if not payment:
        logger.warning(f"Payment not found for status update: {payment_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="결제 정보를 찾을 수 없습니다"
        )
    
    logger.info(f"Payment status updated: {payment_id}")
    return payment


# ==================== 결제 취소/환불 ====================

@router.post("/{payment_id}/cancel", response_model=schemas.PaymentResponse)
def cancel_payment(
    payment_id: int,
    reason: Optional[str] = Query(None, description="취소 사유"),
    db: Session = Depends(get_db)
):
    """
    결제 취소
    
    Args:
        payment_id: 결제 ID
        reason: 취소 사유
        db: 데이터베이스 세션
    
    Returns:
        취소된 결제 정보
    """
    logger.info(f"Cancelling payment: {payment_id}")
    
    # 취소 가능 여부 확인
    if not crud.can_cancel_payment(db, payment_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="취소할 수 없는 결제 상태입니다"
        )
    
    try:
        payment = crud.cancel_payment(db, payment_id, reason)
        
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="결제 정보를 찾을 수 없습니다"
            )
        
        logger.info(f"Payment cancelled: {payment_id}")
        return payment
    except ValueError as e:
        logger.error(f"Failed to cancel payment: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{payment_id}/refund", response_model=schemas.PaymentResponse)
def refund_payment(
    payment_id: int,
    reason: Optional[str] = Query(None, description="환불 사유"),
    db: Session = Depends(get_db)
):
    """
    결제 환불
    
    Args:
        payment_id: 결제 ID
        reason: 환불 사유
        db: 데이터베이스 세션
    
    Returns:
        환불된 결제 정보
    """
    logger.info(f"Refunding payment: {payment_id}")
    
    # 환불 가능 여부 확인
    if not crud.can_refund_payment(db, payment_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="환불할 수 없는 결제 상태입니다"
        )
    
    try:
        payment = crud.refund_payment(db, payment_id, reason)
        
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="결제 정보를 찾을 수 없습니다"
            )
        
        logger.info(f"Payment refunded: {payment_id}")
        return payment
    except ValueError as e:
        logger.error(f"Failed to refund payment: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 결제 삭제 ====================

@router.delete("/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(
    payment_id: int,
    db: Session = Depends(get_db)
):
    """
    결제 삭제 (주의: 실제 운영에서는 거의 사용하지 않음)
    
    Args:
        payment_id: 결제 ID
        db: 데이터베이스 세션
    
    Returns:
        None
    """
    logger.warning(f"Deleting payment: {payment_id}")
    
    success = crud.delete_payment(db, payment_id)
    
    if not success:
        logger.warning(f"Payment not found for deletion: {payment_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="결제 정보를 찾을 수 없습니다"
        )
    
    logger.info(f"Payment deleted: {payment_id}")
    return None


# ==================== 검증 엔드포인트 ====================

@router.get("/{payment_id}/verify-ownership")
def verify_payment_ownership(
    payment_id: int,
    user_id: int = Query(..., description="사용자 ID"),
    db: Session = Depends(get_db)
):
    """
    결제 소유권 확인
    
    Args:
        payment_id: 결제 ID
        user_id: 사용자 ID
        db: 데이터베이스 세션
    
    Returns:
        소유권 여부
    """
    is_owner = crud.verify_payment_ownership(db, payment_id, user_id)
    
    return {
        "payment_id": payment_id,
        "user_id": user_id,
        "is_owner": is_owner
    }


@router.get("/{payment_id}/can-cancel")
def check_can_cancel(
    payment_id: int,
    db: Session = Depends(get_db)
):
    """
    결제 취소 가능 여부 확인
    
    Args:
        payment_id: 결제 ID
        db: 데이터베이스 세션
    
    Returns:
        취소 가능 여부
    """
    can_cancel = crud.can_cancel_payment(db, payment_id)
    
    return {
        "payment_id": payment_id,
        "can_cancel": can_cancel
    }


@router.get("/{payment_id}/can-refund")
def check_can_refund(
    payment_id: int,
    db: Session = Depends(get_db)
):
    """
    결제 환불 가능 여부 확인
    
    Args:
        payment_id: 결제 ID
        db: 데이터베이스 세션
    
    Returns:
        환불 가능 여부
    """
    can_refund = crud.can_refund_payment(db, payment_id)
    
    return {
        "payment_id": payment_id,
        "can_refund": can_refund
    }


# ==================== 헬스 체크 ====================

@router.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    결제 API 헬스 체크
    
    Returns:
        상태 정보
    """
    return {
        "status": "healthy",
        "service": "payments"
    }
