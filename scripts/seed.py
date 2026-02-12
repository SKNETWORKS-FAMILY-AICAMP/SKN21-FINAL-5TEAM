"""
Database Seeding Script
서버 시작 시 초기 데이터를 DB에 적재하는 스크립트입니다.
"""
import logging
import random
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from ecommerce.platform.backend.app.router.users.models import User, UserStatus
from ecommerce.platform.backend.app.router.products.models import (
    Category, Product, ProductOption, ProductType,
    UsedProduct, UsedProductOption, UsedProductCondition, UsedProductStatus
)
from ecommerce.platform.backend.app.router.orders.models import Order, OrderItem
from ecommerce.platform.backend.app.router.orders.schemas import OrderStatus
from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress
from ecommerce.platform.backend.app.router.users.crud import hash_password

logger = logging.getLogger(__name__)

def init_db(db: Session):
    """
    초기 데이터 적재 함수
    데이터가 비어있을 경우에만 실행됩니다.
    """
    try:
        # 1. 사용자 데이터 확인 및 생성
        if not db.query(User).first():
            logger.info("🛠️ 초기 사용자 데이터 생성 중...")
            create_users(db)
        
        # 2. 카테고리 데이터 확인 및 생성
        if not db.query(Category).first():
            logger.info("🛠️ 초기 카테고리 데이터 생성 중...")
            create_categories(db)
            
        # 3. 상품 데이터 확인 및 생성
        if not db.query(Product).first():
            logger.info("🛠️ 초기 상품 데이터 생성 중...")
            create_products(db)
        
        # 4. 중고 상품 상태 데이터 확인 및 생성
        if not db.query(UsedProductCondition).first():
            logger.info("🛠️ 초기 중고 상품 상태 데이터 생성 중...")
            create_used_product_conditions(db)
            
        # 5. 중고 상품 데이터 확인 및 생성
        if not db.query(UsedProduct).first():
            logger.info("🛠️ 초기 중고 상품 데이터 생성 중...")
            create_used_products(db)
            
        # 6. 배송지 데이터 확인 및 생성
        if not db.query(ShippingAddress).first():
            logger.info("🛠️ 초기 배송지 데이터 생성 중...")
            create_shipping_addresses(db)
            
        # 7. 주문 데이터 확인 및 생성
        if not db.query(Order).first():
            logger.info("🛠️ 초기 주문 데이터 생성 중...")
            create_orders(db)

        db.commit()
        logger.info("✅ 초기 데이터 적재 완료")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 초기 데이터 적재 실패: {e}")
        raise e

def create_users(db: Session):
    """테스트 사용자 생성"""
    users = [
        User(
            email="test@example.com",
            password_hash=hash_password("password123"), 
            name="테스트유저",
            phone="010-1234-5678",
            status=UserStatus.ACTIVE,
            agree_marketing=True,
            agree_sms=True,
            agree_email=True
        ),
        User(
            email="admin@example.com",
            password_hash=hash_password("admin123"),
            name="관리자",
            phone="010-9999-9999",
            status=UserStatus.ACTIVE,
            agree_marketing=False,
            agree_sms=False,
            agree_email=False
        )
    ]
    db.add_all(users)
    db.flush() 

def create_categories(db: Session):
    """카테고리 생성"""
    categories = {
        "상의": ["티셔츠", "셔츠/블라우스", "니트/스웨터", "후드/맨투맨"],
        "하의": ["청바지", "슬랙스", "스커트", "트레이닝 바지"],
        "아우터": ["코트", "자켓", "패딩", "가디건"],
        "신발": ["스니커즈", "구두", "부츠", "샌들"]
    }
    
    for main_name, sub_names in categories.items():
        main_cat = Category(name=main_name, parent_id=None, display_order=1)
        db.add(main_cat)
        db.flush() 
        
        for idx, sub_name in enumerate(sub_names):
            sub_cat = Category(name=sub_name, parent_id=main_cat.id, display_order=idx+1)
            db.add(sub_cat)
    db.flush()

def create_products(db: Session):
    """상품 및 옵션 생성"""
    # 상의 - 티셔츠 카테고리 조회
    tshirt_cat = db.query(Category).filter(Category.name == "티셔츠").first()
    
    if not tshirt_cat:
        return

    products = [
        Product(
            category_id=tshirt_cat.id,
            name="베이직 코튼 티셔츠",
            description="편안한 착용감의 기본 티셔츠입니다.",
            price=Decimal("15000"),
            is_active=True,
            tags="티셔츠,기본템,데일리"
        ),
        Product(
            category_id=tshirt_cat.id,
            name="오버핏 로고 티셔츠",
            description="트렌디한 오버핏 실루엣의 티셔츠입니다.",
            price=Decimal("25000"),
            is_active=True,
            tags="오버핏,로고,스트릿"
        )
    ]
    
    db.add_all(products)
    db.flush()
    
    # 옵션 추가
    for product in products:
        options = [
            ProductOption(product_id=product.id, size_name="M", color="White", quantity=100, is_active=True),
            ProductOption(product_id=product.id, size_name="L", color="White", quantity=100, is_active=True),
            ProductOption(product_id=product.id, size_name="M", color="Black", quantity=50, is_active=True),
            ProductOption(product_id=product.id, size_name="L", color="Black", quantity=50, is_active=True),
        ]
        db.add_all(options)
    db.flush()

def create_used_product_conditions(db: Session):
    """중고 상품 상태 생성"""
    conditions = [
        UsedProductCondition(condition_name="S급", depreciation_percent=10, description="새 상품과 거의 동일한 상태"),
        UsedProductCondition(condition_name="A급", depreciation_percent=30, description="사용감이 거의 없는 깨끗한 상태"),
        UsedProductCondition(condition_name="B급", depreciation_percent=50, description="약간의 사용감과 얼룩이 있을 수 있음"),
    ]
    db.add_all(conditions)
    db.flush()

