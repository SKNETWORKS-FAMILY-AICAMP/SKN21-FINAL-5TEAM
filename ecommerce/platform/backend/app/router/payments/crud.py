"""
CRUD Operations - Payments Module
결제 관련 CRUD 함수
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ecommerce.platform.backend.app.router.payments import models, schemas
from ecommerce.platform.backend.app.router.orders.models import Order
# Orders 스키마에서 OrderStatus import
from ecommerce.platform.backend.app.router.orders.schemas import OrderStatus


# ============================================
# Payment CRUD
# ============================================

def get_payment_by_id(db: Session, payment_id: int) -> Optional[models.Payment]:
    """
    결제 ID로 조회
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
    
    Returns:
        Payment 객체 또는 None
    """
    return db.query(models.Payment).filter(models.Payment.id == payment_id).first()


def get_payment_by_order_id(db: Session, order_id: int) -> Optional[models.Payment]:
    """
    주문 ID로 결제 조회 (1:1 관계)
    
    Args:
        db: 데이터베이스 세션
        order_id: 주문 ID
    
    Returns:
        Payment 객체 또는 None
    """
    return db.query(models.Payment).filter(models.Payment.order_id == order_id).first()


def get_payments_by_status(
    db: Session,
    payment_status: schemas.PaymentStatus,
    skip: int = 0,
    limit: int = 100
) -> List[models.Payment]:
    """
    결제 상태별 조회
    
    Args:
        db: 데이터베이스 세션
        payment_status: 결제 상태
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        Payment 객체 리스트
    """
    return (
        db.query(models.Payment)
        .filter(models.Payment.payment_status == payment_status)
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_payments_by_method(
    db: Session,
    payment_method: str,
    skip: int = 0,
    limit: int = 100
) -> List[models.Payment]:
    """
    결제 수단별 조회
    
    Args:
        db: 데이터베이스 세션
        payment_method: 결제 수단
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        Payment 객체 리스트
    """
    return (
        db.query(models.Payment)
        .filter(models.Payment.payment_method == payment_method)
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_payment(
    db: Session,
    payment_data: schemas.PaymentCreate
) -> models.Payment:
    """
    새 결제 생성
    
    Args:
        db: 데이터베이스 세션
        payment_data: 결제 생성 데이터
    
    Returns:
        생성된 Payment 객체
    
    Raises:
        ValueError: 주문을 찾을 수 없거나 이미 결제가 존재하는 경우
    """
    # 주문 존재 여부 확인
    order = db.query(Order).filter(Order.id == payment_data.order_id).first()
    if not order:
        raise ValueError(f"주문 ID {payment_data.order_id}를 찾을 수 없습니다")
    
    # 이미 결제가 존재하는지 확인
    existing_payment = get_payment_by_order_id(db, payment_data.order_id)
    if existing_payment:
        raise ValueError(f"주문 ID {payment_data.order_id}에 대한 결제가 이미 존재합니다")
    
    # 결제 생성
    payment = models.Payment(
        order_id=payment_data.order_id,
        payment_method=payment_data.payment_method,
        payment_data=payment_data.payment_data,
        payment_status=payment_data.payment_status,
        card_numbers=payment_data.card_numbers
    )
    
    db.add(payment)
    db.commit()
    db.refresh(payment)
    
    return payment


def update_payment(
    db: Session,
    payment_id: int,
    payment_update: schemas.PaymentUpdate
) -> Optional[models.Payment]:
    """
    결제 정보 수정
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
        payment_update: 수정할 결제 정보
    
    Returns:
        수정된 Payment 객체 또는 None
    """
    payment = get_payment_by_id(db, payment_id)
    
    if not payment:
        return None
    
    # 업데이트할 데이터만 추출 (None이 아닌 값만)
    update_data = payment_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(payment, key, value)
    
    db.commit()
    db.refresh(payment)
    
    return payment


def update_payment_status(
    db: Session,
    payment_id: int,
    new_status: schemas.PaymentStatus,
    update_order_status: bool = True
) -> Optional[models.Payment]:
    """
    결제 상태 변경 (주문 상태도 함께 변경 가능)
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
        new_status: 새로운 결제 상태
        update_order_status: 주문 상태도 함께 업데이트할지 여부
    
    Returns:
        수정된 Payment 객체 또는 None
    """
    payment = get_payment_by_id(db, payment_id)
    
    if not payment:
        return None
    
    # 결제 상태 변경 - .value 사용하여 문자열로 변환
    payment.payment_status = models.PaymentStatus(new_status)
    
    # 주문 상태도 함께 변경
    if update_order_status:
        order = db.query(Order).filter(Order.id == payment.order_id).first()
        if order:
            if new_status == schemas.PaymentStatus.COMPLETED:
                order.status = OrderStatus.PAID 
            elif new_status == schemas.PaymentStatus.FAILED:
                order.status = OrderStatus.CANCELLED
            elif new_status == schemas.PaymentStatus.CANCELLED:
                order.status = OrderStatus.CANCELLED
    
    db.commit()
    db.refresh(payment)
    
    return payment


def delete_payment(db: Session, payment_id: int) -> bool:
    """
    결제 삭제
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
    
    Returns:
        삭제 성공 여부
    """
    payment = get_payment_by_id(db, payment_id)
    
    if not payment:
        return False
    
    db.delete(payment)
    db.commit()
    
    return True


# ============================================
# Payment Processing Functions
# ============================================

def process_payment(
    db: Session,
    order_id: int,
    payment_method: str,
    payment_data: Optional[str] = None,
    card_numbers: Optional[str] = None
) -> models.Payment:
    """
    결제 처리 (결제 생성 + 상태 변경)
    
    Args:
        db: 데이터베이스 세션
        order_id: 주문 ID
        payment_method: 결제 수단
        payment_data: 결제 데이터 (JSON)
        card_numbers: 카드번호 (마스킹)
    
    Returns:
        처리된 Payment 객체
    
    Raises:
        ValueError: 주문을 찾을 수 없거나 결제 처리 실패
    """
    # 주문 확인
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError(f"주문 ID {order_id}를 찾을 수 없습니다")
    
    # 이미 결제가 있는지 확인
    existing_payment = get_payment_by_order_id(db, order_id)
    
    if existing_payment:
        # 이미 결제가 있으면 상태만 업데이트
        if existing_payment.payment_status == schemas.PaymentStatus.COMPLETED:
            raise ValueError("이미 결제가 완료된 주문입니다")
        
        # 결제 상태를 COMPLETED로 변경
        existing_payment.payment_status = models.PaymentStatus.COMPLETED
        existing_payment.payment_method = payment_method
        if payment_data:
            existing_payment.payment_data = payment_data
        if card_numbers:
            existing_payment.card_numbers = card_numbers
        
        payment = existing_payment
    else:
        # 새 결제 생성
        payment_create = schemas.PaymentCreate(
            order_id=order_id,
            payment_method=payment_method,
            payment_data=payment_data,
            payment_status=schemas.PaymentStatus.COMPLETED,
            card_numbers=card_numbers
        )
        payment = create_payment(db, payment_create)
    
    # 주문 상태를 PAID로 변경
    order.status = OrderStatus.PAID 
    
    db.commit()
    db.refresh(payment)
    
    return payment


def cancel_payment(
    db: Session,
    payment_id: int,
    reason: Optional[str] = None
) -> Optional[models.Payment]:
    """
    결제 취소
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
        reason: 취소 사유
    
    Returns:
        취소된 Payment 객체 또는 None
    """
    payment = get_payment_by_id(db, payment_id)
    
    if not payment:
        return None
    
    # 이미 취소된 결제인지 확인
    if payment.payment_status == schemas.PaymentStatus.CANCELLED:
        raise ValueError("이미 취소된 결제입니다")
    
    # 결제 상태를 CANCELLED로 변경
    payment.payment_status = models.PaymentStatus.CANCELLED
    
    # 취소 사유를 payment_data에 저장 (선택사항)
    if reason:
        import json
        cancel_data = {
            "cancelled_at": datetime.utcnow().isoformat(),
            "reason": reason
        }
        payment.payment_data = json.dumps(cancel_data)
    
    # 주문 상태도 CANCELLED로 변경
    order = db.query(Order).filter(Order.id == payment.order_id).first()
    if order:
        order.status = OrderStatus.CANCELLED
    
    db.commit()
    db.refresh(payment)
    
    return payment


def refund_payment(
    db: Session,
    payment_id: int,
    reason: Optional[str] = None
) -> Optional[models.Payment]:
    """
    결제 환불
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
        reason: 환불 사유
    
    Returns:
        환불된 Payment 객체 또는 None
    """
    payment = get_payment_by_id(db, payment_id)
    
    if not payment:
        return None
    
    # 완료된 결제만 환불 가능
    if payment.payment_status != schemas.PaymentStatus.COMPLETED:
        raise ValueError("완료된 결제만 환불할 수 있습니다")
    
    # 결제 상태를 CANCELLED로 변경 (환불은 취소로 처리)
    payment.payment_status = models.PaymentStatus.CANCELLED
    
    # 환불 정보를 payment_data에 저장
    if reason:
        import json
        refund_data = {
            "refunded_at": datetime.utcnow().isoformat(),
            "reason": reason,
            "type": "refund"
        }
        payment.payment_data = json.dumps(refund_data)
    
    # 주문 상태를 REFUNDED로 변경
    order = db.query(Order).filter(Order.id == payment.order_id).first()
    if order:
        order.status = OrderStatus.REFUNDED
    
    db.commit()
    db.refresh(payment)
    
    return payment


# ============================================
# Validation Functions
# ============================================

def verify_payment_ownership(
    db: Session,
    payment_id: int,
    user_id: int
) -> bool:
    """
    결제의 소유권 확인 (결제의 주문이 해당 사용자의 것인지 확인)
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
        user_id: 사용자 ID
    
    Returns:
        소유권 여부
    """
    result = (
        db.query(models.Payment)
        .join(Order, models.Payment.order_id == Order.id)
        .filter(
            and_(
                models.Payment.id == payment_id,
                Order.user_id == user_id
            )
        )
        .first()
    )
    
    return result is not None


def can_cancel_payment(db: Session, payment_id: int) -> bool:
    """
    결제 취소 가능 여부 확인
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
    
    Returns:
        취소 가능 여부
    """
    payment = get_payment_by_id(db, payment_id)
    
    if not payment:
        return False
    
    # PENDING 또는 COMPLETED 상태만 취소 가능
    return payment.payment_status in [
        schemas.PaymentStatus.PENDING,
        schemas.PaymentStatus.COMPLETED
    ]


def can_refund_payment(db: Session, payment_id: int) -> bool:
    """
    결제 환불 가능 여부 확인
    
    Args:
        db: 데이터베이스 세션
        payment_id: 결제 ID
    
    Returns:
        환불 가능 여부
    """
    payment = get_payment_by_id(db, payment_id)
    
    if not payment:
        return False
    
    # COMPLETED 상태만 환불 가능
    return payment.payment_status == schemas.PaymentStatus.COMPLETED
