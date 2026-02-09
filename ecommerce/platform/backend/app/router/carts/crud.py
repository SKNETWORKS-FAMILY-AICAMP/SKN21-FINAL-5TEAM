"""
Cart CRUD Operations with Real Product Data
"""
from decimal import Decimal
from typing import List, Optional, Dict
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from ecommerce.platform.backend.app.router.carts import models, schemas

from ecommerce.platform.backend.app.router.products.models import (
    ProductOption, 
    Product,
    UsedProductOption, 
    UsedProduct,
    UsedProductCondition
)

# ============================================
# Cart CRUD
# ============================================

def get_cart_by_user_id(db: Session, user_id: int) -> Optional[models.Cart]:
    """사용자 ID로 장바구니 조회"""
    return db.query(models.Cart).filter(models.Cart.user_id == user_id).first()


def create_cart(db: Session, user_id: int) -> models.Cart:
    """새 장바구니 생성"""
    cart = models.Cart(user_id=user_id)
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return cart


def get_or_create_cart(db: Session, user_id: int) -> models.Cart:
    """장바구니 조회 또는 생성"""
    cart = get_cart_by_user_id(db, user_id)
    if not cart:
        cart = create_cart(db, user_id)
    return cart


def clear_cart(db: Session, cart_id: int) -> bool:
    """장바구니 비우기"""
    try:
        db.query(models.CartItem).filter(models.CartItem.cart_id == cart_id).delete()
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


# ============================================
# CartItem CRUD
# ============================================

def get_cart_items_by_cart_id(db: Session, cart_id: int) -> List[models.CartItem]:
    """장바구니의 모든 항목 조회"""
    return db.query(models.CartItem).filter(models.CartItem.cart_id == cart_id).all()


def get_cart_item_by_id(db: Session, item_id: int) -> Optional[models.CartItem]:
    """장바구니 항목 ID로 조회"""
    return db.query(models.CartItem).filter(models.CartItem.id == item_id).first()


def get_existing_cart_item(
    db: Session,
    cart_id: int,
    product_option_type: schemas.ProductType,
    product_option_id: int
) -> Optional[models.CartItem]:
    """동일한 상품 옵션이 이미 장바구니에 있는지 확인"""
    return db.query(models.CartItem).filter(
        and_(
            models.CartItem.cart_id == cart_id,
            models.CartItem.product_option_type == product_option_type,
            models.CartItem.product_option_id == product_option_id
        )
    ).first()


def add_cart_item(
    db: Session,
    cart_id: int,
    item_data: schemas.CartItemCreate
) -> models.CartItem:
    """장바구니에 항목 추가 (이미 있으면 수량 증가)"""
    existing_item = get_existing_cart_item(
        db,
        cart_id,
        item_data.product_option_type,
        item_data.product_option_id
    )
    
    if existing_item:
        # 이미 있으면 수량만 증가
        existing_item.quantity += item_data.quantity
        db.commit()
        db.refresh(existing_item)
        return existing_item
    else:
        # 새로 추가
        cart_item = models.CartItem(
            cart_id=cart_id,
            product_option_type=item_data.product_option_type,
            product_option_id=item_data.product_option_id,
            quantity=item_data.quantity
        )
        db.add(cart_item)
        db.commit()
        db.refresh(cart_item)
        return cart_item


def update_cart_item_quantity(
    db: Session,
    item_id: int,
    quantity: int
) -> Optional[models.CartItem]:
    """장바구니 항목 수량 수정"""
    cart_item = get_cart_item_by_id(db, item_id)
    if cart_item:
        cart_item.quantity = quantity
        db.commit()
        db.refresh(cart_item)
    return cart_item


def delete_cart_item(db: Session, item_id: int) -> bool:
    """장바구니 항목 삭제"""
    cart_item = get_cart_item_by_id(db, item_id)
    if cart_item:
        db.delete(cart_item)
        db.commit()
        return True
    return False


def delete_cart_items(db: Session, item_ids: List[int]) -> int:
    """장바구니 항목 일괄 삭제"""
    try:
        deleted_count = db.query(models.CartItem).filter(
            models.CartItem.id.in_(item_ids)
        ).delete(synchronize_session=False)
        db.commit()
        return deleted_count
    except Exception:
        db.rollback()
        return 0


def verify_cart_item_ownership(db: Session, item_id: int, user_id: int) -> bool:
    """장바구니 항목의 소유권 확인"""
    result = db.query(models.CartItem).join(models.Cart).filter(
        and_(
            models.CartItem.id == item_id,
            models.Cart.user_id == user_id
        )
    ).first()
    return result is not None


# ============================================
# Product Info Retrieval (Real Data)
# ============================================

def get_new_product_info(db: Session, option_id: int) -> Optional[Dict]:
    """
    신상품 옵션 정보 조회
    ProductOption -> Product 조인
    """
    try:
        # eager loading으로 product 함께 조회
        option = db.query(ProductOption).join(Product).filter(
            ProductOption.id == option_id,
            ProductOption.is_active == True,
            Product.is_active == True,
            Product.deleted_at.is_(None)
        ).options(joinedload(ProductOption.product)).first()
        
        if not option or not option.product:
            return None
        
        product = option.product
        
        # 배송비 계산 (5만원 이상 무료배송)
        shipping_fee = Decimal('0') if product.price >= 50000 else Decimal('3000')
        shipping_text = '무료배송' if product.price >= 50000 else '배송비 3,000원'
        
        # 기본 이미지 URL
        image_url = 'https://via.placeholder.com/120'
        
        return {
            'id': option.id,
            'name': product.name,
            'brand': '브랜드',  # Product 모델에 brand 필드 없음
            'price': product.price,  # Product의 price
            'original_price': None,  # Product 모델에 original_price 없음
            'stock': option.quantity,  # ProductOption의 quantity
            'shipping_fee': shipping_fee,
            'shipping_text': shipping_text,
            'is_used': False,
            'image': image_url,
            'option': {
                'size': option.size_name,  # size_name 사용
                'color': option.color,
                'condition': None
            }
        }
    except Exception as e:
        print(f"Error getting new product info: {e}")
        return None


