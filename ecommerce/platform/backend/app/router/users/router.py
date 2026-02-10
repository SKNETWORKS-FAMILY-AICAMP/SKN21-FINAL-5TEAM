from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.users.models import UserStatus
from ecommerce.platform.backend.app.router.users import crud, schemas

router = APIRouter(
    # prefix="/users",
    tags=["Users"],
)

# =========================
# auth helper (세션 기반)
# =========================

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )

    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    return user


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
    db: Session = Depends(get_db),
):
    user = crud.get_user_by_email(db, body.email)
    if not user:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다.")

    if not user.password_hash or not crud.verify_password(
        body.password, user.password_hash
    ):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다.")

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    request.session["user_id"] = user.id

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
    }


@router.post("/logout", response_model=schemas.SimpleOkResponse)
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


# =========================
# Profile (me)
# =========================

@router.get("/me", response_model=schemas.MeResponse)
def me(current_user=Depends(get_current_user)):
    return schemas.MeResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        phone=current_user.phone,
        agree_marketing=current_user.agree_marketing,
        agree_sms=current_user.agree_sms,
        agree_email=current_user.agree_email,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )


@router.patch("/me", response_model=schemas.UserProfileUpdateResponse)
def update_my_profile(
    body: schemas.UserProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
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


@router.put("/me/body-measurement", response_model=schemas.BodyMeasurementUpsertResponse)
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

@router.delete("/me", response_model=schemas.SimpleOkResponse)
def withdraw(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    crud.withdraw_user(db, current_user)
    return {"ok": True}

# =========================
