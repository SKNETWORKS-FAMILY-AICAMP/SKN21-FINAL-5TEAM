"""
CRUD Operations - Inventory Module
재고 거래 내역 관련 CRUD 함수
"""
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ecommerce.platform.backend.app.router.inventories import models, schemas
from ecommerce.platform.backend.app.router.products.models import ProductOption, UsedProductOption


# ============================================
# InventoryTransaction CRUD
# ============================================

def get_transaction_by_id(db: Session, transaction_id: int) -> Optional[models.InventoryTransaction]:
    """
    재고 거래 내역 ID로 조회
    
    Args:
        db: 데이터베이스 세션
        transaction_id: 거래 내역 ID
    
    Returns:
        InventoryTransaction 객체 또는 None
    """
    return db.query(models.InventoryTransaction).filter(
        models.InventoryTransaction.id == transaction_id
    ).first()


def get_transactions_by_product_option(
    db: Session,
    product_option_type: schemas.ProductType,
    product_option_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[models.InventoryTransaction]:
    """
    상품 옵션별 재고 거래 내역 조회
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        InventoryTransaction 객체 리스트
    """
    return (
        db.query(models.InventoryTransaction)
        .filter(
            and_(
                models.InventoryTransaction.product_option_type == product_option_type,
                models.InventoryTransaction.product_option_id == product_option_id
            )
        )
        .order_by(models.InventoryTransaction.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_transactions_by_type(
    db: Session,
    transaction_type: schemas.TransactionType,
    skip: int = 0,
    limit: int = 100
) -> List[models.InventoryTransaction]:
    """
    거래 유형별 재고 거래 내역 조회
    
    Args:
        db: 데이터베이스 세션
        transaction_type: 거래 유형
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        InventoryTransaction 객체 리스트
    """
    return (
        db.query(models.InventoryTransaction)
        .filter(models.InventoryTransaction.transaction_type == transaction_type)
        .order_by(models.InventoryTransaction.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_transactions_by_reference(
    db: Session,
    reference_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[models.InventoryTransaction]:
    """
    참조 ID별 재고 거래 내역 조회 (예: 특정 주문의 재고 변동)
    
    Args:
        db: 데이터베이스 세션
        reference_id: 참조 ID (주문 ID 등)
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        InventoryTransaction 객체 리스트
    """
    return (
        db.query(models.InventoryTransaction)
        .filter(models.InventoryTransaction.reference_id == reference_id)
        .order_by(models.InventoryTransaction.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_inventory_transaction(
    db: Session,
    transaction_data: schemas.InventoryTransactionCreate
) -> models.InventoryTransaction:
    """
    재고 거래 내역 생성
    
    Args:
        db: 데이터베이스 세션
        transaction_data: 거래 내역 데이터
    
    Returns:
        생성된 InventoryTransaction 객체
    """
    transaction = models.InventoryTransaction(
        product_option_type=transaction_data.product_option_type,
        product_option_id=transaction_data.product_option_id,
        quantity_change=transaction_data.quantity_change,
        transaction_type=transaction_data.transaction_type,
        reference_id=transaction_data.reference_id,
        notes=transaction_data.notes
    )
    
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    
    return transaction


# ============================================
# Inventory Transaction Functions
# ============================================

def add_inventory(
    db: Session,
    product_option_type: schemas.ProductType,
    product_option_id: int,
    quantity: int,
    notes: Optional[str] = None
) -> models.InventoryTransaction:
    """
    재고 입고 (PURCHASE)
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        quantity: 입고 수량
        notes: 비고
    
    Returns:
        생성된 InventoryTransaction 객체
    """
    if quantity <= 0:
        raise ValueError("입고 수량은 0보다 커야 합니다")
    
    # 상품 옵션의 재고 업데이트
    if product_option_type == schemas.ProductType.NEW:
        option = db.query(ProductOption).filter(ProductOption.id == product_option_id).first()
    else:
        option = db.query(UsedProductOption).filter(UsedProductOption.id == product_option_id).first()
    
    if not option:
        raise ValueError(f"상품 옵션을 찾을 수 없습니다: {product_option_type}/{product_option_id}")
    
    # 재고 증가
    option.quantity += quantity
    
    # 거래 내역 생성
    transaction_data = schemas.InventoryTransactionCreate(
        product_option_type=product_option_type,
        product_option_id=product_option_id,
        quantity_change=quantity,
        transaction_type=schemas.TransactionType.PURCHASE,
        reference_id=None,  # ✅ 추가
        notes=notes or "재고 입고"
    )
    
    transaction = create_inventory_transaction(db, transaction_data)
    
    db.commit()
    
    return transaction


def remove_inventory(
    db: Session,
    product_option_type: schemas.ProductType,
    product_option_id: int,
    quantity: int,
    order_id: Optional[int] = None,
    notes: Optional[str] = None
) -> models.InventoryTransaction:
    """
    재고 출고 (SALE)
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        quantity: 출고 수량
        order_id: 주문 ID
        notes: 비고
    
    Returns:
        생성된 InventoryTransaction 객체
    """
    if quantity <= 0:
        raise ValueError("출고 수량은 0보다 커야 합니다")
    
    # 상품 옵션의 재고 확인 및 업데이트
    if product_option_type == schemas.ProductType.NEW:
        option = db.query(ProductOption).filter(ProductOption.id == product_option_id).first()
    else:
        option = db.query(UsedProductOption).filter(UsedProductOption.id == product_option_id).first()
    
    if not option:
        raise ValueError(f"상품 옵션을 찾을 수 없습니다: {product_option_type}/{product_option_id}")
    
    if option.quantity < quantity:
        raise ValueError(f"재고가 부족합니다 (현재: {option.quantity}, 요청: {quantity})")
    
    # 재고 감소
    option.quantity -= quantity
    
    # 거래 내역 생성
    transaction_data = schemas.InventoryTransactionCreate(
        product_option_type=product_option_type,
        product_option_id=product_option_id,
        quantity_change=-quantity,  # 음수로 저장
        transaction_type=schemas.TransactionType.SALE,
        reference_id=order_id,  # ✅ 추가
        notes=notes or "재고 출고 (판매)"
    )
    
    transaction = create_inventory_transaction(db, transaction_data)
    
    db.commit()
    
    return transaction


def return_inventory(
    db: Session,
    product_option_type: schemas.ProductType,
    product_option_id: int,
    quantity: int,
    order_id: Optional[int] = None,
    notes: Optional[str] = None
) -> models.InventoryTransaction:
    """
    재고 반품 (RETURN)
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        quantity: 반품 수량
        order_id: 주문 ID
        notes: 비고
    
    Returns:
        생성된 InventoryTransaction 객체
    """
    if quantity <= 0:
        raise ValueError("반품 수량은 0보다 커야 합니다")
    
    # 상품 옵션의 재고 업데이트
    if product_option_type == schemas.ProductType.NEW:
        option = db.query(ProductOption).filter(ProductOption.id == product_option_id).first()
    else:
        option = db.query(UsedProductOption).filter(UsedProductOption.id == product_option_id).first()
    
    if not option:
        raise ValueError(f"상품 옵션을 찾을 수 없습니다: {product_option_type}/{product_option_id}")
    
    # 재고 증가 (반품)
    option.quantity += quantity
    
    # 거래 내역 생성
    transaction_data = schemas.InventoryTransactionCreate(
        product_option_type=product_option_type,
        product_option_id=product_option_id,
        quantity_change=quantity,
        transaction_type=schemas.TransactionType.RETURN,
        reference_id=order_id,  # ✅ 추가
        notes=notes or "재고 반품"
    )
    
    transaction = create_inventory_transaction(db, transaction_data)
    
    db.commit()
    
    return transaction


def adjust_inventory(
    db: Session,
    product_option_type: schemas.ProductType,
    product_option_id: int,
    quantity_change: int,
    notes: Optional[str] = None
) -> models.InventoryTransaction:
    """
    재고 조정 (ADJUSTMENT)
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
        quantity_change: 조정 수량 (양수/음수)
        notes: 조정 사유
    
    Returns:
        생성된 InventoryTransaction 객체
    """
    if quantity_change == 0:
        raise ValueError("조정 수량은 0이 아니어야 합니다")
    
    # 상품 옵션의 재고 업데이트
    if product_option_type == schemas.ProductType.NEW:
        option = db.query(ProductOption).filter(ProductOption.id == product_option_id).first()
    else:
        option = db.query(UsedProductOption).filter(UsedProductOption.id == product_option_id).first()
    
    if not option:
        raise ValueError(f"상품 옵션을 찾을 수 없습니다: {product_option_type}/{product_option_id}")
    
    # 음수 조정 시 재고 확인
    if quantity_change < 0 and option.quantity < abs(quantity_change):
        raise ValueError(f"재고가 부족합니다 (현재: {option.quantity}, 조정: {quantity_change})")
    
    # 재고 조정
    option.quantity += quantity_change
    
    # 거래 내역 생성
    transaction_data = schemas.InventoryTransactionCreate(
        product_option_type=product_option_type,
        product_option_id=product_option_id,
        quantity_change=quantity_change,
        transaction_type=schemas.TransactionType.ADJUSTMENT,
        reference_id=None,  # ✅ 추가
        notes=notes or "재고 조정"
    )
    
    transaction = create_inventory_transaction(db, transaction_data)
    
    db.commit()
    
    return transaction


# ============================================
# Inventory Statistics
# ============================================

def get_inventory_stats(
    db: Session,
    product_option_type: schemas.ProductType,
    product_option_id: int
) -> schemas.InventoryStats:
    """
    재고 통계 조회
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
    
    Returns:
        재고 통계
    """
    # 현재 재고 조회
    if product_option_type == schemas.ProductType.NEW:
        option = db.query(ProductOption).filter(ProductOption.id == product_option_id).first()
    else:
        option = db.query(UsedProductOption).filter(UsedProductOption.id == product_option_id).first()
    
    current_stock = option.quantity if option else 0
    
    # 유형별 통계
    purchased = (
        db.query(func.sum(models.InventoryTransaction.quantity_change))
        .filter(
            and_(
                models.InventoryTransaction.product_option_type == product_option_type,
                models.InventoryTransaction.product_option_id == product_option_id,
                models.InventoryTransaction.transaction_type == schemas.TransactionType.PURCHASE
            )
        )
        .scalar() or 0
    )
    
    sold = abs(
        db.query(func.sum(models.InventoryTransaction.quantity_change))
        .filter(
            and_(
                models.InventoryTransaction.product_option_type == product_option_type,
                models.InventoryTransaction.product_option_id == product_option_id,
                models.InventoryTransaction.transaction_type == schemas.TransactionType.SALE
            )
        )
        .scalar() or 0
    )
    
    returned = (
        db.query(func.sum(models.InventoryTransaction.quantity_change))
        .filter(
            and_(
                models.InventoryTransaction.product_option_type == product_option_type,
                models.InventoryTransaction.product_option_id == product_option_id,
                models.InventoryTransaction.transaction_type == schemas.TransactionType.RETURN
            )
        )
        .scalar() or 0
    )
    
    adjusted = (
        db.query(func.sum(models.InventoryTransaction.quantity_change))
        .filter(
            and_(
                models.InventoryTransaction.product_option_type == product_option_type,
                models.InventoryTransaction.product_option_id == product_option_id,
                models.InventoryTransaction.transaction_type == schemas.TransactionType.ADJUSTMENT
            )
        )
        .scalar() or 0
    )
    
    return schemas.InventoryStats(
        product_option_type=product_option_type,
        product_option_id=product_option_id,
        current_stock=current_stock,
        total_purchased=purchased,
        total_sold=sold,
        total_returned=returned,
        total_adjusted=adjusted
    )


def get_current_stock(
    db: Session,
    product_option_type: schemas.ProductType,
    product_option_id: int
) -> int:
    """
    현재 재고 조회
    
    Args:
        db: 데이터베이스 세션
        product_option_type: 상품 유형
        product_option_id: 상품 옵션 ID
    
    Returns:
        현재 재고 수량
    """
    if product_option_type == schemas.ProductType.NEW:
        option = db.query(ProductOption).filter(ProductOption.id == product_option_id).first()
    else:
        option = db.query(UsedProductOption).filter(UsedProductOption.id == product_option_id).first()
    
    return option.quantity if option else 0