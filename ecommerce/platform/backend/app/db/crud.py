"""
CRUD Operations for E-commerce Platform
Database operations using SQLAlchemy
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from models import (
    User, UserBodyMeasurement, Category, Product, ProductOption,
    UsedProduct, UsedProductOption, UsedProductCondition,
    Cart, CartItem, ShippingAddress, Order, OrderItem,
    Payment, ShippingInfo, OrderStatusHistory, Review,
    PointHistory, IssuedVoucher, InventoryTransaction,
    ProductImage, ShippingRequestTemplate
)
from schemas import (
    UserCreate, UserUpdate, BodyMeasurementCreate, BodyMeasurementUpdate,
    CategoryCreate, CategoryUpdate, ProductCreate, ProductUpdate,
    ProductOptionCreate, ProductOptionUpdate, UsedProductCreate, UsedProductUpdate,
    CartItemCreate, CartItemUpdate, ShippingAddressCreate, ShippingAddressUpdate,
    OrderCreate, OrderItemCreate, ReviewCreate, ReviewUpdate
)
import bcrypt


# ============================================
# User CRUD
# ============================================

def get_user(db: Session, user_id: int) -> Optional[User]:
    """사용자 ID로 조회"""
    return db.query(User).filter(
        User.id == user_id,
        User.deleted_at.is_(None)
    ).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """이메일로 사용자 조회"""
    return db.query(User).filter(
        User.email == email,
        User.deleted_at.is_(None)
    ).first()


def get_users(
    db: Session, 
    skip: int = 0, 
    limit: int = 100,
    status: Optional[str] = None
) -> List[User]:
    """사용자 목록 조회"""
    query = db.query(User).filter(User.deleted_at.is_(None))
    
    if status:
        query = query.filter(User.status == status)
    
    return query.offset(skip).limit(limit).all()


def create_user(db: Session, user: UserCreate) -> User:
    """사용자 생성"""
    # 비밀번호 해싱
    hashed_password = bcrypt.hashpw(
        user.password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')
    
    db_user = User(
        email=user.email,
        password_hash=hashed_password,
        name=user.name,
        phone=user.phone,
        address1=user.address1,
        address2=user.address2
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(db: Session, user_id: int, user: UserUpdate) -> Optional[User]:
    """사용자 정보 수정"""
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    
    # 변경된 필드만 업데이트
    update_data = user.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_user, field, value)
    
    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, user_id: int) -> bool:
    """사용자 삭제 (소프트 삭제)"""
    db_user = get_user(db, user_id)
    if not db_user:
        return False
    
    db_user.deleted_at = datetime.utcnow()
    db.commit()
    return True


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호 검증"""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def update_last_login(db: Session, user_id: int) -> None:
    """마지막 로그인 시간 업데이트"""
    db_user = get_user(db, user_id)
    if db_user:
        db_user.last_login_at = datetime.utcnow()
        db.commit()


# ============================================
# UserBodyMeasurement CRUD
# ============================================

def get_body_measurement(db: Session, user_id: int) -> Optional[UserBodyMeasurement]:
    """사용자 신체 치수 조회"""
    return db.query(UserBodyMeasurement).filter(
        UserBodyMeasurement.user_id == user_id
    ).first()


def create_body_measurement(
    db: Session, 
    user_id: int, 
    measurement: BodyMeasurementCreate
) -> UserBodyMeasurement:
    """신체 치수 생성"""
    db_measurement = UserBodyMeasurement(
        user_id=user_id,
        **measurement.model_dump()
    )
    
    db.add(db_measurement)
    db.commit()
    db.refresh(db_measurement)
    return db_measurement


def update_body_measurement(
    db: Session,
    user_id: int,
    measurement: BodyMeasurementUpdate
) -> Optional[UserBodyMeasurement]:
    """신체 치수 수정"""
    db_measurement = get_body_measurement(db, user_id)
    if not db_measurement:
        return None
    
    update_data = measurement.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_measurement, field, value)
    
    db.commit()
    db.refresh(db_measurement)
    return db_measurement


# ============================================
# Category CRUD
# ============================================

def get_category(db: Session, category_id: int) -> Optional[Category]:
    """카테고리 조회"""
    return db.query(Category).filter(Category.id == category_id).first()


