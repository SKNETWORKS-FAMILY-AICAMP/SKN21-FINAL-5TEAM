from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from .models import User, UserBodyMeasurement, UserStatus

pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")

# =========================
# util
# =========================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# =========================
# user queries
# =========================

def get_user_by_id(db: Session, user_id: int) -> User | None:
    return (
        db.query(User)
        .filter(
            User.id == user_id,
            User.deleted_at.is_(None),
        )
        .first()
    )


def get_user_by_email(db: Session, email: str) -> User | None:
    return (
        db.query(User)
        .filter(
            User.email == email,
            User.deleted_at.is_(None),
        )
        .first()
    )


def is_email_available(db: Session, email: str) -> bool:
    return get_user_by_email(db, email) is None


def create_user(
    db: Session,
    email: str,
    password: str,
    name: str,
    phone: str | None,
    agree_marketing_info: bool = False,
    agree_ad_sms: bool = False,
    agree_ad_email: bool = False,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name,
        phone=phone,
        agree_marketing=agree_marketing_info,
        agree_sms=agree_ad_sms,
        agree_email=agree_ad_email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# =========================
# profile
# =========================

def update_user_profile(
    db: Session,
    user: User,
    *,
    email: str | None = None,
    name: str | None = None,
    phone: str | None = None,
) -> User:
    if email is not None:
        user.email = email
    if name is not None:
        user.name = name
    if phone is not None:
        user.phone = phone

    db.commit()
    db.refresh(user)
    return user


def change_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    if not user.password_hash:
        raise ValueError("비밀번호가 설정되어 있지 않습니다.")

    if not verify_password(current_password, user.password_hash):
        raise ValueError("현재 비밀번호가 일치하지 않습니다.")

    user.password_hash = hash_password(new_password)
    db.commit()


# =========================
# notification
# =========================

def update_notification_settings(
    db: Session,
    user: User,
    *,
    agree_marketing: bool | None = None,
    agree_sms: bool | None = None,
    agree_email: bool | None = None,
) -> User:
    if agree_marketing is not None:
        user.agree_marketing = agree_marketing
    if agree_sms is not None:
        user.agree_sms = agree_sms
    if agree_email is not None:
        user.agree_email = agree_email

    db.commit()
    db.refresh(user)
    return user


# =========================
# body measurement
# =========================

def get_body_measurement(db: Session, user_id: int) -> UserBodyMeasurement | None:
    return (
        db.query(UserBodyMeasurement)
        .filter(UserBodyMeasurement.user_id == user_id)
        .first()
    )


def upsert_body_measurement(
    db: Session,
    user_id: int,
    data: dict,
) -> UserBodyMeasurement:
    m = get_body_measurement(db, user_id)

    if m is None:
        m = UserBodyMeasurement(user_id=user_id, **data)
        db.add(m)
        db.commit()
        db.refresh(m)
        return m

    for k, v in data.items():
        setattr(m, k, v)

    db.commit()
    db.refresh(m)
    return m


# =========================
# withdraw (soft delete)
# =========================

def withdraw_user(db: Session, user: User) -> None:
    user.status = UserStatus.INACTIVE
    user.deleted_at = datetime.utcnow()
    db.commit()

# =========================