"""
FastAPI Router - Inventory Module
재고 거래 내역 관련 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List , Optional
import logging

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.inventories import crud, schemas

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["inventories"]
)


# ==================== 재고 거래 내역 조회 ====================

@router.get("/transactions/{transaction_id}", response_model=schemas.InventoryTransactionResponse)
def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db)
):
    """
    재고 거래 내역 ID로 조회
    
    Args:
        transaction_id: 거래 내역 ID
        db: 데이터베이스 세션
    
    Returns:
        재고 거래 내역
    """
    logger.info(f"Fetching transaction: {transaction_id}")
    
    transaction = crud.get_transaction_by_id(db, transaction_id)
    
    if not transaction:
        logger.warning(f"Transaction not found: {transaction_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="거래 내역을 찾을 수 없습니다"
        )
    
    return transaction


@router.get("/products/{product_option_type}/{product_option_id}/transactions", response_model=List[schemas.InventoryTransactionResponse])
def get_product_transactions(
    product_option_type: schemas.ProductType,
    product_option_id: int,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    상품별 재고 거래 내역 조회
    
    Args:
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        재고 거래 내역 목록
    """
    logger.info(f"Fetching transactions for product: {product_option_type}/{product_option_id}")
    
    transactions = crud.get_transactions_by_product_option(
        db, product_option_type, product_option_id, skip, limit
    )
    
    return transactions


