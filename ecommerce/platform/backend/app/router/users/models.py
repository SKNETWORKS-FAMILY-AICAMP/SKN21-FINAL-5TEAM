"""
SQLAlchemy Models - Users Module
회원 및 신체 치수 관련 모델
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, String, Boolean, DateTime, Enum, ForeignKey, Numeric, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base

if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress
    from ecommerce.platform.backend.app.router.carts.models import Cart
    from ecommerce.platform.backend.app.router.orders.models import Order
    from ecommerce.platform.backend.app.router.products.models import UsedProduct
    from ecommerce.platform.backend.app.router.points.models import PointHistory, IssuedVoucher
    from ecommerce.platform.backend.app.router.reviews.models import Review
    from ecommerce.platform.backend.app.router.user_history.models import UserHistory


# ==================================================
# Enums
# ==================================================

class UserStatus(str, PyEnum):
    """사용자 상태"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class UserRole(str, PyEnum):
    """사용자 권한"""
    USER = "user"
    ADMIN = "admin"


# ==================================================
# User Models
# ==================================================

class User(Base):
    """회원 정보"""
    __tablename__ = "users"
    __table_args__ = (
        Index('idx_email', 'email'),
        {'comment': '회원 정보'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='회원 고유 ID'
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, comment='이메일 (로그인용) - 고유값'
    )
    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255), comment='암호화된 비밀번호'
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment='회원 이름'
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(20), comment='핸드폰번호'
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, values_callable=lambda x: [e.value for e in x]),
        default=UserStatus.ACTIVE, comment='계정상태'
    )
    address1: Mapped[Optional[str]] = mapped_column(
        String(255), comment='주소1 (기본 주소)'
    )
    address2: Mapped[Optional[str]] = mapped_column(
        String(255), comment='주소2 (상세 주소)'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), comment='수정일시'
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='마지막 로그인 일시'
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment='삭제 일시 (소프트 삭제)'
    )
    agree_marketing: Mapped[bool] = mapped_column(
        Boolean, default=False, comment='마케팅 목적 개인정보 수집 동의'
    )
    agree_sms: Mapped[bool] = mapped_column(
        Boolean, default=False, comment='광고성 문자 수신 동의'
    )
    agree_email: Mapped[bool] = mapped_column(
        Boolean, default=False, comment='광고성 이메일 수신 동의'
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]),
        default=UserRole.USER, comment='사용자 권한 (user/admin)'
    )

    # Relationships
    body_measurement: Mapped[Optional["UserBodyMeasurement"]] = relationship(
        "UserBodyMeasurement",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False
    )
    shipping_addresses: Mapped[List["ShippingAddress"]] = relationship(
        "ShippingAddress",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    carts: Mapped[List["Cart"]] = relationship(
        "Cart",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    orders: Mapped[List["Order"]] = relationship(
        "Order",
        back_populates="user"
    )
    used_products: Mapped[List["UsedProduct"]] = relationship(
        "UsedProduct",
        back_populates="seller",
        cascade="all, delete-orphan"
    )
    point_history: Mapped[List["PointHistory"]] = relationship(
        "PointHistory",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    issued_vouchers: Mapped[List["IssuedVoucher"]] = relationship(
        "IssuedVoucher",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    reviews: Mapped[List["Review"]] = relationship(
        "Review",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    user_history: Mapped[List["UserHistory"]] = relationship(
        "UserHistory",
        back_populates="user",
        cascade="all, delete-orphan"
    )


class UserBodyMeasurement(Base):
    """사용자 신체 치수"""
    __tablename__ = "userbodymeasurements"
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        {'comment': '사용자 신체 치수'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='신체 치수 고유 ID'
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('users.id', ondelete='CASCADE'),
        unique=True, nullable=False, comment='회원 ID (1:1 관계)'
    )
    height: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='키 (cm)'
    )
    weight: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='몸무게 (kg)'
    )
    upper_total_length: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='상체 총장 (cm)'
    )
    shoulder_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='어깨너비 (cm)'
    )
    chest_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='가슴단면 (cm)'
    )
    sleeve_length: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='소매길이 (cm)'
    )
    lower_total_length: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='하체 총장 (cm)'
    )
    waist_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='허리단면 (cm)'
    )
    hip_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='엉덩이단면 (cm)'
    )
    thigh_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='허벅지단면 (cm)'
    )
    rise: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='밑위 (cm)'
    )
    hem_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), comment='밑단단면 (cm)'
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
        back_populates="body_measurement"
    )

# =========================