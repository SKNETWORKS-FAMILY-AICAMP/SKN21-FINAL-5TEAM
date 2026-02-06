"""
SQLAlchemy Models - User & Body Measurement
FastAPI + SQLAlchemy ORM (2.0 style)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
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

from database import Base


# ==================================================
# TYPE CHECKING (for IDE / mypy / pyright)
# ==================================================
if TYPE_CHECKING:
    from .models import UserBodyMeasurement


# ==================================================
# Enums
# ==================================================
class UserStatus(str, PyEnum):
    """사용자 계정 상태"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


# ==================================================
# User
# ==================================================
class User(Base):
    """회원 정보"""
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_email", "email"),
        {"comment": "회원 정보"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="회원 고유 ID",
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="이메일 (로그인 ID)",
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="암호화된 비밀번호",
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="회원 이름",
    )

    phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        comment="휴대폰 번호",
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

    address2: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="주소2 (상세 주소)",
    )

    # 약관 동의
    agree_marketing: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="마케팅 목적 개인정보 수집 동의",
    )
    agree_sms: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="광고성 문자 수신 동의",
    )
    agree_email: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="광고성 이메일 수신 동의",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        comment="가입일시",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment="정보 수정일시",
    )

    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        comment="마지막 로그인 일시",
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        comment="탈퇴 일시 (소프트 삭제)",
    )

    # Relationships (1:1)
    body_measurement: Mapped[Optional["UserBodyMeasurement"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )


# ==================================================
# User Body Measurement
# ==================================================
class UserBodyMeasurement(Base):
    """사용자 신체 치수"""
    __tablename__ = "user_body_measurements"
    __table_args__ = (
        Index("idx_ubm_user_id", "user_id"),
        {"comment": "회원 신체 치수"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="신체 치수 ID",
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        comment="회원 ID (1:1)",
    )

    # 기본 정보
    height: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="키 (cm)",
    )
    weight: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="몸무게 (kg)",
    )

    # 상체
    shoulder_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="어깨너비 (cm)",
    )
    chest_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="가슴단면 (cm)",
    )
    sleeve_length: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="소매길이 (cm)",
    )

    # 하체
    waist_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="허리단면 (cm)",
    )
    hip_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="엉덩이단면 (cm)",
    )
    thigh_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="허벅지단면 (cm)",
    )
    hem_width: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        comment="밑단단면 (cm)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        comment="등록일시",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        comment="수정일시",
    )

    # Relationships
    user: Mapped["User"] = relationship(
        back_populates="body_measurement"
    )