def create_used_products(db: Session):
    """중고 상품 및 옵션 생성"""
    # 판매자(admin)와 카테고리(청바지), 상태(A급) 조회
    admin_user = db.query(User).filter(User.email == "admin@example.com").first()
    pants_cat = db.query(Category).filter(Category.name == "청바지").first()
    condition_a = db.query(UsedProductCondition).filter(UsedProductCondition.condition_name == "A급").first()

    if not admin_user or not pants_cat or not condition_a:
        logger.warning("중고 상품 생성을 위한 필수 데이터(유저, 카테고리, 상태)가 부족합니다.")
        return

    used_products = [
        UsedProduct(
            category_id=pants_cat.id,
            seller_id=admin_user.id,
            name="A급 리바이스 청바지",
            description="사이즈가 안 맞아서 팝니다. 2번 입었어요.",
            price=Decimal("45000"),
            condition_id=condition_a.id,
            status=UsedProductStatus.APPROVED, # 판매 승인됨
            tags="청바지,리바이스,중고"
        ),
        UsedProduct(
            category_id=pants_cat.id,
            seller_id=admin_user.id,
            name="빈티지 데님 자켓",
            description="빈티지 감성의 데님 자켓입니다.",
            price=Decimal("30000"),
            condition_id=condition_a.id,
            status=UsedProductStatus.PENDING, # 승인 대기중
            tags="데님,자켓,빈티지"
        )
    ]
    db.add_all(used_products)
    db.flush()

    for up in used_products:
        # 중고는 보통 수량이 1개
        opt = UsedProductOption(
            used_product_id=up.id, 
            size_name="M", 
            color="Blue", 
            quantity=1, 
            is_active=True
        )
        db.add(opt)
    db.flush()

def create_shipping_addresses(db: Session):
    """배송지 생성"""
    user = db.query(User).filter(User.email == "test@example.com").first()
    if not user:
        return
        
    address = ShippingAddress(
        user_id=user.id,
        recipient_name="테스트유저",
        address1="서울시 강남구 테헤란로 123",
        address2="SKN 타워 10층",
        post_code="06123",
        phone="010-1234-5678",
        is_default=True
    )
    db.add(address)
    db.flush()

def create_orders(db: Session):
    """주문 데이터 생성"""
    user = db.query(User).filter(User.email == "test@example.com").first()
    if not user:
        return
        
    # 배송지 조회 (없으면 생성)
    address = db.query(ShippingAddress).filter(ShippingAddress.user_id == user.id).first()
    if not address:
        create_shipping_addresses(db)
        address = db.query(ShippingAddress).filter(ShippingAddress.user_id == user.id).first()
    
    # 신상품 옵션 아무거나 하나 조회
    new_product_option = db.query(ProductOption).first()
    
    if not new_product_option:
        return

    # 1. 주문 완료 (배송완료) - 신상품
    order1 = Order(
        user_id=user.id,
        order_number=f"ORD-{datetime.now().strftime('%Y%m%d')}-0001",
        shipping_address_id=address.id,
        subtotal=Decimal("15000"),
        shipping_fee=Decimal("3000"),
        total_amount=Decimal("18000"),
        status=OrderStatus.DELIVERED,
        payment_method="CARD",
        shipping_request="문 앞에 놔주세요"
    )
    db.add(order1)
    db.flush()
    
    item1 = OrderItem(
        order_id=order1.id,
        product_option_type=ProductType.NEW,
        product_option_id=new_product_option.id,
        quantity=1,
        unit_price=Decimal("15000"),
        subtotal=Decimal("15000")
    )
    db.add(item1)

    # 2. 배송중인 주문 - 신상품 2개
    order2 = Order(
        user_id=user.id,
        order_number=f"ORD-{datetime.now().strftime('%Y%m%d')}-0002",
        shipping_address_id=address.id,
        subtotal=Decimal("30000"),
        shipping_fee=Decimal("3000"),
        total_amount=Decimal("33000"),
        status=OrderStatus.SHIPPED,
        payment_method="CARD",
        shipping_request="경비실에 맡겨주세요"
    )
    db.add(order2)
    db.flush()
    
    item2 = OrderItem(
        order_id=order2.id,
        product_option_type=ProductType.NEW,
        product_option_id=new_product_option.id,
        quantity=2,
        unit_price=Decimal("15000"),
        subtotal=Decimal("30000")
    )
    db.add(item2)
    
    # 3. 중고상품 주문 (결제완료)
    # 중고 상품 옵션 조회 (Approved 상태인 상품의 옵션)
    used_opt = db.query(UsedProductOption).join(UsedProduct).filter(
        UsedProduct.status == UsedProductStatus.APPROVED
    ).first()
    
    if used_opt:
        # 중고 상품 가격 조회
        used_product = db.query(UsedProduct).filter(UsedProduct.id == used_opt.used_product_id).first()
        price = used_product.price
        
        order3 = Order(
            user_id=user.id,
            order_number=f"ORD-{datetime.now().strftime('%Y%m%d')}-0003",
            shipping_address_id=address.id,
            subtotal=price,
            shipping_fee=Decimal("2500"),
            total_amount=price + Decimal("2500"),
            status=OrderStatus.PAID,
            payment_method="CARD",
            shipping_request="배송 전 연락바랍니다"
        )
        db.add(order3)
        db.flush()
        
        item3 = OrderItem(
            order_id=order3.id,
            product_option_type=ProductType.USED,
            product_option_id=used_opt.id,
            quantity=1,
            unit_price=price,
            subtotal=price
        )
        db.add(item3)

    db.flush()
