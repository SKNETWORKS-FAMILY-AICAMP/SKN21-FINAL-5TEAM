from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from router.users.models import UserStatus
from . import crud, schemas

router = APIRouter()


# =========================
# auth helper (임시)
# - 토큰 구현 전까지는 X-User-Id 헤더로 현재 유저를 식별
# =========================

def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
):
    if x_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-Id 헤더가 필요합니다.",
        )

    user = crud.get_user_by_id(db, x_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    return user


# =========================
# 기존 기능 유지
# =========================

@router.post("/check-email", response_model=schemas.CheckEmailResponse)
def check_email(body: schemas.CheckEmailRequest, db: Session = Depends(get_db)):
    available = crud.is_email_available(db, body.email)
    return {"available": available}


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=schemas.SimpleOkResponse)
def register(body: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if not crud.is_email_available(db, body.email):
        raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다.")

    crud.create_user(
        db=db,
        email=body.email,
        password=body.password,
        name=body.name,
        phone=body.phone,
        address1=body.address1,
        address2=body.address2,
        agree_marketing_info=body.agree_marketing_info,
        agree_ad_sms=body.agree_ad_sms,
        agree_ad_email=body.agree_ad_email,
    )
    return {"ok": True}


@router.post("/login", response_model=schemas.LoginResponse)
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, body.email)
    if not user:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다.")

    if not user.password_hash or not crud.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다.")

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    return {"id": user.id, "email": user.email, "name": user.name}


# =========================
# Profile: 조회/변경
# =========================

@router.get("/me", response_model=schemas.MeResponse)
def me(current_user=Depends(get_current_user)):
    return schemas.MeResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        phone=current_user.phone,
        agree_marketing=getattr(current_user, "agree_marketing", False),
        agree_sms=getattr(current_user, "agree_sms", False),
        agree_email=getattr(current_user, "agree_email", False),
        address1=getattr(current_user, "address1", None),
        address2=getattr(current_user, "address2", None),
        created_at=getattr(current_user, "created_at", None),
        updated_at=getattr(current_user, "updated_at", None),
    )


@router.put("/profile", response_model=schemas.UserProfileUpdateResponse)
def update_profile(
    body: schemas.UserProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 이메일 변경 시 중복 체크
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
            agree_marketing=getattr(updated, "agree_marketing", False),
            agree_sms=getattr(updated, "agree_sms", False),
            agree_email=getattr(updated, "agree_email", False),
            address1=getattr(updated, "address1", None),
            address2=getattr(updated, "address2", None),
            created_at=getattr(updated, "created_at", None),
            updated_at=getattr(updated, "updated_at", None),
        ),
    }


@router.put("/password", response_model=schemas.SimpleOkResponse)
def change_password(
    body: schemas.ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        crud.change_password(db, current_user, body.current_password, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


# =========================
# Notification: 조회/변경 (agree_* 토글)
# =========================

@router.get("/notification", response_model=schemas.NotificationSettingResponse)
def get_notification(current_user=Depends(get_current_user)):
    return {
        "agree_marketing": getattr(current_user, "agree_marketing", False),
        "agree_sms": getattr(current_user, "agree_sms", False),
        "agree_email": getattr(current_user, "agree_email", False),
    }


@router.put("/notification", response_model=schemas.SimpleOkResponse)
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
# Body Measurement: 조회/저장(업서트)
# =========================

@router.get("/body-measurement", response_model=schemas.BodyMeasurementResponse)
def get_body_measurement(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    m = crud.get_body_measurement(db, current_user.id)
    if not m:
        # 없으면 404 대신 "빈 값"으로 내려주는 방식도 가능하지만
        # 우선은 404가 프론트 처리하기 명확합니다.
        raise HTTPException(status_code=404, detail="신체 치수 정보가 없습니다.")

    return schemas.BodyMeasurementResponse(
        id=m.id,
        user_id=m.user_id,
        height=m.height,
        weight=m.weight,
        upper_total_length=m.upper_total_length,
        shoulder_width=m.shoulder_width,
        chest_width=m.chest_width,
        sleeve_length=m.sleeve_length,
        lower_total_length=m.lower_total_length,
        waist_width=m.waist_width,
        hip_width=m.hip_width,
        thigh_width=m.thigh_width,
        rise=m.rise,
        hem_width=m.hem_width,
        created_at=getattr(m, "created_at", None),
        updated_at=getattr(m, "updated_at", None),
    )


@router.put("/body-measurement", response_model=schemas.BodyMeasurementUpsertResponse)
def upsert_body_measurement(
    body: schemas.BodyMeasurementUpsertRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    data = body.model_dump(exclude_unset=True)
    m = crud.upsert_body_measurement(db, current_user.id, data)

    return {
        "ok": True,
        "measurement": schemas.BodyMeasurementResponse(
            id=m.id,
            user_id=m.user_id,
            height=m.height,
            weight=m.weight,
            upper_total_length=m.upper_total_length,
            shoulder_width=m.shoulder_width,
            chest_width=m.chest_width,
            sleeve_length=m.sleeve_length,
            lower_total_length=m.lower_total_length,
            waist_width=m.waist_width,
            hip_width=m.hip_width,
            thigh_width=m.thigh_width,
            rise=m.rise,
            hem_width=m.hem_width,
            created_at=getattr(m, "created_at", None),
            updated_at=getattr(m, "updated_at", None),
        ),
    }


# =========================
# Withdraw: 회원탈퇴(소프트 삭제)
# =========================

@router.delete("/me", response_model=schemas.SimpleOkResponse)
def withdraw(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    crud.withdraw_user(db, current_user)
    return {"ok": True}
