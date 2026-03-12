"""
SQLAlchemy Models - Reviews Module
리뷰 관련 모델
"""
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger, Text, Integer,
    DateTime, ForeignKey, CheckConstraint, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.users.models import User
    from ecommerce.platform.backend.app.router.orders.models import OrderItem


# ==================================================
# Review Model
# ==================================================

class Review(Base):
    """리뷰"""
    __tablename__ = "reviews"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_order_item_id', 'order_item_id'),
        UniqueConstraint('order_item_id', name='uk_order_item_review'),
        CheckConstraint('rating BETWEEN 1 AND 5', name='reviews_chk_1'),
        {'comment': '리뷰'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='리뷰 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )
    order_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('orderitems.id', ondelete='CASCADE'),
        nullable=False, comment='주문 항목 ID'
    )
    content: Mapped[Optional[str]] = mapped_column(
        Text, comment='리뷰 내용'
    )
    rating: Mapped[int] = mapped_column(
        Integer, nullable=False, comment='평점 (1-5)'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), comment='수정일시'
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="reviews"
    )
    order_item: Mapped["OrderItem"] = relationship(
        "OrderItem",
        back_populates="reviews"
    )
