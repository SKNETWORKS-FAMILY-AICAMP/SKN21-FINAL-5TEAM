"""
CRUD Operations - Points Module
포인트 및 상품권 관련 CRUD 함수
"""
from typing import Optional, List
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ecommerce.platform.backend.app.router.points import models, schemas


# ============================================
# PointHistory CRUD
# ============================================

def get_point_history_by_id(db: Session, history_id: int) -> Optional[models.PointHistory]:
    """
    포인트 내역 ID로 조회
    
    Args:
        db: 데이터베이스 세션
        history_id: 포인트 내역 ID
    
    Returns:
        PointHistory 객체 또는 None
    """
    return db.query(models.PointHistory).filter(
        models.PointHistory.id == history_id
    ).first()


def get_point_history_by_user(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[models.PointHistory]:
    """
    사용자별 포인트 내역 조회
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        PointHistory 객체 리스트
    """
    return (
        db.query(models.PointHistory)
        .filter(models.PointHistory.user_id == user_id)
        .order_by(models.PointHistory.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_point_history_by_type(
    db: Session,
    user_id: int,
    point_type: schemas.PointType,
    skip: int = 0,
    limit: int = 100
) -> List[models.PointHistory]:
    """
    포인트 유형별 내역 조회
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        point_type: 포인트 유형
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        PointHistory 객체 리스트
    """
    return (
        db.query(models.PointHistory)
        .filter(
            and_(
                models.PointHistory.user_id == user_id,
                models.PointHistory.type == point_type
            )
        )
        .order_by(models.PointHistory.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_current_point_balance(db: Session, user_id: int) -> Decimal:
    """
    현재 포인트 잔액 조회
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
    
    Returns:
        현재 포인트 잔액
    """
    # 가장 최근 내역의 balance_after 조회
    latest = (
        db.query(models.PointHistory.balance_after)
        .filter(models.PointHistory.user_id == user_id)
        .order_by(models.PointHistory.created_at.desc())
        .first()
    )
    
    return latest[0] if latest else Decimal('0')


def get_point_statistics(db: Session, user_id: int) -> schemas.PointBalance:
    """
    포인트 통계 조회
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
    
    Returns:
        포인트 잔액 및 통계
    """
    # 현재 잔액
    current_balance = get_current_point_balance(db, user_id)
    
    # 총 적립 포인트 (EARN, REFUND)
    total_earned = (
        db.query(func.sum(models.PointHistory.amount))
        .filter(
            and_(
                models.PointHistory.user_id == user_id,
                models.PointHistory.type.in_([schemas.PointType.EARN, schemas.PointType.REFUND])
            )
        )
        .scalar() or Decimal('0')
    )
    
    # 총 사용 포인트 (USE, EXPIRE) - 절대값
    total_used = abs(
        db.query(func.sum(models.PointHistory.amount))
        .filter(
            and_(
                models.PointHistory.user_id == user_id,
                models.PointHistory.type.in_([schemas.PointType.USE, schemas.PointType.EXPIRE])
            )
        )
        .scalar() or Decimal('0')
    )
    
    return schemas.PointBalance(
        user_id=user_id,
        current_balance=current_balance,
        total_earned=total_earned,
        total_used=total_used
    )


def create_point_history(
    db: Session,
    user_id: int,
    history_data: schemas.PointHistoryCreate
) -> models.PointHistory:
    """
    포인트 내역 생성
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        history_data: 포인트 내역 데이터
    
    Returns:
        생성된 PointHistory 객체
    """
    # 현재 잔액 조회
    current_balance = get_current_point_balance(db, user_id)
    
    # 새 잔액 계산
    new_balance = current_balance + history_data.amount
    
    # 잔액이 음수가 되는지 확인
    if new_balance < 0:
        raise ValueError("포인트 잔액이 부족합니다")
    
    # 포인트 내역 생성
    point_history = models.PointHistory(
        user_id=user_id,
        order_id=history_data.order_id,
        amount=history_data.amount,
        balance_after=new_balance,
        type=history_data.type,
        description=history_data.description
    )
    
    db.add(point_history)
    db.commit()
    db.refresh(point_history)
    
    return point_history


# ============================================
# Point Transaction Functions
# ============================================

def earn_points(
    db: Session,
    user_id: int,
    amount: Decimal,
    description: Optional[str] = None,
    order_id: Optional[int] = None
) -> models.PointHistory:
    """
    포인트 적립
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        amount: 적립할 포인트
        description: 적립 사유
        order_id: 관련 주문 ID
    
    Returns:
        생성된 PointHistory 객체
    """
    if amount <= 0:
        raise ValueError("적립 금액은 0보다 커야 합니다")
    
    history_data = schemas.PointHistoryCreate(
        amount=amount,
        type=schemas.PointType.EARN,
        description=description or "포인트 적립",
        order_id=order_id
    )
    
    return create_point_history(db, user_id, history_data)


def use_points(
    db: Session,
    user_id: int,
    amount: Decimal,
    description: Optional[str] = None,
    order_id: Optional[int] = None
) -> models.PointHistory:
    """
    포인트 사용
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        amount: 사용할 포인트
        description: 사용 사유
        order_id: 관련 주문 ID
    
    Returns:
        생성된 PointHistory 객체
    """
    if amount <= 0:
        raise ValueError("사용 금액은 0보다 커야 합니다")
    
    # 현재 잔액 확인
    current_balance = get_current_point_balance(db, user_id)
    if current_balance < amount:
        raise ValueError(f"포인트 잔액이 부족합니다 (현재: {current_balance}, 요청: {amount})")
    
    history_data = schemas.PointHistoryCreate(
        amount=-amount,  # 음수로 저장
        type=schemas.PointType.USE,
        description=description or "포인트 사용",
        order_id=order_id
    )
    
    return create_point_history(db, user_id, history_data)


def refund_points(
    db: Session,
    user_id: int,
    amount: Decimal,
    description: Optional[str] = None,
    order_id: Optional[int] = None
) -> models.PointHistory:
    """
    포인트 환불
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        amount: 환불할 포인트
        description: 환불 사유
        order_id: 관련 주문 ID
    
    Returns:
        생성된 PointHistory 객체
    """
    if amount <= 0:
        raise ValueError("환불 금액은 0보다 커야 합니다")
    
    history_data = schemas.PointHistoryCreate(
        amount=amount,
        type=schemas.PointType.REFUND,
        description=description or "포인트 환불",
        order_id=order_id
    )
    
    return create_point_history(db, user_id, history_data)


# ============================================
# IssuedVoucher CRUD
# ============================================

def get_voucher_by_id(db: Session, voucher_id: int) -> Optional[models.IssuedVoucher]:
    """
    상품권 ID로 조회
    
    Args:
        db: 데이터베이스 세션
        voucher_id: 상품권 ID
    
    Returns:
        IssuedVoucher 객체 또는 None
    """
    return db.query(models.IssuedVoucher).filter(
        models.IssuedVoucher.id == voucher_id
    ).first()


def get_voucher_by_code(db: Session, voucher_code: str) -> Optional[models.IssuedVoucher]:
    """
    상품권 코드로 조회
    
    Args:
        db: 데이터베이스 세션
        voucher_code: 상품권 코드
    
    Returns:
        IssuedVoucher 객체 또는 None
    """
    return db.query(models.IssuedVoucher).filter(
        models.IssuedVoucher.voucher_code == voucher_code
    ).first()


def get_vouchers_by_user(
    db: Session,
    user_id: int,
    include_used: bool = False,
    skip: int = 0,
    limit: int = 100
) -> List[models.IssuedVoucher]:
    """
    사용자별 상품권 목록 조회
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        include_used: 사용된 상품권 포함 여부
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        IssuedVoucher 객체 리스트
    """
    query = db.query(models.IssuedVoucher).filter(
        models.IssuedVoucher.user_id == user_id
    )
    
    if not include_used:
        query = query.filter(models.IssuedVoucher.is_used == False)
    
    return (
        query
        .order_by(models.IssuedVoucher.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_voucher(
    db: Session,
    user_id: int,
    voucher_data: schemas.IssuedVoucherCreate
) -> models.IssuedVoucher:
    """
    상품권 발급
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        voucher_data: 상품권 데이터
    
    Returns:
        생성된 IssuedVoucher 객체
    
    Raises:
        ValueError: 중복된 상품권 코드
    """
    # 중복 코드 확인
    existing = get_voucher_by_code(db, voucher_data.voucher_code)
    if existing:
        raise ValueError(f"이미 존재하는 상품권 코드입니다: {voucher_data.voucher_code}")
    
    voucher = models.IssuedVoucher(
        user_id=user_id,
        voucher_code=voucher_data.voucher_code,
        amount=voucher_data.amount,
        is_used=False
    )
    
    db.add(voucher)
    db.commit()
    db.refresh(voucher)
    
    return voucher


def use_voucher(
    db: Session,
    voucher_code: str,
    user_id: int
) -> models.IssuedVoucher:
    """
    상품권 사용
    
    Args:
        db: 데이터베이스 세션
        voucher_code: 상품권 코드
        user_id: 사용자 ID
    
    Returns:
        사용 처리된 IssuedVoucher 객체
    
    Raises:
        ValueError: 유효하지 않은 상품권
    """
    voucher = get_voucher_by_code(db, voucher_code)
    
    if not voucher:
        raise ValueError("존재하지 않는 상품권 코드입니다")
    
    if voucher.user_id != user_id:
        raise ValueError("본인의 상품권만 사용할 수 있습니다")
    
    if voucher.is_used:
        raise ValueError("이미 사용된 상품권입니다")
    
    # 상품권 사용 처리
    voucher.is_used = True
    voucher.used_at = datetime.utcnow()
    
    db.commit()
    db.refresh(voucher)
    
    return voucher


def delete_voucher(db: Session, voucher_id: int) -> bool:
    """
    상품권 삭제
    
    Args:
        db: 데이터베이스 세션
        voucher_id: 상품권 ID
    
    Returns:
        삭제 성공 여부
    """
    voucher = get_voucher_by_id(db, voucher_id)
    
    if not voucher:
        return False
    
    db.delete(voucher)
    db.commit()
    
    return True
