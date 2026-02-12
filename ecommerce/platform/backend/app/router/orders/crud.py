"""
Order CRUD Operations
주문 관련 데이터베이스 작업
"""
from decimal import Decimal
from typing import List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, desc

from ecommerce.platform.backend.app.router.orders import models, schemas
from ecommerce.platform.backend.app.router.carts.models import Cart, CartItem
from ecommerce.platform.backend.app.router.products.models import ProductOption, UsedProductOption


# ============================================
# Utility Functions
# ============================================

def generate_order_number() -> str:
    """주문 번호 생성 (ORD-YYYYMMDD-HHMMSS-microseconds)"""
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")
    micro = now.microsecond // 1000  # milliseconds
    return f"ORD-{date_str}-{time_str}-{micro:03d}"


# ============================================
# Order CRUD - Read Operations
# ============================================

def get_order_by_id(db: Session, order_id: int) -> Optional[models.Order]:
    """주문 ID로 조회"""
    return db.query(models.Order).filter(models.Order.id == order_id).first()


def get_order_by_order_number(db: Session, order_number: str) -> Optional[models.Order]:
    """주문 번호로 조회"""
    return db.query(models.Order).filter(models.Order.order_number == order_number).first()


def get_orders_by_user_id(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    status: Optional[schemas.OrderStatus] = None
) -> Tuple[List[models.Order], int]:
    """
    사용자별 주문 목록 조회
    Returns: (주문 리스트, 전체 개수)
    """
    query = db.query(models.Order).filter(models.Order.user_id == user_id)
    
    if status:
        query = query.filter(models.Order.status == status)
    
    total = query.count()
    orders = (
        query.options(joinedload(models.Order.items))
        .order_by(desc(models.Order.created_at))
        .offset(skip)
        .limit(limit)
        .all()
    )
    
    return orders, total


def get_order_detail(db: Session, order_id: int) -> Optional[models.Order]:
    """
    주문 상세 조회 (항목, 배송지 포함)
    """
    return (
        db.query(models.Order)
        .options(
            joinedload(models.Order.items),
            joinedload(models.Order.shipping_addresses),
            joinedload(models.Order.payment)
        )
        .filter(models.Order.id == order_id)
        .first()
    )


def verify_order_ownership(db: Session, order_id: int, user_id: int) -> bool:
    """주문 소유권 확인"""
    order = db.query(models.Order).filter(
        and_(
            models.Order.id == order_id,
            models.Order.user_id == user_id
        )
    ).first()
    return order is not None


# ============================================
# Order CRUD - Create Operations
# ============================================

def create_order_from_cart(
    db: Session,
    user_id: int,
    cart_item_ids: List[int],
    shipping_address_id: int,
    payment_method: str,
    shipping_request: Optional[str] = None,
    points_used: Decimal = Decimal('0')
) -> Tuple[Optional[models.Order], Optional[str]]:
    """
    장바구니에서 주문 생성
    Returns: (Order, error_message)
    """
    try:
        # 1. 장바구니 항목 조회 및 검증
        cart_items = (
            db.query(CartItem)
            .join(Cart)
            .filter(
                and_(
                    CartItem.id.in_(cart_item_ids),
                    Cart.user_id == user_id
                )
            )
            .all()
        )
        
        if len(cart_items) != len(cart_item_ids):
            return None, "일부 장바구니 항목을 찾을 수 없습니다"
        
        if not cart_items:
            return None, "주문할 상품이 없습니다"
        
        # 2. 상품 정보 조회 및 가격 계산
        order_items_data = []
        subtotal = Decimal('0')
        total_shipping_fee = Decimal('0')
        
        for cart_item in cart_items:
            # 상품 옵션 조회
            if cart_item.product_option_type == schemas.ProductType.NEW:
                option = (
                    db.query(ProductOption)
                    .filter(
                        ProductOption.id == cart_item.product_option_id,
                        ProductOption.is_active == True
                    )
                    .first()
                )
                if not option or not option.product or not option.product.is_active:
                    return None, f"상품을 찾을 수 없습니다 (ID: {cart_item.product_option_id})"
                
                unit_price = option.product.price
                stock = option.quantity
                
                # 배송비 계산 (5만원 이상 무료배송)
                item_total = unit_price * cart_item.quantity
                shipping_fee = Decimal('0') if item_total >= 50000 else Decimal('3000')
                
            else:  # USED
                option = (
                    db.query(UsedProductOption)
                    .filter(
                        UsedProductOption.id == cart_item.product_option_id,
                        UsedProductOption.is_active == True
                    )
                    .first()
                )
                if not option or not option.used_product:
                    return None, f"상품을 찾을 수 없습니다 (ID: {cart_item.product_option_id})"
                
                unit_price = option.used_product.price
                stock = option.quantity
                shipping_fee = Decimal('2500')  # 중고상품 배송비
            
            # 재고 확인
            if stock < cart_item.quantity:
                return None, f"재고가 부족합니다 (남은 재고: {stock}개)"
            
            # 주문 항목 데이터 준비
            item_subtotal = unit_price * cart_item.quantity
            order_items_data.append({
                'product_option_type': cart_item.product_option_type,
                'product_option_id': cart_item.product_option_id,
                'quantity': cart_item.quantity,
                'unit_price': unit_price,
                'subtotal': item_subtotal,
                'option': option
            })
            
            subtotal += item_subtotal
            total_shipping_fee += shipping_fee
        
        # 3. 주문 금액 계산
        order_number = generate_order_number()
        discount_amount = Decimal('0')  # 향후 쿠폰/할인 적용 가능
        total_amount = subtotal + total_shipping_fee - discount_amount - points_used
        
        if total_amount < 0:
            total_amount = Decimal('0')
        
        # 4. 주문 생성
        order = models.Order(
            user_id=user_id,
            order_number=order_number,
            shipping_address_id=shipping_address_id,
            subtotal=subtotal,
            discount_amount=discount_amount,
            shipping_fee=total_shipping_fee,
            total_amount=total_amount,
            points_used=points_used,
            status=schemas.OrderStatus.PENDING,
            payment_method=payment_method,
            shipping_request=shipping_request
        )
        db.add(order)
        db.flush()  # ID 생성
        
        # 5. 주문 항목 생성 및 재고 차감
        for item_data in order_items_data:
            order_item = models.OrderItem(
                order_id=order.id,
                product_option_type=item_data['product_option_type'],
                product_option_id=item_data['product_option_id'],
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
                subtotal=item_data['subtotal']
            )
            db.add(order_item)
            
            # 재고 차감
            option = item_data['option']
            option.quantity -= item_data['quantity']
        
        # 6. 장바구니 항목 삭제
        for cart_item in cart_items:
            db.delete(cart_item)
        
        db.commit()
        db.refresh(order)
        
        return order, None
        
    except Exception as e:
        db.rollback()
        return None, f"주문 생성 중 오류 발생: {str(e)}"


