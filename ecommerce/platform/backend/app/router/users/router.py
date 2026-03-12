from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse

from ecommerce.platform.backend.app.core.auth import create_access_token
from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.users.models import UserStatus
from ecommerce.platform.backend.app.router.users import crud, schemas
from ecommerce.platform.backend.app.router.users.models import User, UserRole
from ecommerce.platform.backend.app.core.auth import (
    get_current_user,
    get_current_user_optional,
)

import os
from authlib.integrations.starlette_client import OAuth
from fastapi.responses import RedirectResponse
from ecommerce.platform.backend.app.router.user_history import (
    crud as user_history_crud,
    schemas as user_history_schemas,
)
import json
from datetime import datetime

router = APIRouter(
    # prefix="/users",
    tags=["Users"],
)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")

# =========================
# Admin - 전체 유저 조회
# =========================


@router.get("/all", response_model=list[schemas.UserListItem])
def list_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다.")
    return crud.get_all_users(db)


# =========================
# Auth / Register / Login
# =========================


@router.post("/check-email", response_model=schemas.CheckEmailResponse)
def check_email(body: schemas.CheckEmailRequest, db: Session = Depends(get_db)):
    return {"available": crud.is_email_available(db, body.email)}


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.SimpleOkResponse,
)
def register(body: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if not crud.is_email_available(db, body.email):
        raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다.")

    crud.create_user(
        db=db,
        email=body.email,
        password=body.password,
        name=body.name,
        phone=body.phone,
        agree_marketing_info=body.agree_marketing_info,
        agree_ad_sms=body.agree_ad_sms,
        agree_ad_email=body.agree_ad_email,
    )
    return {"ok": True}


@router.post("/login", response_model=schemas.LoginResponse)
def login(
    body: schemas.LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    user = crud.get_user_by_email(db, body.email)
    if not user or not user.password_hash:
        raise HTTPException(
            status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다."
        )

    if not crud.verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다."
        )

    user.last_login_at = datetime.utcnow()
    user_history_crud.track_auth_action(
        db=db,
        user_id=user.id,
        action_type=user_history_schemas.ActionType.LOGIN,
        action_metadata=json.dumps(
            {"user": user.name, "timestamp": datetime.utcnow().isoformat()},
            ensure_ascii=False,
        ),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    access_token = create_access_token(user.id)

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        max_age=60 * 60 * 24 * 7,
    )

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
    }


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_history_crud.track_auth_action(
        db=db,
        user_id=current_user.id,
        action_type=user_history_schemas.ActionType.LOGOUT,
        action_metadata=json.dumps(
            {"user": current_user.name, "timestamp": datetime.utcnow().isoformat()},
            ensure_ascii=False,
        ),
    )

    response.delete_cookie(
        key="access_token",
        path="/",
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )

    return {"ok": True}


# =========================
# Cart
@router.post("/cart")
def add_to_cart(
    current_user: User = Depends(get_current_user),
):
    return {"user_id": current_user.id}


# =========================
# Profile (me)
# =========================


@router.get("/me")
def me(current_user: User | None = Depends(get_current_user_optional)):
    if current_user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "id": current_user.id,
        "email": current_user.email,
        "gender": current_user.gender.value if current_user.gender else None,
        "name": current_user.name,
        "phone": current_user.phone,
        "agree_marketing": current_user.agree_marketing,
        "agree_sms": current_user.agree_sms,
        "agree_email": current_user.agree_email,
        "created_at": current_user.created_at,
        "updated_at": current_user.updated_at,
    }


