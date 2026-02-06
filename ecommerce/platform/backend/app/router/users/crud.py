from sqlalchemy.orm import Session
from passlib.context import CryptContext
from .models import User

pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")

# ===== util =====

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

# ===== queries =====

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
    address1: str | None,
    address2: str | None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name,
        phone=phone,
        address1=address1,
        address2=address2,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
