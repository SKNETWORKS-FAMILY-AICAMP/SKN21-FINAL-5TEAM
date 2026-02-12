"""
CRUD Operations - User History Module
사용자 행동 히스토리 관련 CRUD 함수
"""
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc
import json

from ecommerce.platform.backend.app.router.user_history import models, schemas


# ============================================
# 기본 CRUD
# ============================================

def create_history(
    db: Session,
    user_id: int,
    history_data: schemas.UserHistoryCreate
) -> models.UserHistory:
    """
    히스토리 생성

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        history_data: 히스토리 데이터

    Returns:
        생성된 UserHistory 객체
    """
    history = models.UserHistory(
        user_id=user_id,
        action_type=history_data.action_type,
        product_option_type=history_data.product_option_type,
        product_option_id=history_data.product_option_id,
        order_id=history_data.order_id,
        cart_item_id=history_data.cart_item_id,
        action_metadata=history_data.action_metadata,
        search_keyword=history_data.search_keyword,
        ip_address=history_data.ip_address,
        user_agent=history_data.user_agent
    )

    db.add(history)
    db.commit()
    db.refresh(history)

    return history


def get_history_by_id(db: Session, history_id: int) -> Optional[models.UserHistory]:
    """
    히스토리 ID로 조회

    Args:
        db: 데이터베이스 세션
        history_id: 히스토리 ID

    Returns:
        UserHistory 객체 또는 None
    """
    return db.query(models.UserHistory).filter(
        models.UserHistory.id == history_id
    ).first()