@router.get("/transactions/type/{transaction_type}", response_model=List[schemas.InventoryTransactionResponse])
def get_transactions_by_type(
    transaction_type: schemas.TransactionType,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    거래 유형별 재고 거래 내역 조회
    
    Args:
        transaction_type: 거래 유형
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        재고 거래 내역 목록
    """
    logger.info(f"Fetching transactions by type: {transaction_type}")
    
    transactions = crud.get_transactions_by_type(db, transaction_type, skip, limit)
    
    return transactions


@router.get("/transactions/reference/{reference_id}", response_model=List[schemas.InventoryTransactionResponse])
def get_transactions_by_reference(
    reference_id: int,
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(100, ge=1, le=1000, description="최대 조회 레코드 수"),
    db: Session = Depends(get_db)
):
    """
    참조 ID별 재고 거래 내역 조회 (예: 특정 주문의 재고 변동)
    
    Args:
        reference_id: 참조 ID (주문 ID 등)
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        db: 데이터베이스 세션
    
    Returns:
        재고 거래 내역 목록
    """
    logger.info(f"Fetching transactions by reference: {reference_id}")
    
    transactions = crud.get_transactions_by_reference(db, reference_id, skip, limit)
    
    return transactions


# ==================== 재고 입고 ====================

@router.post("/add", response_model=schemas.InventoryTransactionResponse, status_code=status.HTTP_201_CREATED)
def add_inventory(
    request: schemas.AddInventoryRequest,
    db: Session = Depends(get_db)
):
    """
    재고 입고
    
    Args:
        request: 입고 요청 데이터
        db: 데이터베이스 세션
    
    Returns:
        생성된 거래 내역
    """
    logger.info(f"Adding inventory: {request.product_option_type}/{request.product_option_id}, qty: {request.quantity}")
    
    try:
        transaction = crud.add_inventory(
            db,
            product_option_type=request.product_option_type,
            product_option_id=request.product_option_id,
            quantity=request.quantity,
            notes=request.notes
        )
        logger.info(f"Inventory added: {transaction.id}")
        return transaction
    except ValueError as e:
        logger.error(f"Failed to add inventory: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 재고 출고 ====================

@router.post("/remove", response_model=schemas.InventoryTransactionResponse, status_code=status.HTTP_201_CREATED)
def remove_inventory(
    request: schemas.RemoveInventoryRequest,
    db: Session = Depends(get_db)
):
    """
    재고 출고 (판매)
    
    Args:
        request: 출고 요청 데이터
        db: 데이터베이스 세션
    
    Returns:
        생성된 거래 내역
    """
    logger.info(f"Removing inventory: {request.product_option_type}/{request.product_option_id}, qty: {request.quantity}")
    
    try:
        transaction = crud.remove_inventory(
            db,
            product_option_type=request.product_option_type,
            product_option_id=request.product_option_id,
            quantity=request.quantity,
            order_id=request.order_id,
            notes=request.notes
        )
        logger.info(f"Inventory removed: {transaction.id}")
        return transaction
    except ValueError as e:
        logger.error(f"Failed to remove inventory: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 재고 반품 ====================

@router.post("/return", response_model=schemas.InventoryTransactionResponse, status_code=status.HTTP_201_CREATED)
def return_inventory(
    product_option_type: schemas.ProductType,
    product_option_id: int,
    quantity: int = Query(..., gt=0, description="반품 수량"),
    order_id: Optional[int] = Query(None, description="주문 ID"),
    notes: Optional[str] = Query(None, description="비고"),
    db: Session = Depends(get_db)
):
    """
    재고 반품
    
    Args:
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        quantity: 반품 수량
        order_id: 주문 ID
        notes: 비고
        db: 데이터베이스 세션
    
    Returns:
        생성된 거래 내역
    """
    logger.info(f"Returning inventory: {product_option_type}/{product_option_id}, qty: {quantity}")
    
    try:
        transaction = crud.return_inventory(
            db,
            product_option_type=product_option_type,
            product_option_id=product_option_id,
            quantity=quantity,
            order_id=order_id,
            notes=notes
        )
        logger.info(f"Inventory returned: {transaction.id}")
        return transaction
    except ValueError as e:
        logger.error(f"Failed to return inventory: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 재고 조정 ====================

@router.post("/adjust", response_model=schemas.InventoryTransactionResponse, status_code=status.HTTP_201_CREATED)
def adjust_inventory(
    request: schemas.AdjustInventoryRequest,
    db: Session = Depends(get_db)
):
    """
    재고 조정
    
    Args:
        request: 조정 요청 데이터
        db: 데이터베이스 세션
    
    Returns:
        생성된 거래 내역
    """
    logger.info(f"Adjusting inventory: {request.product_option_type}/{request.product_option_id}, change: {request.quantity_change}")
    
    try:
        transaction = crud.adjust_inventory(
            db,
            product_option_type=request.product_option_type,
            product_option_id=request.product_option_id,
            quantity_change=request.quantity_change,
            notes=request.notes
        )
        logger.info(f"Inventory adjusted: {transaction.id}")
        return transaction
    except ValueError as e:
        logger.error(f"Failed to adjust inventory: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== 재고 통계 ====================

@router.get("/products/{product_option_type}/{product_option_id}/stats", response_model=schemas.InventoryStats)
def get_inventory_stats(
    product_option_type: schemas.ProductType,
    product_option_id: int,
    db: Session = Depends(get_db)
):
    """
    재고 통계 조회
    
    Args:
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        db: 데이터베이스 세션
    
    Returns:
        재고 통계
    """
    logger.info(f"Fetching inventory stats: {product_option_type}/{product_option_id}")
    
    stats = crud.get_inventory_stats(db, product_option_type, product_option_id)
    
    return stats


@router.get("/products/{product_option_type}/{product_option_id}/stock")
def get_current_stock(
    product_option_type: schemas.ProductType,
    product_option_id: int,
    db: Session = Depends(get_db)
):
    """
    현재 재고 조회
    
    Args:
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        db: 데이터베이스 세션
    
    Returns:
        현재 재고 수량
    """
    logger.info(f"Fetching current stock: {product_option_type}/{product_option_id}")
    
    stock = crud.get_current_stock(db, product_option_type, product_option_id)
    
    return {
        "product_option_type": product_option_type,
        "product_option_id": product_option_id,
        "current_stock": stock
    }


# ==================== 헬스 체크 ====================

@router.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    재고 API 헬스 체크
    
    Returns:
        상태 정보
    """
    return {
        "status": "healthy",
        "service": "inventory"
    }