def get_categories(
    db: Session,
    parent_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100
) -> List[Category]:
    """카테고리 목록 조회"""
    query = db.query(Category)
    
    if parent_id is not None:
        query = query.filter(Category.parent_id == parent_id)
    
    if is_active is not None:
        query = query.filter(Category.is_active == is_active)
    
    return query.order_by(Category.display_order).offset(skip).limit(limit).all()


def get_category_tree(db: Session) -> List[Category]:
    """카테고리 트리 구조 조회 (최상위만)"""
    return db.query(Category).filter(
        Category.parent_id.is_(None),
        Category.is_active == True
    ).order_by(Category.display_order).all()


def create_category(db: Session, category: CategoryCreate) -> Category:
    """카테고리 생성"""
    db_category = Category(**category.model_dump())
    
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


def update_category(
    db: Session,
    category_id: int,
    category: CategoryUpdate
) -> Optional[Category]:
    """카테고리 수정"""
    db_category = get_category(db, category_id)
    if not db_category:
        return None
    
    update_data = category.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_category, field, value)
    
    db.commit()
    db.refresh(db_category)
    return db_category


def delete_category(db: Session, category_id: int) -> bool:
    """카테고리 삭제"""
    db_category = get_category(db, category_id)
    if not db_category:
        return False
    
    # 하위 카테고리나 상품이 있으면 삭제 불가
    has_children = db.query(Category).filter(
        Category.parent_id == category_id
    ).first()
    if has_children:
        return False
    
    has_products = db.query(Product).filter(
        Product.category_id == category_id
    ).first()
    if has_products:
        return False
    
    db.delete(db_category)
    db.commit()
    return True


# ============================================
# Product CRUD
# ============================================

def get_product(db: Session, product_id: int) -> Optional[Product]:
    """상품 조회"""
    return db.query(Product).filter(
        Product.id == product_id,
        Product.deleted_at.is_(None)
    ).first()


def get_products(
    db: Session,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
) -> List[Product]:
    """상품 목록 조회"""
    query = db.query(Product).filter(Product.deleted_at.is_(None))
    
    if category_id:
        query = query.filter(Product.category_id == category_id)
    
    if is_active is not None:
        query = query.filter(Product.is_active == is_active)
    
    if search:
        query = query.filter(
            or_(
                Product.name.contains(search),
                Product.description.contains(search),
                Product.tags.contains(search)
            )
        )
    
    return query.order_by(desc(Product.created_at)).offset(skip).limit(limit).all()


def create_product(db: Session, product: ProductCreate) -> Product:
    """상품 생성"""
    db_product = Product(**product.model_dump())
    
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


def update_product(
    db: Session,
    product_id: int,
    product: ProductUpdate
) -> Optional[Product]:
    """상품 수정"""
    db_product = get_product(db, product_id)
    if not db_product:
        return None
    
    update_data = product.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_product, field, value)
    
    db.commit()
    db.refresh(db_product)
    return db_product


def delete_product(db: Session, product_id: int) -> bool:
    """상품 삭제 (소프트 삭제)"""
    db_product = get_product(db, product_id)
    if not db_product:
        return False
    
    db_product.deleted_at = datetime.utcnow()
    db.commit()
    return True


# ============================================
# ProductOption CRUD
# ============================================

def get_product_option(db: Session, option_id: int) -> Optional[ProductOption]:
    """상품 옵션 조회"""
    return db.query(ProductOption).filter(ProductOption.id == option_id).first()


def get_product_options(
    db: Session,
    product_id: int,
    is_active: Optional[bool] = None
) -> List[ProductOption]:
    """특정 상품의 옵션 목록"""
    query = db.query(ProductOption).filter(ProductOption.product_id == product_id)
    
    if is_active is not None:
        query = query.filter(ProductOption.is_active == is_active)
    
    return query.all()


def create_product_option(
    db: Session,
    option: ProductOptionCreate
) -> ProductOption:
    """상품 옵션 생성"""
    db_option = ProductOption(**option.model_dump())
    
    db.add(db_option)
    db.commit()
    db.refresh(db_option)
    return db_option


def update_product_option(
    db: Session,
    option_id: int,
    option: ProductOptionUpdate
) -> Optional[ProductOption]:
    """상품 옵션 수정"""
    db_option = get_product_option(db, option_id)
    if not db_option:
        return None
    
    update_data = option.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_option, field, value)
    
    db.commit()
    db.refresh(db_option)
    return db_option