def create_order_direct(
    db: Session,
    user_id: int,
    order_data: schemas.OrderCreate
) -> Tuple[Optional[models.Order], Optional[str]]:
    """
    직접 주문 생성 (장바구니를 거치지 않음)
    Returns: (Order, error_message)
    """
    try:
        # 상품 정보 조회 및 검증
        order_items_data = []
        subtotal = Decimal('0')
        total_shipping_fee = Decimal('0')
        
        for item_create in order_data.items:
            # 상품 옵션 조회
            if item_create.product_option_type == schemas.ProductType.NEW:
                option = (
                    db.query(ProductOption)
                    .filter(
                        ProductOption.id == item_create.product_option_id,
                        ProductOption.is_active == True
                    )
                    .first()
                )
                if not option or not option.product or not option.product.is_active:
                    return None, f"상품을 찾을 수 없습니다 (ID: {item_create.product_option_id})"
                
                unit_price = option.product.price
                stock = option.quantity
                
                item_total = unit_price * item_create.quantity
                shipping_fee = Decimal('0') if item_total >= 50000 else Decimal('3000')
                
            else:  # USED
                option = (
                    db.query(UsedProductOption)
                    .filter(
                        UsedProductOption.id == item_create.product_option_id,
                        UsedProductOption.is_active == True
                    )
                    .first()
                )
                if not option or not option.used_product:
                    return None, f"상품을 찾을 수 없습니다 (ID: {item_create.product_option_id})"
                
                unit_price = option.used_product.price
                stock = option.quantity
                shipping_fee = Decimal('2500')
            
            # 재고 확인
            if stock < item_create.quantity:
                return None, f"재고가 부족합니다 (남은 재고: {stock}개)"
            
            # 주문 항목 데이터 준비
            item_subtotal = unit_price * item_create.quantity
            order_items_data.append({
                'product_option_type': item_create.product_option_type,
                'product_option_id': item_create.product_option_id,
                'quantity': item_create.quantity,
                'unit_price': unit_price,
                'subtotal': item_subtotal,
                'option': option
            })
            
            subtotal += item_subtotal
            total_shipping_fee += shipping_fee
        
        # 주문 금액 계산
        order_number = generate_order_number()
        discount_amount = Decimal('0')
        total_amount = subtotal + total_shipping_fee - discount_amount - order_data.points_used
        
        if total_amount < 0:
            total_amount = Decimal('0')
        
        # 주문 생성
        order = models.Order(
            user_id=user_id,
            order_number=order_number,
            shipping_address_id=order_data.shipping_address_id,
            subtotal=subtotal,
            discount_amount=discount_amount,
            shipping_fee=total_shipping_fee,
            total_amount=total_amount,
            points_used=order_data.points_used,
            status=schemas.OrderStatus.PENDING,
            payment_method=order_data.payment_method,
            shipping_request=order_data.shipping_request
        )
        db.add(order)
        db.flush()
        
        # 주문 항목 생성 및 재고 차감
        for item_data in order_items_data:
            order_item = models.OrderItem(
                order_id=order.id,
                product_option_type=item_data['product_option_type'],
                product_option_id=item_data['product_option_id'],
                quantity=item_data['quantity'],
                unit_price=item_data['unit_price'],
                subtotal=item_data['subtotal']
            )
            db.add(order_item)
            
            option = item_data['option']
            option.quantity -= item_data['quantity']
        
        db.commit()
        db.refresh(order)
        
        return order, None
        
    except Exception as e:
        db.rollback()
        return None, f"주문 생성 중 오류 발생: {str(e)}"


