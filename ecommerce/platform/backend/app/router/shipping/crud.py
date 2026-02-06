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
    """사용자의 모든 배송지 조회 (삭제되지 않은 것만)"""
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
    """특정 배송지 조회"""
    return (
        db.query(ShippingAddress)
        .filter(ShippingAddress.id == address_id, ShippingAddress.deleted_at.is_(None))
        .first()
    )


# =====================
# 배송지 생성
# =====================
def create_shipping_address(db: Session, user_id: int, address: ShippingAddressCreate) -> ShippingAddress:
    """새 배송지 생성"""
    new_address = ShippingAddress(user_id=user_id, **address.model_dump())
    
    # 기본 배송지로 설정하는 경우, 기존 기본 배송지 해제
    if new_address.is_default:
        db.query(ShippingAddress).filter(
            ShippingAddress.user_id == user_id,
            ShippingAddress.is_default == True,
            ShippingAddress.deleted_at.is_(None)
        ).update({"is_default": False})

    db.add(new_address)
    db.commit()
    db.refresh(new_address)
    return new_address


# =====================
# 배송지 수정
# =====================
def update_shipping_address(
    db: Session, 
    address_id: int, 
    address: ShippingAddressUpdate
) -> Optional[ShippingAddress]:
    """배송지 정보 수정"""
    db_address = get_shipping_address(db, address_id)
    if not db_address:
        return None
    
    # 업데이트할 데이터만 추출 (None이 아닌 값만)
    update_data = address.model_dump(exclude_unset=True)
    
    # 기본 배송지로 변경하는 경우
    if update_data.get("is_default") is True:
        db.query(ShippingAddress).filter(
            ShippingAddress.user_id == db_address.user_id,
            ShippingAddress.id != address_id,
            ShippingAddress.is_default == True,
            ShippingAddress.deleted_at.is_(None)
        ).update({"is_default": False})
    
    # 배송지 정보 업데이트
    for key, value in update_data.items():
        setattr(db_address, key, value)
    
    db.commit()
    db.refresh(db_address)
    return db_address


# =====================
# 배송지 삭제 (소프트 삭제)
# =====================
def delete_shipping_address(db: Session, address_id: int) -> bool:
    """배송지 소프트 삭제 (deleted_at 설정)"""
    db_address = get_shipping_address(db, address_id)
    if not db_address:
        return False
    
    # 소프트 삭제
    db_address.deleted_at = datetime.utcnow()
    db.commit()
    return True


# =====================
# 기본 배송지 설정
# =====================
def set_default_shipping_address(db: Session, address_id: int) -> Optional[ShippingAddress]:
    """특정 배송지를 기본 배송지로 설정"""
    db_address = get_shipping_address(db, address_id)
    if not db_address:
        return None
    
    # 해당 사용자의 모든 배송지의 기본 설정 해제
    db.query(ShippingAddress).filter(
        ShippingAddress.user_id == db_address.user_id,
        ShippingAddress.id != address_id,
        ShippingAddress.is_default == True,
        ShippingAddress.deleted_at.is_(None)
    ).update({"is_default": False})
    
    # 선택한 배송지를 기본으로 설정
    db_address.is_default = True
    db.commit()
    db.refresh(db_address)
    return db_address


# =====================
# 기본 배송지 조회
# =====================
def get_default_shipping_address(db: Session, user_id: int) -> Optional[ShippingAddress]:
    """사용자의 기본 배송지 조회"""
    return (
        db.query(ShippingAddress)
        .filter(
            ShippingAddress.user_id == user_id,
            ShippingAddress.is_default == True,
            ShippingAddress.deleted_at.is_(None)
        )
        .first()
    )
