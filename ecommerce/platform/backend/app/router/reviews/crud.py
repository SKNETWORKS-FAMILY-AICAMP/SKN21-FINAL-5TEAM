"""
CRUD Operations - Reviews Module
리뷰 관련 CRUD 함수
"""
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_

from ecommerce.platform.backend.app.router.reviews import models, schemas
from ecommerce.platform.backend.app.router.orders.models import OrderItem, Order


# ============================================
# Review CRUD
# ============================================

def get_review_by_id(db: Session, review_id: int) -> Optional[models.Review]:
    """
    리뷰 ID로 조회
    
    Args:
        db: 데이터베이스 세션
        review_id: 리뷰 ID
    
    Returns:
        Review 객체 또는 None
    """
    return db.query(models.Review).filter(models.Review.id == review_id).first()


def get_review_by_order_item_id(db: Session, order_item_id: int) -> Optional[models.Review]:
    """
    주문 항목 ID로 리뷰 조회 (1:1 관계)
    
    Args:
        db: 데이터베이스 세션
        order_item_id: 주문 항목 ID
    
    Returns:
        Review 객체 또는 None
    """
    return db.query(models.Review).filter(
        models.Review.order_item_id == order_item_id
    ).first()


def get_reviews_by_user_id(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[models.Review]:
    """
    사용자 ID로 리뷰 목록 조회
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        Review 객체 리스트
    """
    return (
        db.query(models.Review)
        .filter(models.Review.user_id == user_id)
        .order_by(models.Review.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_reviews_by_product_option(
    db: Session,
    product_option_type: str,
    product_option_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[models.Review]:
    """
    상품 옵션으로 리뷰 목록 조회
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형 (new/used)
        product_option_id: 상품 옵션 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        Review 객체 리스트
    """
    return (
        db.query(models.Review)
        .join(OrderItem, models.Review.order_item_id == OrderItem.id)
        .filter(
            and_(
                OrderItem.product_option_type == product_option_type,
                OrderItem.product_option_id == product_option_id
            )
        )
        .order_by(models.Review.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_reviews_by_rating(
    db: Session,
    rating: int,
    skip: int = 0,
    limit: int = 100
) -> List[models.Review]:
    """
    평점별 리뷰 조회
    
    Args:
        db: 데이터베이스 세션
        rating: 평점 (1-5)
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        Review 객체 리스트
    """
    return (
        db.query(models.Review)
        .filter(models.Review.rating == rating)
        .order_by(models.Review.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_review(
    db: Session,
    user_id: int,
    review_data: schemas.ReviewCreate
) -> models.Review:
    """
    새 리뷰 생성
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        review_data: 리뷰 생성 데이터
    
    Returns:
        생성된 Review 객체
    
    Raises:
        ValueError: 유효하지 않은 요청
    """
    # 주문 항목 확인
    order_item = db.query(OrderItem).filter(
        OrderItem.id == review_data.order_item_id
    ).first()
    
    if not order_item:
        raise ValueError(f"주문 항목 ID {review_data.order_item_id}를 찾을 수 없습니다")
    
    # 주문의 소유자 확인
    order = db.query(Order).filter(Order.id == order_item.order_id).first()
    if not order or order.user_id != user_id:
        raise ValueError("본인의 주문에 대해서만 리뷰를 작성할 수 있습니다")
    
    # 이미 리뷰가 존재하는지 확인
    existing_review = get_review_by_order_item_id(db, review_data.order_item_id)
    if existing_review:
        raise ValueError("이미 리뷰가 작성된 주문 항목입니다")
    
    # 리뷰 생성
    review = models.Review(
        user_id=user_id,
        order_item_id=review_data.order_item_id,
        content=review_data.content,
        rating=review_data.rating
    )
    
    db.add(review)
    db.commit()
    db.refresh(review)
    
    return review


def update_review(
    db: Session,
    review_id: int,
    review_update: schemas.ReviewUpdate
) -> Optional[models.Review]:
    """
    리뷰 수정
    
    Args:
        db: 데이터베이스 세션
        review_id: 리뷰 ID
        review_update: 수정할 리뷰 정보
    
    Returns:
        수정된 Review 객체 또는 None
    """
    review = get_review_by_id(db, review_id)
    
    if not review:
        return None
    
    # 업데이트할 데이터만 추출 (None이 아닌 값만)
    update_data = review_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(review, key, value)
    
    db.commit()
    db.refresh(review)
    
    return review


def delete_review(db: Session, review_id: int) -> bool:
    """
    리뷰 삭제
    
    Args:
        db: 데이터베이스 세션
        review_id: 리뷰 ID
    
    Returns:
        삭제 성공 여부
    """
    review = get_review_by_id(db, review_id)
    
    if not review:
        return False
    
    db.delete(review)
    db.commit()
    
    return True


# ============================================
# Review Statistics
# ============================================

def get_review_stats_by_product_option(
    db: Session,
    product_option_type: str,
    product_option_id: int
) -> schemas.ReviewStats:
    """
    상품 옵션별 리뷰 통계
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
    
    Returns:
        리뷰 통계
    """
    # 총 리뷰 수와 평균 평점
    result = (
        db.query(
            func.count(models.Review.id).label('total'),
            func.avg(models.Review.rating).label('avg_rating')
        )
        .join(OrderItem, models.Review.order_item_id == OrderItem.id)
        .filter(
            and_(
                OrderItem.product_option_type == product_option_type,
                OrderItem.product_option_id == product_option_id
            )
        )
        .first()
    )
    
    # result가 None이 아닌 경우에만 접근
    if result:
        total_reviews = result[0] if result[0] is not None else 0
        average_rating = float(result[1]) if result[1] is not None else 0.0
    else:
        total_reviews = 0
        average_rating = 0.0
    
    # 평점 분포
    rating_dist = {str(i): 0 for i in range(1, 6)}
    
    distribution = (
        db.query(
            models.Review.rating,
            func.count(models.Review.id).label('count')
        )
        .join(OrderItem, models.Review.order_item_id == OrderItem.id)
        .filter(
            and_(
                OrderItem.product_option_type == product_option_type,
                OrderItem.product_option_id == product_option_id
            )
        )
        .group_by(models.Review.rating)
        .all()
    )
    
    for rating, count in distribution:
        rating_dist[str(rating)] = count
    
    return schemas.ReviewStats(
        total_reviews=total_reviews,
        average_rating=round(average_rating, 2),
        rating_distribution=rating_dist
    )


def get_review_stats_by_user(db: Session, user_id: int) -> dict:
    """
    사용자별 리뷰 통계
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
    
    Returns:
        사용자 리뷰 통계
    """
    result = (
        db.query(
            func.count(models.Review.id).label('total'),
            func.avg(models.Review.rating).label('avg_rating')
        )
        .filter(models.Review.user_id == user_id)
        .first()
    )
    
    # result가 None이 아닌 경우에만 접근
    if result:
        total_reviews = result[0] if result[0] is not None else 0
        average_rating = float(result[1]) if result[1] is not None else 0.0
    else:
        total_reviews = 0
        average_rating = 0.0
    
    return {
        "total_reviews": total_reviews,
        "average_rating": round(average_rating, 2)
    }


# ============================================
# Validation Functions
# ============================================

def verify_review_ownership(
    db: Session,
    review_id: int,
    user_id: int
) -> bool:
    """
    리뷰 소유권 확인
    
    Args:
        db: 데이터베이스 세션
        review_id: 리뷰 ID
        user_id: 사용자 ID
    
    Returns:
        소유권 여부
    """
    review = db.query(models.Review).filter(
        and_(
            models.Review.id == review_id,
            models.Review.user_id == user_id
        )
    ).first()
    
    return review is not None


def can_write_review(
    db: Session,
    user_id: int,
    order_item_id: int
) -> bool:
    """
    리뷰 작성 가능 여부 확인
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        order_item_id: 주문 항목 ID
    
    Returns:
        작성 가능 여부
    """
    # 주문 항목이 해당 사용자의 것인지 확인
    order_item = (
        db.query(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(
            and_(
                OrderItem.id == order_item_id,
                Order.user_id == user_id
            )
        )
        .first()
    )
    
    if not order_item:
        return False
    
    # 이미 리뷰가 작성되었는지 확인
    existing_review = get_review_by_order_item_id(db, order_item_id)
    
    return existing_review is None
