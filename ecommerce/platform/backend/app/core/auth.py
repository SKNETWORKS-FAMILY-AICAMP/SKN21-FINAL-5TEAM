# backend/app/core/auth.py

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request, Depends, HTTPException, status
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.users.models import User

# =========================
# JWT 설정
# =========================
SECRET_KEY = "CHANGE_THIS_TO_ENV_SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7  # 로그인 유지 기간

# =========================
# 토큰 생성
# =========================
def create_access_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# =========================
# 현재 로그인 유저
# =========================
def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    if user.status != "active":
        raise HTTPException(status_code=401, detail="Inactive user")

    return user


# =========================
# 현재 로그인 유저 (Optional - 비로그인 시 None 반환)
# =========================
def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    token = request.cookies.get("access_token")
    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            return None
    except JWTError:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.status != "active":
        return None

    return user