def update_product_option_quantity(
    db: Session,
    option_id: int,
    quantity_change: int
) -> Optional[ProductOption]:
    """상품 옵션 재고 수량 변경"""
    db_option = get_product_option(db, option_id)
    if not db_option:
        return None
    
    db_option.quantity += quantity_change
    
    # 재고가 음수가 되지 않도록
    if db_option.quantity < 0:
        db_option.quantity = 0
    
    db.commit()
    db.refresh(db_option)
    return db_option


# ============================================
# UsedProduct CRUD
# ============================================

def get_used_product(db: Session, product_id: int) -> Optional[UsedProduct]:
    """중고 상품 조회"""
    return db.query(UsedProduct).filter(
        UsedProduct.id == product_id,
        UsedProduct.deleted_at.is_(None)
    ).first()


def get_used_products(
    db: Session,
    category_id: Optional[int] = None,
    seller_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
) -> List[UsedProduct]:
    """중고 상품 목록 조회"""
    query = db.query(UsedProduct).filter(UsedProduct.deleted_at.is_(None))
    
    if category_id:
        query = query.filter(UsedProduct.category_id == category_id)
    
    if seller_id:
        query = query.filter(UsedProduct.seller_id == seller_id)
    
    if status:
        query = query.filter(UsedProduct.status == status)
    
    return query.order_by(desc(UsedProduct.created_at)).offset(skip).limit(limit).all()


def create_used_product(
    db: Session,
    seller_id: int,
    product: UsedProductCreate
) -> UsedProduct:
    """중고 상품 생성"""
    db_product = UsedProduct(
        seller_id=seller_id,
        **product.model_dump()
    )
    
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


def update_used_product(
    db: Session,
    product_id: int,
    product: UsedProductUpdate
) -> Optional[UsedProduct]:
    """중고 상품 수정"""
    db_product = get_used_product(db, product_id)
    if not db_product:
        return None
    
    update_data = product.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_product, field, value)
    
    db.commit()
    db.refresh(db_product)
    return db_product


def approve_used_product(db: Session, product_id: int) -> Optional[UsedProduct]:
    """중고 상품 승인"""
    db_product = get_used_product(db, product_id)
    if not db_product:
        return None
    
    db_product.status = "approved"
    db.commit()
    db.refresh(db_product)
    return db_product


def reject_used_product(db: Session, product_id: int) -> Optional[UsedProduct]:
    """중고 상품 거절"""
    db_product = get_used_product(db, product_id)
    if not db_product:
        return None
    
    db_product.status = "rejected"
    db.commit()
    db.refresh(db_product)
    return db_product


# ============================================
# Cart CRUD
# ============================================

def get_cart(db: Session, user_id: int) -> Optional[Cart]:
    """사용자 장바구니 조회"""
    return db.query(Cart).filter(Cart.user_id == user_id).first()


def get_or_create_cart(db: Session, user_id: int) -> Cart:
    """장바구니 조회 또는 생성"""
    cart = get_cart(db, user_id)
    if not cart:
        cart = Cart(user_id=user_id)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart


def add_to_cart(
    db: Session,
    user_id: int,
    item: CartItemCreate
) -> CartItem:
    """장바구니에 상품 추가"""
    cart = get_or_create_cart(db, user_id)
    
    # 이미 같은 상품이 있는지 확인
    existing_item = db.query(CartItem).filter(
        CartItem.cart_id == cart.id,
        CartItem.product_option_type == item.product_option_type,
        CartItem.product_option_id == item.product_option_id
    ).first()
    
    if existing_item:
        # 수량만 증가
        existing_item.quantity += item.quantity
        db.commit()
        db.refresh(existing_item)
        return existing_item
    
    # 새로운 항목 추가
    db_item = CartItem(
        cart_id=cart.id,
        **item.model_dump()
    )
    
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def update_cart_item(
    db: Session,
    item_id: int,
    item: CartItemUpdate
) -> Optional[CartItem]:
    """장바구니 항목 수량 수정"""
    db_item = db.query(CartItem).filter(CartItem.id == item_id).first()
    if not db_item:
        return None
    
    db_item.quantity = item.quantity
    db.commit()
    db.refresh(db_item)
    return db_item


def remove_from_cart(db: Session, item_id: int) -> bool:
    """장바구니에서 항목 삭제"""
    db_item = db.query(CartItem).filter(CartItem.id == item_id).first()
    if not db_item:
        return False
    
    db.delete(db_item)
    db.commit()
    return True


