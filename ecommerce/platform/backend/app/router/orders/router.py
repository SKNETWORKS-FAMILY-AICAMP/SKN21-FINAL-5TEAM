"""
Order Router - 주문 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional
from decimal import Decimal

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.orders import crud, schemas


router = APIRouter(
    tags=["orders"]
)


# ==================== 주문 생성 ====================

@router.post("/{user_id}/orders/from-cart", response_model=schemas.OrderDetailResponse, status_code=status.HTTP_201_CREATED)
def create_order_from_cart(
    user_id: int,
    cart_item_ids: list[int] = Query(..., description="장바구니 항목 ID 리스트"),
    shipping_address_id: int = Query(..., description="배송지 ID"),
    payment_method: str = Query(..., description="결제 수단"),
    shipping_request: Optional[str] = Query(None, description="배송 요청사항"),
    points_used: Decimal = Query(Decimal('0'), description="사용할 포인트"),
    db: Session = Depends(get_db)
):
    """
    장바구니에서 주문 생성
    - 선택된 장바구니 항목으로 주문 생성
    - 재고 차감 및 장바구니 항목 삭제
    """
    order, error = crud.create_order_from_cart(
        db=db,
        user_id=user_id,
        cart_item_ids=cart_item_ids,
        shipping_address_id=shipping_address_id,
        payment_method=payment_method,
        shipping_request=shipping_request,
        points_used=points_used
    )
    
    if error or not order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "주문 생성 실패"
        )
    
    # 주문 상세 조회
    order_detail = crud.get_order_detail(db, order.id)
    
    if not order_detail:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="주문 생성 후 조회 실패"
        )
    
    return order_detail


@router.post("/{user_id}/orders", response_model=schemas.OrderDetailResponse, status_code=status.HTTP_201_CREATED)
def create_order_direct(
    user_id: int,
    order_data: schemas.OrderCreate,
    db: Session = Depends(get_db)
):
    """
    직접 주문 생성
    - 장바구니를 거치지 않고 바로 주문
    - 재고 차감
    """
    order, error = crud.create_order_direct(
        db=db,
        user_id=user_id,
        order_data=order_data
    )
    
    if error or not order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "주문 생성 실패"
        )
    
    # 주문 상세 조회
    order_detail = crud.get_order_detail(db, order.id)
    
    if not order_detail:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="주문 생성 후 조회 실패"
        )
    
    return order_detail


# ==================== 주문 조회 ====================

@router.get("/{user_id}/orders", response_model=schemas.OrderListResponse)
def get_user_orders(
    user_id: int,
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(20, ge=1, le=100, description="조회할 개수"),
    status_filter: Optional[schemas.OrderStatus] = Query(None, alias="status", description="주문 상태 필터"),
    db: Session = Depends(get_db)
):
    """
    사용자 주문 목록 조회
    - 최신순 정렬
    - 상태별 필터링 가능
    - 페이지네이션 지원
    """
    orders, total = crud.get_orders_by_user_with_product_names(
        db=db,
        user_id=user_id,
        skip=skip,
        limit=limit,
        status=status_filter
    )
    
    page = (skip // limit) + 1 if limit > 0 else 1
    
    return schemas.OrderListResponse(
        orders=[schemas.OrderResponse.model_validate(order) for order in orders],
        total=total,
        page=page,
        page_size=limit
    )


@router.get("/{user_id}/orders/{order_id}", response_model=schemas.OrderDetailResponse)
def get_order_detail(
    user_id: int,
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    주문 상세 조회
    - 주문 항목, 배송지, 결제 정보 포함
    """
    # 소유권 확인
    if not crud.verify_order_ownership(db, order_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    order = crud.get_order_detail_with_product_names(db, order_id)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    return order


@router.get("/orders/number/{order_number}", response_model=schemas.OrderDetailResponse)
def get_order_by_number(
    order_number: str,
    db: Session = Depends(get_db)
):
    """
    주문 번호로 주문 조회
    - 주문 번호를 통한 주문 추적
    """
    order = crud.get_order_by_order_number(db, order_number)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    # 상세 정보 조회
    order_detail = crud.get_order_detail(db, order.id)
    
    if not order_detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문 상세 정보를 찾을 수 없습니다"
        )
    
    return order_detail


