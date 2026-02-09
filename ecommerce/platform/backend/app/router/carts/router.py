"""
Cart Router - 장바구니 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.carts import crud, schemas


router = APIRouter(
    tags=["carts"]
)


# ==================== 장바구니 조회 ====================

@router.get("/{user_id}", response_model=schemas.CartDetailWithSummary)
def get_user_cart(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    특정 사용자의 장바구니 조회
    - 장바구니가 없으면 자동 생성
    - 상품 정보와 요약 정보 포함
    """
    # 장바구니 조회 또는 생성
    cart = crud.get_or_create_cart(db, user_id)
    
    # 장바구니 항목 조회
    cart_items = crud.get_cart_items_by_cart_id(db, cart.id)
    
    # 상품 정보 추가
    enriched_items = crud.enrich_cart_items_with_product_info(db, cart_items)
    
    # 요약 정보 계산
    summary = crud.calculate_cart_summary(enriched_items)
    
    cart_detail = schemas.CartDetailResponse(
        id=cart.id,
        user_id=cart.user_id,
        created_at=cart.created_at,
        updated_at=cart.updated_at,
        items=enriched_items
    )
    
    return schemas.CartDetailWithSummary(
        cart=cart_detail,
        summary=summary
    )


@router.get("/{user_id}/summary", response_model=schemas.CartSummary)
def get_cart_summary(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    장바구니 요약 정보만 조회
    - 헤더의 장바구니 아이콘 뱃지용
    """
    cart = crud.get_or_create_cart(db, user_id)
    cart_items = crud.get_cart_items_by_cart_id(db, cart.id)
    enriched_items = crud.enrich_cart_items_with_product_info(db, cart_items)
    
    return crud.calculate_cart_summary(enriched_items)


# ==================== 장바구니 항목 추가 ====================

@router.post("/{user_id}/items", response_model=schemas.CartItemDetailResponse, status_code=status.HTTP_201_CREATED)
def add_to_cart(
    user_id: int,
    item_data: schemas.AddToCartRequest,
    db: Session = Depends(get_db)
):
    """
    장바구니에 상품 추가
    - 이미 있는 상품이면 수량 증가
    - 없는 상품이면 새로 추가
    """
    # 장바구니 조회 또는 생성
    cart = crud.get_or_create_cart(db, user_id)
    
    # 상품 옵션 존재 여부 및 재고 확인
    product_info = crud.verify_product_option(
        db, 
        item_data.product_option_type, 
        item_data.product_option_id
    )
    
    if not product_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="상품을 찾을 수 없습니다"
        )
    
    # 재고 확인
    if product_info['stock'] < item_data.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"재고가 부족합니다. (남은 재고: {product_info['stock']}개)"
        )
    
    # 장바구니에 추가
    cart_item_create = schemas.CartItemCreate(
        product_option_type=item_data.product_option_type,
        product_option_id=item_data.product_option_id,
        quantity=item_data.quantity
    )
    
    cart_item = crud.add_cart_item(db, cart.id, cart_item_create)
    
    # 상품 정보 추가하여 반환
    enriched_items = crud.enrich_cart_items_with_product_info(db, [cart_item])
    
    return enriched_items[0]


# ==================== 장바구니 항목 수정 ====================

@router.patch("/{user_id}/items/{item_id}", response_model=schemas.CartItemDetailResponse)
def update_cart_item(
    user_id: int,
    item_id: int,
    update_data: schemas.UpdateCartItemRequest,
    db: Session = Depends(get_db)
):
    """
    장바구니 항목 수량 수정
    """
    # 소유권 확인
    if not crud.verify_cart_item_ownership(db, item_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="장바구니 항목을 찾을 수 없습니다"
        )
    
    # 재고 확인
    cart_item = crud.get_cart_item_by_id(db, item_id)
    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="장바구니 항목을 찾을 수 없습니다"
        )
    
    product_info = crud.verify_product_option(
        db,
        cart_item.product_option_type,
        cart_item.product_option_id
    )
    
    if product_info and product_info['stock'] < update_data.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"재고가 부족합니다. (남은 재고: {product_info['stock']}개)"
        )
    
    # 수량 업데이트
    updated_item = crud.update_cart_item_quantity(db, item_id, update_data.quantity)
    
    if not updated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="장바구니 항목을 찾을 수 없습니다"
        )
    
    # 상품 정보 추가하여 반환
    enriched_items = crud.enrich_cart_items_with_product_info(db, [updated_item])
    
    return enriched_items[0]


# ==================== 장바구니 항목 삭제 ====================

@router.delete("/{user_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_cart_item(
    user_id: int,
    item_id: int,
    db: Session = Depends(get_db)
):
    """
    장바구니 항목 개별 삭제
    """
    # 소유권 확인
    if not crud.verify_cart_item_ownership(db, item_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="장바구니 항목을 찾을 수 없습니다"
        )
    
    # 삭제
    if not crud.delete_cart_item(db, item_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="장바구니 항목을 찾을 수 없습니다"
        )
    
    return None


@router.delete("/{user_id}/items", status_code=status.HTTP_200_OK)
def remove_cart_items(
    user_id: int,
    request: schemas.RemoveFromCartRequest,
    db: Session = Depends(get_db)
):
    """
    선택한 장바구니 항목 일괄 삭제
    """
    # 각 항목의 소유권 확인
    for item_id in request.item_ids:
        if not crud.verify_cart_item_ownership(db, item_id, user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"항목 {item_id}에 대한 권한이 없습니다"
            )
    
    # 일괄 삭제
    deleted_count = crud.delete_cart_items(db, request.item_ids)
    
    return {
        "message": f"{deleted_count}개 항목이 삭제되었습니다",
        "deleted_count": deleted_count
    }


@router.delete("/{user_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
def clear_cart(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    장바구니 전체 비우기
    """
    cart = crud.get_cart_by_user_id(db, user_id)
    
    if not cart:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="장바구니를 찾을 수 없습니다"
        )
    
    crud.clear_cart(db, cart.id)
    
    return None


# ==================== 헬스 체크 ====================

@router.get("/health")
def health_check():
    """
    장바구니 API 헬스 체크
    """
    return {
        "status": "healthy",
        "service": "carts"
    }