def get_used_product_info(db: Session, option_id: int) -> Optional[Dict]:
    """
    중고상품 옵션 정보 조회
    UsedProductOption -> UsedProduct -> UsedProductCondition 조인
    """
    try:
        # eager loading으로 관계 데이터 함께 조회
        option = db.query(UsedProductOption).join(UsedProduct).filter(
            UsedProductOption.id == option_id,
            UsedProductOption.is_active == True,
            UsedProduct.deleted_at.is_(None)
        ).options(
            joinedload(UsedProductOption.used_product).joinedload(UsedProduct.condition)
        ).first()
        
        if not option or not option.used_product:
            return None
        
        product = option.used_product
        
        # 중고상품 배송비
        shipping_fee = Decimal('2500')
        shipping_text = '배송비 2,500원'
        
        # 기본 이미지 URL
        image_url = 'https://via.placeholder.com/120'
        
        # 상태 정보 가져오기
        condition_name = '상태 확인 필요'
        if product.condition:
            condition_name = product.condition.condition_name
        
        return {
            'id': option.id,
            'name': product.name,
            'brand': '중고',  # UsedProduct 모델에 brand 필드 없음
            'price': product.price,  # UsedProduct의 price
            'original_price': None,  # UsedProduct 모델에 original_price 없음
            'stock': option.quantity,  # UsedProductOption의 quantity
            'shipping_fee': shipping_fee,
            'shipping_text': shipping_text,
            'is_used': True,
            'image': image_url,
            'option': {
                'size': option.size_name,  # size_name 사용
                'color': option.color,
                'condition': condition_name  # condition 객체에서 condition_name 추출
            }
        }
    except Exception as e:
        print(f"Error getting used product info: {e}")
        return None


def get_product_info(
    db: Session,
    product_type: schemas.ProductType,
    product_option_id: int
) -> Optional[Dict]:
    """
    상품 옵션 정보 조회 (신상품/중고상품 분기)
    """
    if product_type == schemas.ProductType.NEW:
        return get_new_product_info(db, product_option_id)
    else:
        return get_used_product_info(db, product_option_id)


def verify_product_option(
    db: Session,
    product_type: schemas.ProductType,
    product_option_id: int
) -> Optional[Dict]:
    """
    상품 옵션 존재 여부 및 재고 확인
    """
    product_info = get_product_info(db, product_type, product_option_id)
    
    if not product_info:
        return None
    
    # 재고가 0이면 None 반환
    if product_info['stock'] <= 0:
        return None
    
    return product_info


def enrich_cart_items_with_product_info(
    db: Session,
    cart_items: List[models.CartItem]
) -> List[schemas.CartItemDetailResponse]:
    """
    장바구니 항목에 상품 정보 추가
    상품 정보를 조회할 수 없는 경우 해당 항목은 제외
    """
    enriched_items = []
    
    for item in cart_items:
        product_info_dict = get_product_info(
            db,
            item.product_option_type,
            item.product_option_id
        )
        
        # 상품 정보가 없으면 (삭제됨, 비활성화 등) 스킵
        if not product_info_dict:
            continue
        
        # 수량이 재고보다 많으면 재고로 자동 조정
        actual_quantity = min(item.quantity, product_info_dict['stock'])
        if actual_quantity != item.quantity:
            item.quantity = actual_quantity
            db.commit()
        
        # Pydantic 스키마로 변환
        product_info = schemas.ProductInfo(
            id=product_info_dict['id'],
            name=product_info_dict['name'],
            brand=product_info_dict['brand'],
            price=product_info_dict['price'],
            original_price=product_info_dict.get('original_price'),
            stock=product_info_dict['stock'],
            shipping_fee=product_info_dict['shipping_fee'],
            shipping_text=product_info_dict['shipping_text'],
            is_used=product_info_dict['is_used'],
            image=product_info_dict['image'],
            option=schemas.ProductOptionInfo(**product_info_dict['option'])
        )
        
        enriched_item = schemas.CartItemDetailResponse(
            id=item.id,
            cart_id=item.cart_id,
            quantity=actual_quantity,
            product_option_type=item.product_option_type,
            product_option_id=item.product_option_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            product=product_info
        )
        enriched_items.append(enriched_item)
    
    return enriched_items


def calculate_cart_summary(
    items: List[schemas.CartItemDetailResponse]
) -> schemas.CartSummary:
    """장바구니 요약 정보 계산"""
    total_items = len(items)
    total_quantity = sum(item.quantity for item in items)
    total_price = sum((item.product.price * item.quantity for item in items), Decimal('0'))
    total_shipping_fee = sum((item.product.shipping_fee for item in items), Decimal('0'))
    final_total = total_price + total_shipping_fee
    
    return schemas.CartSummary(
        total_items=total_items,
        total_quantity=total_quantity,
        total_price=total_price,
        total_shipping_fee=total_shipping_fee,
        final_total=final_total
    )