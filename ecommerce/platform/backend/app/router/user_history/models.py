"""
SQLAlchemy Models - User History Module
사용자 행동 히스토리 관련 모델
"""
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from enum import Enum as PyEnum
import json

from sqlalchemy import (
    BigInteger, String, Text, DateTime, Enum, ForeignKey, Index, select
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy import event

from ecommerce.platform.backend.app.database import Base
from ecommerce.platform.backend.app.router.carts.models import Cart, CartItem

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.users.models import User
    from ecommerce.platform.backend.app.router.orders.models import Order


# ==================================================
# Enums
# ==================================================

class ActionType(str, PyEnum):
    """사용자 행동 유형"""
    # 인증 관련
    LOGIN = "login"
    LOGOUT = "logout"

    # 장바구니 관련
    CART_ADD = "cart_add"
    CART_DEL = "cart_del"

    # 주문 관련
    PAYMENT = "payment"  # 결제 완료
    ORDER_DEL = "order_del"

    # 환불 관련
    ORDER_RE = "order_re"

    # 리뷰 관련
    REVIEW_CREATE = "review_create"


# ==================================================
# User History Models
# ==================================================

class UserHistory(Base):
    """사용자 행동 히스토리"""
    __tablename__ = "userhistory"
    __table_args__ = (
        # 성능 최적화를 위한 인덱스
        Index('idx_user_id', 'user_id'),
        Index('idx_action_type', 'action_type'),
        Index('idx_user_action', 'user_id', 'action_type'),
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_created_at', 'created_at'),
        # 상품 관련 행동 조회 최적화
        Index('idx_product_option', 'product_option_type', 'product_option_id'),
        {'comment': '사용자 행동 히스토리'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment='히스토리 고유 ID'
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, comment='회원 ID'
    )

    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, comment='행동 유형'
    )

    # 선택적 외래키 (행동에 따라 다르게 사용)
    product_option_type: Mapped[Optional[str]] = mapped_column(
        String(20), comment='상품 옵션 유형 (new/used)'
    )

    product_option_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='상품 옵션 ID'
    )

    order_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('orders.id', ondelete='SET NULL'),
        comment='관련 주문 ID'
    )

    cart_item_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey('cartitems.id', ondelete='SET NULL'),
        comment='관련 장바구니 항목 ID'
    )

    # JSON 형태의 메타데이터 (유연성 확보)
    action_metadata: Mapped[Optional[str]] = mapped_column(
        Text, comment='추가 메타데이터 (JSON 형식)'
    )

    # 검색어 저장
    search_keyword: Mapped[Optional[str]] = mapped_column(
        String(255), comment='검색 키워드'
    )

    # IP 주소 (선택사항)
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), comment='IP 주소 (IPv4/IPv6)'
    )

    # User Agent (선택사항)
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text, comment='User Agent 정보'
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        comment='행동 발생 시각'
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="user_history"
    )

    order: Mapped[Optional["Order"]] = relationship(
        "Order",
        back_populates="user_history"
    )


@event.listens_for(CartItem, "after_insert")
def log_cart_item_history(mapper, connection, target):
    """
    CartItem이 새로 생성될 때 UserHistory에 CART_ADD 기록을 삽입합니다.
    """
    from ecommerce.platform.backend.app.router.users.models import User
    from ecommerce.platform.backend.app.router.products.models import (
        ProductOption, Product, UsedProductOption, UsedProduct
    )

    cart_tbl = Cart.__table__
    user_id = connection.execute(
        select(cart_tbl.c.user_id).where(cart_tbl.c.id == target.cart_id)
    ).scalar_one_or_none()

    if not user_id:
        return

    # 사용자 이름 조회
    user_tbl = User.__table__
    user_name = connection.execute(
        select(user_tbl.c.name).where(user_tbl.c.id == user_id)
    ).scalar_one_or_none()

    history_tbl = UserHistory.__table__
    product_option_type = (
        target.product_option_type.value
        if hasattr(target.product_option_type, "value")
        else target.product_option_type
    )

    # 상품명 조회
    cart_item_name = None
    if product_option_type == "new":
        option_tbl = ProductOption.__table__
        product_tbl = Product.__table__
        cart_item_name = connection.execute(
            select(product_tbl.c.name)
            .select_from(option_tbl.join(product_tbl, option_tbl.c.product_id == product_tbl.c.id))
            .where(option_tbl.c.id == target.product_option_id)
        ).scalar_one_or_none()
    else:
        upo_tbl = UsedProductOption.__table__
        up_tbl = UsedProduct.__table__
        cart_item_name = connection.execute(
            select(up_tbl.c.name)
            .select_from(upo_tbl.join(up_tbl, upo_tbl.c.used_product_id == up_tbl.c.id))
            .where(upo_tbl.c.id == target.product_option_id)
        ).scalar_one_or_none()

    action_data = {
        "quantity": target.quantity,
        "userName": user_name,
        "cartItemName": cart_item_name,
        "timestamp": datetime.now().isoformat()
    }

    connection.execute(
        history_tbl.insert().values(
            user_id=user_id,
            action_type=ActionType.CART_ADD.value,
            product_option_type=product_option_type,
            product_option_id=target.product_option_id,
            cart_item_id=target.id,
            action_metadata=json.dumps(action_data, ensure_ascii=False)
        )
    )