def clear_cart(db: Session, user_id: int) -> bool:
    """장바구니 비우기"""
    cart = get_cart(db, user_id)
    if not cart:
        return False
    
    db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
    db.commit()
    return True


# ============================================
# ShippingAddress CRUD
# ============================================

def get_shipping_address(db: Session, address_id: int) -> Optional[ShippingAddress]:
    """배송지 조회"""
    return db.query(ShippingAddress).filter(
        ShippingAddress.id == address_id,
        ShippingAddress.deleted_at.is_(None)
    ).first()


def get_shipping_addresses(db: Session, user_id: int) -> List[ShippingAddress]:
    """사용자의 배송지 목록"""
    return db.query(ShippingAddress).filter(
        ShippingAddress.user_id == user_id,
        ShippingAddress.deleted_at.is_(None)
    ).order_by(desc(ShippingAddress.is_default)).all()


def get_default_shipping_address(db: Session, user_id: int) -> Optional[ShippingAddress]:
    """기본 배송지 조회"""
    return db.query(ShippingAddress).filter(
        ShippingAddress.user_id == user_id,
        ShippingAddress.is_default == True,
        ShippingAddress.deleted_at.is_(None)
    ).first()


def create_shipping_address(
    db: Session,
    user_id: int,
    address: ShippingAddressCreate
) -> ShippingAddress:
    """배송지 생성"""
    # 기본 배송지로 설정하는 경우, 기존 기본 배송지 해제
    if address.is_default:
        db.query(ShippingAddress).filter(
            ShippingAddress.user_id == user_id,
            ShippingAddress.is_default == True
        ).update({"is_default": False})
    
    db_address = ShippingAddress(
        user_id=user_id,
        **address.model_dump()
    )
    
    db.add(db_address)
    db.commit()
    db.refresh(db_address)
    return db_address


def update_shipping_address(
    db: Session,
    address_id: int,
    address: ShippingAddressUpdate
) -> Optional[ShippingAddress]:
    """배송지 수정"""
    db_address = get_shipping_address(db, address_id)
    if not db_address:
        return None
    
    # 기본 배송지로 변경하는 경우
    update_data = address.model_dump(exclude_unset=True)
    if update_data.get('is_default') == True:
        db.query(ShippingAddress).filter(
            ShippingAddress.user_id == db_address.user_id,
            ShippingAddress.is_default == True,
            ShippingAddress.id != address_id
        ).update({"is_default": False})
    
    for field, value in update_data.items():
        setattr(db_address, field, value)
    
    db.commit()
    db.refresh(db_address)
    return db_address


def delete_shipping_address(db: Session, address_id: int) -> bool:
    """배송지 삭제 (소프트 삭제)"""
    db_address = get_shipping_address(db, address_id)
    if not db_address:
        return False
    
    db_address.deleted_at = datetime.utcnow()
    db.commit()
    return True


# ============================================
# Order CRUD
# ============================================

def get_order(db: Session, order_id: int) -> Optional[Order]:
    """주문 조회"""
    return db.query(Order).filter(Order.id == order_id).first()


def get_order_by_number(db: Session, order_number: str) -> Optional[Order]:
    """주문 번호로 조회"""
    return db.query(Order).filter(Order.order_number == order_number).first()


def get_user_orders(
    db: Session,
    user_id: int,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
) -> List[Order]:
    """사용자의 주문 목록"""
    query = db.query(Order).filter(Order.user_id == user_id)
    
    if status:
        query = query.filter(Order.status == status)
    
    return query.order_by(desc(Order.created_at)).offset(skip).limit(limit).all()