@router.patch("/me", response_model=schemas.UserProfileUpdateResponse)
def update_my_profile(
    body: schemas.UserProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.email is not None and body.email != current_user.email:
        if not crud.is_email_available(db, body.email):
            raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다.")

    updated = crud.update_user_profile(
        db,
        current_user,
        email=body.email,
        name=body.name,
        phone=body.phone,
    )

    return {
        "ok": True,
        "user": schemas.MeResponse(
            id=updated.id,
            email=updated.email,
            name=updated.name,
            phone=updated.phone,
            agree_marketing=updated.agree_marketing,
            agree_sms=updated.agree_sms,
            agree_email=updated.agree_email,
            gender=updated.gender.value if updated.gender else None,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        ),
    }


@router.patch("/me/password", response_model=schemas.SimpleOkResponse)
def change_password(
    body: schemas.ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        crud.change_password(
            db,
            current_user,
            body.current_password,
            body.new_password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True}


# =========================
# Notification
# =========================


@router.get("/me/notification", response_model=schemas.NotificationSettingResponse)
def get_notification(current_user=Depends(get_current_user)):
    return {
        "agree_marketing": current_user.agree_marketing,
        "agree_sms": current_user.agree_sms,
        "agree_email": current_user.agree_email,
    }


@router.patch("/me/notification", response_model=schemas.SimpleOkResponse)
def update_notification(
    body: schemas.NotificationSettingUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    crud.update_notification_settings(
        db,
        current_user,
        agree_marketing=body.agree_marketing,
        agree_sms=body.agree_sms,
        agree_email=body.agree_email,
    )
    return {"ok": True}


# =========================
# Body Measurement
# =========================


@router.get("/me/body-measurement", response_model=schemas.BodyMeasurementResponse)
def get_body_measurement(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    m = crud.get_body_measurement(db, current_user.id)
    if not m:
        raise HTTPException(status_code=404, detail="신체 치수 정보가 없습니다.")

    return schemas.BodyMeasurementResponse.from_orm(m)


@router.put(
    "/me/body-measurement", response_model=schemas.BodyMeasurementUpsertResponse
)
def upsert_body_measurement(
    body: schemas.BodyMeasurementUpsertRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    m = crud.upsert_body_measurement(
        db,
        current_user.id,
        body.model_dump(exclude_unset=True),
    )
    return {"ok": True, "measurement": schemas.BodyMeasurementResponse.from_orm(m)}


# =========================
# Withdraw
# =========================


@router.delete("/me")
def withdraw(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    crud.withdraw_user(db, current_user)

    response = JSONResponse(content={"ok": True})
    response.delete_cookie("access_token", path="/", samesite=COOKIE_SAMESITE, secure=COOKIE_SECURE)
    response.delete_cookie("session", path="/", samesite=COOKIE_SAMESITE, secure=COOKIE_SECURE)

    return response


# =========================
@router.get("/auth/google/login")
async def google_login(request: Request):
    # 현재 요청의 호스트를 기준으로 콜백 URL을 동적으로 구성해 state mismatch를 방지
    redirect_uri = str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")

    if not user_info:
        raise HTTPException(status_code=400, detail="Google 사용자 정보 조회 실패")

    google_id = user_info["sub"]
    email = user_info["email"]
    name = user_info.get("name")

    # 1️⃣ google_id 기준 조회
    user = db.query(User).filter(User.google_id == google_id).first()

    # 2️⃣ 없으면 신규 생성
    if not user:
        user = User(
            email=email,
            name=name,
            google_id=google_id,
            password_hash=None,
            status=UserStatus.ACTIVE,
            role=UserRole.USER,
            agree_marketing=False,
            agree_sms=False,
            agree_email=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    user_history_crud.track_auth_action(
        db=db,
        user_id=user.id,
        action_type=user_history_schemas.ActionType.LOGIN,
        action_metadata=json.dumps(
            {"user": user.name, "timestamp": datetime.utcnow().isoformat()},
            ensure_ascii=False,
        ),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    user.last_login_at = datetime.utcnow()
    db.commit()

    # 4️⃣ JWT 발급
    access_token = create_access_token(user.id)

    response = RedirectResponse(url="/")
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        max_age=60 * 60 * 24 * 7,
    )

    return response