# ============================================
# Order CRUD - Update Operations
# ============================================

def update_order_status(
    db: Session,
    order_id: int,
    status: schemas.OrderStatus
) -> Optional[models.Order]:
    """주문 상태 변경"""
    order = get_order_by_id(db, order_id)
    if order:
        order.status = status
        db.commit()
        db.refresh(order)
    return order


def update_order(
    db: Session,
    order_id: int,
    order_update: schemas.OrderUpdate
) -> Optional[models.Order]:
    """주문 정보 수정"""
    order = get_order_by_id(db, order_id)
    if not order:
        return None
    
    update_data = order_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(order, field, value)
    
    db.commit()
    db.refresh(order)
    return order


# ============================================
# Order CRUD - Cancel & Refund
# ============================================

def cancel_order(
    db: Session,
    order_id: int,
    reason: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    주문 취소 (재고 복구)
    Returns: (success, error_message)
    """
    try:
        order = get_order_detail(db, order_id)
        if not order:
            return False, "주문을 찾을 수 없습니다"
        
        # 이미 취소되었거나 환불된 경우
        if order.status in [schemas.OrderStatus.CANCELLED, schemas.OrderStatus.REFUNDED]:
            return False, "이미 취소된 주문입니다"
        
        # 배송 시작된 경우 취소 불가
        if order.status in [schemas.OrderStatus.SHIPPED, schemas.OrderStatus.DELIVERED]:
            return False, "배송이 시작된 주문은 취소할 수 없습니다"
        
        # 재고 복구
        for item in order.items:
            if item.product_option_type == schemas.ProductType.NEW:
                option = db.query(ProductOption).filter(
                    ProductOption.id == item.product_option_id
                ).first()
            else:
                option = db.query(UsedProductOption).filter(
                    UsedProductOption.id == item.product_option_id
                ).first()
            
            if option:
                option.quantity += item.quantity
        
        # 주문 상태 변경
        order.status = schemas.OrderStatus.CANCELLED
        if reason:
            current_request = order.shipping_request or ""
            order.shipping_request = f"{current_request}\n[취소 사유: {reason}]".strip()
        
        db.commit()
        return True, None
        
    except Exception as e:
        db.rollback()
        return False, f"주문 취소 중 오류 발생: {str(e)}"


def refund_order(
    db: Session,
    order_id: int,
    reason: str
) -> Tuple[bool, Optional[str]]:
    """
    주문 환불 (재고 복구)
    Returns: (success, error_message)
    """
    try:
        order = get_order_detail(db, order_id)
        if not order:
            return False, "주문을 찾을 수 없습니다"
        
        # 결제 완료된 주문만 환불 가능
        if order.status not in [
            schemas.OrderStatus.PAID,
            schemas.OrderStatus.PREPARING,
            schemas.OrderStatus.SHIPPED,
            schemas.OrderStatus.DELIVERED
        ]:
            return False, "환불 가능한 상태가 아닙니다"
        
        # 재고 복구
        for item in order.items:
            if item.product_option_type == schemas.ProductType.NEW:
                option = db.query(ProductOption).filter(
                    ProductOption.id == item.product_option_id
                ).first()
            else:
                option = db.query(UsedProductOption).filter(
                    UsedProductOption.id == item.product_option_id
                ).first()
            
            if option:
                option.quantity += item.quantity
        
        # 주문 상태 변경
        order.status = schemas.OrderStatus.REFUNDED
        current_request = order.shipping_request or ""
        order.shipping_request = f"{current_request}\n[환불 사유: {reason}]".strip()
        
        db.commit()
        return True, None
        
    except Exception as e:
        db.rollback()
        return False, f"환불 처리 중 오류 발생: {str(e)}"


# ============================================
# OrderItem CRUD
# ============================================

def get_order_items_by_order_id(db: Session, order_id: int) -> List[models.OrderItem]:
    """주문 ID로 주문 항목 목록 조회"""
    return db.query(models.OrderItem).filter(models.OrderItem.order_id == order_id).all()


# ============================================
# Product Info Enrichment (상품명 추가)
# ============================================

def get_product_info_for_item(db: Session, item: models.OrderItem) -> dict:
    """
    OrderItem에서 상품 정보 조회 (상품명, 브랜드, 사이즈, 색상, 중고상품 상태 포함)

    Args:
        db: 데이터베이스 세션
        item: OrderItem 객체

    Returns:
        상품 정보 딕셔너리 {
            "product_name": str,
            "product_brand": str | None,
            "product_size": str | None,
            "product_color": str | None,
            "product_condition": str | None
        }
    """
    default_info = {
        "product_name": f"상품 옵션 ID: {item.product_option_id}",
        "product_brand": None,
        "product_size": None,
        "product_color": None,
        "product_condition": None
    }

    try:
        if item.product_option_type == schemas.ProductType.NEW:
            # 신상품 조회
            from ecommerce.platform.backend.app.router.products.models import Product

            option = db.query(ProductOption).filter(
                ProductOption.id == item.product_option_id
            ).first()

            if option and option.product:
                return {
                    "product_name": option.product.name,
                    "product_brand": option.product.category.name if option.product.category else None,
                    "product_size": option.size_name,
                    "product_color": option.color,
                    "product_condition": None  # 신상품은 상태 없음
                }

        elif item.product_option_type == schemas.ProductType.USED:
            # 중고상품 조회
            from ecommerce.platform.backend.app.router.products.models import UsedProduct

            option = db.query(UsedProductOption).filter(
                UsedProductOption.id == item.product_option_id
            ).first()

            if option and option.used_product:
                condition_name = None
                if option.used_product.condition:
                    condition_name = option.used_product.condition.condition_name

                return {
                    "product_name": option.used_product.name,
                    "product_brand": option.used_product.category.name if option.used_product.category else None,
                    "product_size": option.size_name,
                    "product_color": option.color,
                    "product_condition": condition_name
                }

        return default_info

    except Exception as e:
        return default_info


def enrich_order_with_product_names(db: Session, order: models.Order) -> dict:
    """
    주문 객체를 딕셔너리로 변환하면서 각 항목에 상품명 추가
    
    Args:
        db: 데이터베이스 세션
        order: Order 객체
    
    Returns:
        상품명이 포함된 주문 딕셔너리
    """
    order_dict = {
        "id": order.id,
        "user_id": order.user_id,
        "order_number": order.order_number,
        "shipping_address_id": order.shipping_address_id,
        "subtotal": str(order.subtotal),
        "discount_amount": str(order.discount_amount),
        "shipping_fee": str(order.shipping_fee),
        "total_amount": str(order.total_amount),
        "points_used": str(order.points_used),
        "status": order.status.value,
        "payment_method": order.payment_method,
        "shipping_request": order.shipping_request,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "items": []
    }
    
    # 각 주문 항목에 상품 정보 추가
    for item in order.items:
        product_info = get_product_info_for_item(db, item)

        item_dict = {
            "id": item.id,
            "order_id": item.order_id,
            "product_option_type": item.product_option_type.value,
            "product_option_id": item.product_option_id,
            "quantity": item.quantity,
            "unit_price": str(item.unit_price),
            "subtotal": str(item.subtotal),
            "created_at": item.created_at.isoformat(),
            "product_name": product_info["product_name"],
            "product_brand": product_info["product_brand"],
            "product_size": product_info["product_size"],
            "product_color": product_info["product_color"],
            "product_condition": product_info["product_condition"]
        }
        order_dict["items"].append(item_dict)
    
    return order_dict


def get_orders_by_user_with_product_names(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    status: Optional[schemas.OrderStatus] = None
) -> Tuple[List[dict], int]:
    """
    사용자별 주문 목록 조회 (상품명 포함)
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
        status: 주문 상태 필터 (선택)
    
    Returns:
        (상품명이 포함된 주문 리스트, 전체 개수)
    """
    # 기존 함수로 주문 조회
    orders, total = get_orders_by_user_id(db, user_id, skip, limit, status)
    
    # 각 주문에 상품명 추가
    enriched_orders = [enrich_order_with_product_names(db, order) for order in orders]
    
    return enriched_orders, total


def get_order_detail_with_product_names(db: Session, order_id: int) -> Optional[dict]:
    """
    주문 상세 조회 (상품명 포함)
    
    Args:
        db: 데이터베이스 세션
        order_id: 주문 ID
    
    Returns:
        상품명이 포함된 주문 상세 정보 또는 None
    """
    order = get_order_detail(db, order_id)
    
    if not order:
        return None
    
    return enrich_order_with_product_names(db, order)