def create_order(
    db: Session,
    user_id: int,
    order_data: OrderCreate
) -> Order:
    """주문 생성"""
    import uuid
    
    # 1. 주문 번호 생성
    order_number = f"ORD-{uuid.uuid4().hex[:12].upper()}"
    
    # 2. 주문 항목별 가격 계산
    subtotal = Decimal('0.00')
    order_items_data = []
    
    for item in order_data.items:
        # 상품 옵션 조회 및 가격 확인
        if item.product_option_type.value == "new":
            option = db.query(ProductOption).filter(
                ProductOption.id == item.product_option_id
            ).first()
            if not option or option.quantity < item.quantity:
                raise ValueError(f"재고가 부족합니다: 옵션 ID {item.product_option_id}")
            product_price = option.product.price
        else:  # used
            option = db.query(UsedProductOption).filter(
                UsedProductOption.id == item.product_option_id
            ).first()
            if not option or option.quantity < item.quantity:
                raise ValueError(f"재고가 부족합니다: 옵션 ID {item.product_option_id}")
            product_price = option.used_product.price
        
        unit_price = product_price
        item_subtotal = unit_price * item.quantity
        subtotal += item_subtotal
        
        order_items_data.append({
            'product_option_type': item.product_option_type,
            'product_option_id': item.product_option_id,
            'quantity': item.quantity,
            'unit_price': unit_price,
            'subtotal': item_subtotal
        })
    
    # 3. 배송비 계산 (예: 50,000원 이상 무료배송)
    shipping_fee = Decimal('3000.00') if subtotal < 50000 else Decimal('0.00')
    
    # 4. 최종 금액 계산
    total_amount = subtotal + shipping_fee - order_data.points_used
    
    # 5. 주문 생성
    db_order = Order(
        user_id=user_id,
        order_number=order_number,
        shipping_address_id=order_data.shipping_address_id,
        subtotal=subtotal,
        discount_amount=Decimal('0.00'),
        shipping_fee=shipping_fee,
        total_amount=total_amount,
        points_used=order_data.points_used,
        payment_method=order_data.payment_method,
        shipping_request=order_data.shipping_request,
        status="pending"
    )
    
    db.add(db_order)
    db.flush()  # ID 생성
    
    # 6. 주문 항목 생성
    for item_data in order_items_data:
        order_item = OrderItem(order_id=db_order.id, **item_data)
        db.add(order_item)
    
    # 7. 재고 차감
    for item in order_data.items:
        if item.product_option_type.value == "new":
            update_product_option_quantity(db, item.product_option_id, -item.quantity)
        else:
            option = db.query(UsedProductOption).filter(
                UsedProductOption.id == item.product_option_id
            ).first()
            if option:
                option.quantity -= item.quantity
    
    # 8. 포인트 차감
    if order_data.points_used > 0:
        current_balance = get_user_point_balance(db, user_id)
        create_point_history(
            db=db,
            user_id=user_id,
            order_id=db_order.id,
            amount=-order_data.points_used,
            balance_after=current_balance - order_data.points_used,
            point_type="use",
            description=f"주문 {order_number} 포인트 사용"
        )
    
    db.commit()
    db.refresh(db_order)
    return db_order


def update_order_status(
    db: Session,
    order_id: int,
    new_status: str,
    notes: Optional[str] = None
) -> Optional[Order]:
    """주문 상태 변경"""
    db_order = get_order(db, order_id)
    if not db_order:
        return None
    
    old_status = db_order.status
    db_order.status = new_status
    
    # 상태 이력 기록
    status_history = OrderStatusHistory(
        order_id=order_id,
        status=new_status,
        notes=notes or f"{old_status} -> {new_status}"
    )
    db.add(status_history)
    
    db.commit()
    db.refresh(db_order)
    return db_order


def cancel_order(db: Session, order_id: int) -> Optional[Order]:
    """주문 취소"""
    db_order = get_order(db, order_id)
    if not db_order:
        return None
    
    # 이미 배송 시작된 주문은 취소 불가
    if db_order.status in ["shipped", "delivered"]:
        raise ValueError("배송 중이거나 배송 완료된 주문은 취소할 수 없습니다")
    
    # 재고 복구
    for item in db_order.items:
        if item.product_option_type.value == "new":
            update_product_option_quantity(db, item.product_option_id, item.quantity)
        else:
            option = db.query(UsedProductOption).filter(
                UsedProductOption.id == item.product_option_id
            ).first()
            if option:
                option.quantity += item.quantity
    
    # 포인트 환불
    if db_order.points_used > 0:
        current_balance = get_user_point_balance(db, db_order.user_id)
        create_point_history(
            db=db,
            user_id=db_order.user_id,
            order_id=order_id,
            amount=db_order.points_used,
            balance_after=current_balance + db_order.points_used,
            point_type="refund",
            description=f"주문 {db_order.order_number} 취소 포인트 환불"
        )
    
    db_order.status = "cancelled"
    db.commit()
    db.refresh(db_order)
    return db_order


# ============================================
# Review CRUD
# ============================================

