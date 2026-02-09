"""
SQLAlchemy Models - User & Body Measurement
FastAPI + SQLAlchemy ORM (2.0 style)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING, List
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    String,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base


# ==================================================
# TYPE CHECKING
# ==================================================
if TYPE_CHECKING:
    from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress


# ==================================================
# Enums
# ==================================================
class UserStatus(str, PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    # DELETE = "delete" # 탈퇴한 사용자


# ==================================================
# User
# ==================================================
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_email", "email"),
        {"comment": "회원 정보"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    phone: Mapped[Optional[str]] = mapped_column(
        String(20),
    )

    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            values_callable=lambda e: [i.value for i in e],
            name="user_status",
        ),
        default=UserStatus.ACTIVE,
        nullable=False,
        comment="계정 상태",
    )

    address1: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="주소1 (기본 주소)",
    )

    # Relationships
    body_measurements: Mapped[Optional["UserBodyMeasurement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    shipping_addresses: Mapped[list["ShippingAddress"]] = relationship(
        "ShippingAddress", back_populates="user", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="user"
    )
    carts: Mapped[Optional["Cart"]] = relationship(
        "Cart", back_populates="user", uselist=False
    )
    reviews: Mapped[list["Review"]] = relationship(
        "Review", back_populates="user"
    )
    point_history: Mapped[list["PointHistory"]] = relationship(
        "PointHistory", back_populates="user"
    )
    vouchers: Mapped[list["IssuedVoucher"]] = relationship(
        "IssuedVoucher", back_populates="user"
    )
    used_products: Mapped[list["UsedProduct"]] = relationship(
        "UsedProduct", back_populates="seller"
    )

    address2: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="주소2 (상세 주소)",
    )

    # 약관 동의
    agree_marketing: Mapped[bool] = mapped_column(Boolean, default=False)
    agree_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    agree_email: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # =========================
    # 탈퇴 관련
    # =========================
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        comment="회원 탈퇴 일시",
    )

    # deleted_reason: Mapped[Optional[str]] = mapped_column(
    #     String(255),
    #     comment="회원 탈퇴 사유",
    # )

    # =========================
    # Relationships
    # =========================

    # 1:1 신체 치수
    body_measurement: Mapped[Optional["UserBodyMeasurement"]] = relationship(
        "UserBodyMeasurement",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    # 1:N 배송지
    shipping_addresses: Mapped[List["ShippingAddress"]] = relationship(
        "ShippingAddress",
        back_populates="user",
        cascade="all, delete-orphan",
    )


# ==================================================
# User Body Measurement
# ==================================================
class UserBodyMeasurement(Base):
    __tablename__ = "user_body_measurements"
    __table_args__ = (
        Index("idx_ubm_user_id", "user_id"),
        {"comment": "회원 신체 치수"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    height: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    shoulder_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    chest_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    sleeve_length: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    waist_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    hip_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    thigh_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    hem_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="body_measurement",
    )
