# app/router/shipping/router.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.shipping import crud, schema

router = APIRouter(
    prefix="/shipping",
    tags=["shipping"]
)


# =====================
# 배송지 목록 조회
# =====================
@router.get("", response_model=List[schema.ShippingAddressResponse])
def list_shipping(user_id: int, db: Session = Depends(get_db)):
    return crud.get_shipping_addresses(db, user_id)


# =====================
# 배송지 생성
# =====================
@router.post("", response_model=schema.ShippingAddressResponse)
def add_shipping(user_id: int, address: schema.ShippingAddressCreate, db: Session = Depends(get_db)):
    return crud.create_shipping_address(db, user_id, address)


# =====================
# 배송지 수정
# =====================
@router.put("/{address_id}", response_model=schema.ShippingAddressResponse)
def edit_shipping(address_id: int, address: schema.ShippingAddressUpdate, db: Session = Depends(get_db)):
    updated = crud.update_shipping_address(db, address_id, address)
    if not updated:
        raise HTTPException(status_code=404, detail="배송지를 찾을 수 없습니다.")
    return updated


# =====================
# 배송지 삭제
# =====================
@router.delete("/{address_id}")
def remove_shipping(address_id: int, db: Session = Depends(get_db)):
    success = crud.delete_shipping_address(db, address_id)
    if not success:
        raise HTTPException(status_code=404, detail="배송지를 찾을 수 없습니다.")
    return {"detail": "배송지가 삭제되었습니다."}


# =====================
# 기본 배송지 설정
# =====================
@router.patch("/{address_id}/default", response_model=schema.ShippingAddressResponse)
def set_default(address_id: int, db: Session = Depends(get_db)):
    updated = crud.set_default_shipping_address(db, address_id)
    if not updated:
        raise HTTPException(status_code=404, detail="배송지를 찾을 수 없습니다.")
    return updated