def get_review(db: Session, review_id: int) -> Optional[Review]:
    """리뷰 조회"""
    return db.query(Review).filter(Review.id == review_id).first()


def get_product_reviews(
    db: Session,
    product_id: int,
    product_type: str = "new",
    skip: int = 0,
    limit: int = 100
) -> List[Review]:
    """상품의 리뷰 목록"""
    # OrderItem을 통해 해당 상품의 리뷰 조회
    query = db.query(Review).join(OrderItem).filter(
        OrderItem.product_option_type == product_type
    )
    
    if product_type == "new":
        query = query.join(ProductOption).filter(
            ProductOption.product_id == product_id
        )
    else:
        query = query.join(UsedProductOption).filter(
            UsedProductOption.used_product_id == product_id
        )
    
    return query.order_by(desc(Review.created_at)).offset(skip).limit(limit).all()


def create_review(
    db: Session,
    user_id: int,
    review: ReviewCreate
) -> Review:
    """리뷰 생성"""
    # 해당 주문 항목이 사용자의 것인지 확인
    order_item = db.query(OrderItem).join(Order).filter(
        OrderItem.id == review.order_item_id,
        Order.user_id == user_id
    ).first()
    
    if not order_item:
        raise ValueError("주문 항목을 찾을 수 없습니다")
    
    # 이미 리뷰가 있는지 확인
    existing_review = db.query(Review).filter(
        Review.order_item_id == review.order_item_id
    ).first()
    
    if existing_review:
        raise ValueError("이미 리뷰를 작성하셨습니다")
    
    db_review = Review(
        user_id=user_id,
        **review.model_dump()
    )
    
    db.add(db_review)
    db.commit()
    db.refresh(db_review)
    return db_review


def update_review(
    db: Session,
    review_id: int,
    review: ReviewUpdate
) -> Optional[Review]:
    """리뷰 수정"""
    db_review = get_review(db, review_id)
    if not db_review:
        return None
    
    update_data = review.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_review, field, value)
    
    db.commit()
    db.refresh(db_review)
    return db_review


def delete_review(db: Session, review_id: int) -> bool:
    """리뷰 삭제"""
    db_review = get_review(db, review_id)
    if not db_review:
        return False
    
    db.delete(db_review)
    db.commit()
    return True


# ============================================
# Point CRUD
# ============================================

def get_user_point_balance(db: Session, user_id: int) -> Decimal:
    """사용자 현재 포인트 잔액 조회"""
    latest = db.query(PointHistory).filter(
        PointHistory.user_id == user_id
    ).order_by(desc(PointHistory.created_at)).first()
    
    return latest.balance_after if latest else Decimal('0.00')


def get_point_history(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100
) -> List[PointHistory]:
    """포인트 내역 조회"""
    return db.query(PointHistory).filter(
        PointHistory.user_id == user_id
    ).order_by(desc(PointHistory.created_at)).offset(skip).limit(limit).all()


def create_point_history(
    db: Session,
    user_id: int,
    amount: Decimal,
    balance_after: Decimal,
    point_type: str,
    description: Optional[str] = None,
    order_id: Optional[int] = None
) -> PointHistory:
    """포인트 내역 생성"""
    db_history = PointHistory(
        user_id=user_id,
        order_id=order_id,
        amount=amount,
        balance_after=balance_after,
        type=point_type,
        description=description
    )
    
    db.add(db_history)
    db.commit()
    db.refresh(db_history)
    return db_history


def earn_points(
    db: Session,
    user_id: int,
    amount: Decimal,
    description: str
) -> PointHistory:
    """포인트 적립"""
    current_balance = get_user_point_balance(db, user_id)
    new_balance = current_balance + amount
    
    return create_point_history(
        db=db,
        user_id=user_id,
        amount=amount,
        balance_after=new_balance,
        point_type="earn",
        description=description
    )


# ============================================
# Utility Functions
# ============================================

def get_total_count(db: Session, model) -> int:
    """전체 개수 조회 (페이지네이션용)"""
    return db.query(model).count()


def soft_delete_expired_items(db: Session, model, days: int = 30) -> int:
    """오래된 항목 소프트 삭제"""
    from datetime import timedelta
    
    expiry_date = datetime.utcnow() - timedelta(days=days)
    
    count = db.query(model).filter(
        model.deleted_at.is_(None),
        model.created_at < expiry_date
    ).update({"deleted_at": datetime.utcnow()})
    
    db.commit()
    return count