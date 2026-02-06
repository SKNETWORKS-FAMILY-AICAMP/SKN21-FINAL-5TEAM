from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
# from db.models import UserStatus
from router.users.models import UserStatus


from database import get_db
from . import crud, schemas

router = APIRouter()


@router.post("/check-email", response_model=schemas.CheckEmailResponse)
def check_email(
    body: schemas.CheckEmailRequest,
    db: Session = Depends(get_db),
):
    available = crud.is_email_available(db, body.email)
    return {"available": available}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    body: schemas.RegisterRequest,
    db: Session = Depends(get_db),
):
    if not crud.is_email_available(db, body.email):
        raise HTTPException(
            status_code=400,
            detail="이미 사용 중인 이메일입니다.",
        )

    crud.create_user(
        db=db,
        email=body.email,
        password=body.password,
        name=body.name,
        phone=body.phone,
        address1=body.address1,
        address2=body.address2,
    )
    return {"ok": True}


@router.post("/login", response_model=schemas.LoginResponse)
def login(
    body: schemas.LoginRequest,
    db: Session = Depends(get_db),
):
    user = crud.get_user_by_email(db, body.email)
    if not user:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다.")

    if not user.password_hash or not crud.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다.")

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
    }
