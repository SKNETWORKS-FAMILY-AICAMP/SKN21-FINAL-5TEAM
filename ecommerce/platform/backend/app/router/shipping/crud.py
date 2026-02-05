# app/router/shipping/crud.py

from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional

# 같은 폴더 기준 import
from .models import ShippingAddress
from .schema import ShippingAddressCreate, ShippingAddressUpdate


# =====================
# 배송지 목록 조회
# =====================
def get_shipping_addresses(db: Session, user_id: int) -> List[ShippingAddress]:
    return (
        db.query(ShippingAddress)
        .filter(ShippingAddress.user_id == user_id, ShippingAddress.deleted_at.is_(None))
        .order_by(ShippingAddress.is_default.desc(), ShippingAddress.created_at.desc())
        .all()
    )


# =====================
# 단일 배송지 조회
# =====================
def get_shipping_address(db: Session, address_id: int) -> Optional[ShippingAddress]:
    return (
        db.query(ShippingAddress)
        .filter(ShippingAddress.id == address_id, ShippingAddress.deleted_at.is_(None))
        .first()
    )


# =====================
# 배송지 생성
# =====================
def create_shipping_address(
    db: Session, user_id: int, address: ShippingAddressCreate
) -> ShippingAddress:
    new_address = ShippingAddress(user_id=user_id, **address.model_dump())

    # 기본 배송지 처리
    if new_address.is_default:
        db.query(ShippingAddress).filter(
            ShippingAddress.user_id == user_id,
            ShippingAddress.is_default == True
        ).update({"is_default": False})

    db.add(new_address)
    db.commit()