def get_user_history(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[models.UserHistory]:
    """
    사용자별 히스토리 조회

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수

    Returns:
        UserHistory 객체 리스트
    """
    return (
        db.query(models.UserHistory)
        .filter(models.UserHistory.user_id == user_id)
        .order_by(models.UserHistory.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_history_by_action_type(
    db: Session,
    user_id: int,
    action_type: schemas.ActionType,
    skip: int = 0,
    limit: int = 100
) -> List[models.UserHistory]:
    """
    행동 유형별 히스토리 조회

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        action_type: 행동 유형
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수

    Returns:
        UserHistory 객체 리스트
    """
    return (
        db.query(models.UserHistory)
        .filter(
            and_(
                models.UserHistory.user_id == user_id,
                models.UserHistory.action_type == action_type
            )
        )
        .order_by(models.UserHistory.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_history_by_date_range(
    db: Session,
    user_id: int,
    start_date: datetime,
    end_date: datetime
) -> List[models.UserHistory]:
    """
    날짜 범위로 히스토리 조회

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        start_date: 시작 날짜
        end_date: 종료 날짜

    Returns:
        UserHistory 객체 리스트
    """
    return (
        db.query(models.UserHistory)
        .filter(
            and_(
                models.UserHistory.user_id == user_id,
                models.UserHistory.created_at >= start_date,
                models.UserHistory.created_at <= end_date
            )
        )
        .order_by(models.UserHistory.created_at.desc())
        .all()
    )


# ============================================
# 추적 헬퍼 함수
# ============================================

def track_cart_action(
    db: Session,
    user_id: int,
    action_type: schemas.ActionType,
    cart_item_id: int,
    product_option_type: str,
    product_option_id: int,
    metadata: Optional[dict] = None
) -> models.UserHistory:
    """
    장바구니 행동 기록

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        action_type: 행동 유형
        cart_item_id: 장바구니 항목 ID
        product_option_type: 상품 옵션 유형
        product_option_id: 상품 옵션 ID
        metadata: 추가 메타데이터

    Returns:
        생성된 UserHistory 객체
    """
    metadata_str = json.dumps(metadata) if metadata else None

    history_data = schemas.UserHistoryCreate(
        action_type=action_type,
        product_option_type=product_option_type,
        product_option_id=product_option_id,
        order_id=None,
        cart_item_id=cart_item_id,
        action_metadata=metadata_str,
        search_keyword=None,
        ip_address=None,
        user_agent=None
    )

    return create_history(db, user_id, history_data)


def track_order_action(
    db: Session,
    user_id: int,
    order_id: int,
    action_type: schemas.ActionType
) -> models.UserHistory:
    """
    주문 행동 기록

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        order_id: 주문 ID
        action_type: 행동 유형

    Returns:
        생성된 UserHistory 객체
    """
    history_data = schemas.UserHistoryCreate(
        action_type=action_type,
        product_option_type=None,
        product_option_id=None,
        order_id=order_id,
        cart_item_id=None,
        action_metadata=None,
        search_keyword=None,
        ip_address=None,
        user_agent=None
    )

    return create_history(db, user_id, history_data)


def track_auth_action(
    db: Session,
    user_id: int,
    action_type: schemas.ActionType,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> models.UserHistory:
    """
    로그인/로그아웃 기록

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        action_type: 행동 유형
        ip_address: IP 주소
        user_agent: User Agent

    Returns:
        생성된 UserHistory 객체
    """
    history_data = schemas.UserHistoryCreate(
        action_type=action_type,
        product_option_type=None,
        product_option_id=None,
        order_id=None,
        cart_item_id=None,
        action_metadata=None,
        search_keyword=None,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return create_history(db, user_id, history_data)


def track_refund_request(
    db: Session,
    user_id: int,
    order_id: int
) -> models.UserHistory:
    """
    환불 요청 기록

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        order_id: 주문 ID

    Returns:
        생성된 UserHistory 객체
    """
    history_data = schemas.UserHistoryCreate(
        action_type=schemas.ActionType.REFUND_REQUEST,
        product_option_type=None,
        product_option_id=None,
        order_id=order_id,
        cart_item_id=None,
        action_metadata=None,
        search_keyword=None,
        ip_address=None,
        user_agent=None
    )

    return create_history(db, user_id, history_data)


def track_review_create(
    db: Session,
    user_id: int,
    review_id: int,
    product_option_type: str,
    product_option_id: int
) -> models.UserHistory:
    """
    리뷰 작성 기록

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        review_id: 리뷰 ID
        product_option_type: 상품 옵션 유형
        product_option_id: 상품 옵션 ID

    Returns:
        생성된 UserHistory 객체
    """
    metadata_str = json.dumps({"review_id": review_id})

    history_data = schemas.UserHistoryCreate(
        action_type=schemas.ActionType.REVIEW_CREATE,
        product_option_type=product_option_type,
        product_option_id=product_option_id,
        order_id=None,
        cart_item_id=None,
        action_metadata=metadata_str,
        search_keyword=None,
        ip_address=None,
        user_agent=None
    )

    return create_history(db, user_id, history_data)


# ============================================
# 통계 및 분석 함수
# ============================================

def get_actions_by_type(
    db: Session,
    user_id: int,
    days: int = 30
) -> List[schemas.ActionStatistics]:
    """
    행동 유형별 통계

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        days: 조회 기간 (일)

    Returns:
        행동 통계 리스트
    """
    start_date = datetime.now() - timedelta(days=days)

    results = (
        db.query(
            models.UserHistory.action_type,
            func.count(models.UserHistory.id).label('action_count'),
            func.max(models.UserHistory.created_at).label('last_action_at')
        )
        .filter(
            and_(
                models.UserHistory.user_id == user_id,
                models.UserHistory.created_at >= start_date
            )
        )
        .group_by(models.UserHistory.action_type)
        .all()
    )

    return [
        schemas.ActionStatistics(
            action_type=result.action_type,
            count=result.action_count,
            last_action_at=result.last_action_at
        )
        for result in results
    ]


def get_user_activity_summary(
    db: Session,
    user_id: int,
    days: int = 30
) -> schemas.UserActivitySummary:
    """
    사용자 활동 요약

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        days: 조회 기간 (일)

    Returns:
        사용자 활동 요약
    """
    start_date = datetime.now() - timedelta(days=days)

    # 전체 행동 수
    total_actions = (
        db.query(func.count(models.UserHistory.id))
        .filter(
            and_(
                models.UserHistory.user_id == user_id,
                models.UserHistory.created_at >= start_date
            )
        )
        .scalar() or 0
    )

    # 행동 유형별 통계
    actions_by_type = get_actions_by_type(db, user_id, days)

    # 마지막 로그인 시간
    last_login = (
        db.query(models.UserHistory.created_at)
        .filter(
            and_(
                models.UserHistory.user_id == user_id,
                models.UserHistory.action_type == schemas.ActionType.LOGIN
            )
        )
        .order_by(models.UserHistory.created_at.desc())
        .first()
    )

    last_login_at = last_login[0] if last_login else None

    return schemas.UserActivitySummary(
        user_id=user_id,
        total_actions=total_actions,
        actions_by_type=actions_by_type,
        last_login_at=last_login_at
    )


# ============================================
# 데이터 관리 함수
# ============================================

def delete_old_history(db: Session, days: int = 180) -> int:
    """
    오래된 히스토리 삭제

    Args:
        db: 데이터베이스 세션
        days: 보관 기간 (일)

    Returns:
        삭제된 레코드 수
    """
    cutoff_date = datetime.now() - timedelta(days=days)

    deleted_count = (
        db.query(models.UserHistory)
        .filter(models.UserHistory.created_at < cutoff_date)
        .delete()
    )

    db.commit()

    return deleted_count


def anonymize_user_history(db: Session, user_id: int) -> int:
    """
    사용자 히스토리 익명화 (탈퇴 시)

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID

    Returns:
        익명화된 레코드 수
    """
    affected = (
        db.query(models.UserHistory)
        .filter(models.UserHistory.user_id == user_id)
        .update({
            "ip_address": None,
            "user_agent": None,
            "action_metadata": None
        })
    )

    db.commit()

    return affected
