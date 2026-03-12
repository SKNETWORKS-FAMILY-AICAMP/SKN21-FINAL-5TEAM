# app/router/shipping/router.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.shipping import crud, schemas
from ecommerce.platform.backend.app.router.orders.models import Order
from ecommerce.platform.backend.app.router.orders.schemas import OrderStatus

router = APIRouter(
    tags=["shipping"]
)


# =====================
# 배송지 목록 조회
# =====================
@router.get("", response_model=List[schemas.ShippingAddressResponse])
def list_shipping(user_id: int, db: Session = Depends(get_db)):
    return crud.get_shipping_addresses(db, user_id)


# =====================
# 배송지 생성
# =====================
@router.post("", response_model=schemas.ShippingAddressResponse)
def add_shipping(user_id: int, address: schemas.ShippingAddressCreate, db: Session = Depends(get_db)):
    return crud.create_shipping_address(db, user_id, address)


# =====================
# 배송지 수정
# =====================
@router.put("/{address_id}", response_model=schemas.ShippingAddressResponse)
def edit_shipping(address_id: int, address: schemas.ShippingAddressUpdate, db: Session = Depends(get_db)):
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
@router.patch("/{address_id}/default", response_model=schemas.ShippingAddressResponse)
def set_default(address_id: int, db: Session = Depends(get_db)):
    updated = crud.set_default_shipping_address(db, address_id)
    if not updated:
        raise HTTPException(status_code=404, detail="배송지를 찾을 수 없습니다.")
    return updated


# =====================
# 주문별 배송 정보 조회
# =====================
@router.get("/order/{order_id}", response_model=Optional[schemas.ShippingInfoResponse])
def get_shipping_info(order_id: int, db: Session = Depends(get_db)):
    return crud.get_shipping_info_by_order_id(db, order_id)


# =====================
# 배송 정보 전체 목록 조회 (관리자용)
# =====================
@router.get("/info/all", response_model=List[schemas.ShippingInfoResponse])
def list_all_shipping_info(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    return crud.get_all_shipping_info(db, skip, limit)


# =====================
# 배송 정보 생성
# =====================
@router.post("/info", response_model=schemas.ShippingInfoResponse, status_code=201)
def create_shipping_info(
    data: schemas.ShippingInfoCreate,
    db: Session = Depends(get_db)
):
    existing = crud.get_shipping_info_by_order_id(db, data.order_id)
    if existing:
        raise HTTPException(status_code=400, detail="해당 주문에 이미 배송 정보가 존재합니다.")

    # 주문 상태를 '상품 준비중'으로 변경 (취소/환불 상태는 유지)
    order = db.query(Order).filter(Order.id == data.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    if order.status not in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
        order.status = OrderStatus.PREPARING

    shipping_info = crud.create_shipping_info(db, data)
    return shipping_info


# =====================
# 배송 정보 수정
# =====================
@router.put("/info/{shipping_info_id}", response_model=schemas.ShippingInfoResponse)
def update_shipping_info(
    shipping_info_id: int,
    data: schemas.ShippingInfoUpdate,
    db: Session = Depends(get_db)
):
    updated = crud.update_shipping_info(db, shipping_info_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="배송 정보를 찾을 수 없습니다.")
    return updated


# =====================
# 관리자용 주문 상태 변경 (배송중, 배송완료)
# =====================
@router.patch("/order/{order_id}/status")
def update_order_status_by_admin(
    order_id: int,
    status: str,
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")

    allowed = {"preparing", "shipped", "delivered"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="허용되지 않는 상태입니다. (preparing, shipped, delivered)")

    order.status = OrderStatus(status)
    db.commit()
    db.refresh(order)

    return {"order_id": order.id, "status": order.status.value, "message": "주문 상태가 변경되었습니다."}