# ==================== 주문 상태 변경 ====================

@router.patch("/{user_id}/orders/{order_id}/status", response_model=schemas.OrderResponse)
def update_order_status(
    user_id: int,
    order_id: int,
    status_update: schemas.OrderStatusUpdate,
    db: Session = Depends(get_db)
):
    """
    주문 상태 변경
    - 관리자 또는 시스템에서 사용
    - 배송 상태 업데이트 등
    """
    # 소유권 확인
    if not crud.verify_order_ownership(db, order_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    order = crud.update_order_status(db, order_id, status_update.status)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    return order


@router.patch("/{user_id}/orders/{order_id}", response_model=schemas.OrderResponse)
def update_order(
    user_id: int,
    order_id: int,
    order_update: schemas.OrderUpdate,
    db: Session = Depends(get_db)
):
    """
    주문 정보 수정
    - 배송지, 배송 요청사항 등 수정
    """
    # 소유권 확인
    if not crud.verify_order_ownership(db, order_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    order = crud.update_order(db, order_id, order_update)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    return order


# ==================== 주문 취소/환불 ====================

@router.post("/{user_id}/orders/{order_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_order(
    user_id: int,
    order_id: int,
    reason: Optional[str] = Query(None, description="취소 사유"),
    db: Session = Depends(get_db)
):
    """
    주문 취소
    - 재고 복구
    - 배송 시작 전에만 가능
    """
    # 소유권 확인
    if not crud.verify_order_ownership(db, order_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    success, error = crud.cancel_order(db, order_id, reason)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "주문 취소 실패"
        )
    
    return {
        "message": "주문이 취소되었습니다",
        "order_id": order_id,
        "reason": reason
    }


@router.post("/{user_id}/orders/{order_id}/refund", status_code=status.HTTP_200_OK)
def refund_order(
    user_id: int,
    order_id: int,
    reason: str = Query(..., description="환불 사유"),
    db: Session = Depends(get_db)
):
    """
    주문 환불
    - 재고 복구
    - 결제 완료된 주문에 대해 가능
    """
    # 소유권 확인
    if not crud.verify_order_ownership(db, order_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    success, error = crud.refund_order(db, order_id, reason)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "환불 처리 실패"
        )
    
    return {
        "message": "환불이 요청되었습니다",
        "order_id": order_id,
        "reason": reason
    }


# ==================== 주문 항목 조회 ====================

@router.get("/{user_id}/orders/{order_id}/items", response_model=list[schemas.OrderItemResponse])
def get_order_items(
    user_id: int,
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    주문 항목 목록 조회
    - 특정 주문의 모든 항목 조회
    """
    # 소유권 확인
    if not crud.verify_order_ownership(db, order_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    items = crud.get_order_items_by_order_id(db, order_id)
    
    return [schemas.OrderItemResponse.model_validate(item) for item in items]


# ==================== 주문 요약 ====================

@router.get("/{user_id}/orders/{order_id}/summary", response_model=schemas.OrderSummary)
def get_order_summary(
    user_id: int,
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    주문 요약 정보 조회
    - 간단한 주문 정보만 반환
    """
    # 소유권 확인
    if not crud.verify_order_ownership(db, order_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    order = crud.get_order_detail(db, order_id)
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다"
        )
    
    return schemas.OrderSummary(
        id=order.id,
        order_number=order.order_number,
        total_amount=order.total_amount,
        status=order.status,
        created_at=order.created_at,
        item_count=len(order.items)
    )


# ==================== 헬스 체크 ====================

@router.get("/orders/health", tags=["health"])
def health_check():
    """
    주문 API 헬스 체크
    """
    return {
        "status": "healthy",
        "service": "orders",
        "version": "1.0.0"
    }
