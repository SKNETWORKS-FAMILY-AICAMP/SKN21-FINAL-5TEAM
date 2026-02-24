"""
Database Seeding Script
서버 시작 시 초기 데이터를 DB에 적재하는 스크립트입니다.
"""
import os
import sys

# -------------------------------------------------
# 프로젝트 루트를 PYTHONPATH에 추가 (직접 실행용)
# -------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)

# -------------------------------------------------
# 표준 라이브러리
# -------------------------------------------------
import logging
import random
import csv
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session

import ecommerce.platform.backend.app.router.users.models
import ecommerce.platform.backend.app.router.products.models
import ecommerce.platform.backend.app.router.orders.models
import ecommerce.platform.backend.app.router.shipping.models
import ecommerce.platform.backend.app.router.points.models
import ecommerce.platform.backend.app.router.carts.models
import ecommerce.platform.backend.app.router.reviews.models
import ecommerce.platform.backend.app.router.payments.models
import ecommerce.platform.backend.app.router.inventories.models
import ecommerce.platform.backend.app.router.user_history.models

# -------------------------------------------------
# 실제 사용할 클래스 import
# -------------------------------------------------
from ecommerce.platform.backend.app.router.users.models import User, UserStatus, UserRole
from ecommerce.platform.backend.app.router.products.models import (
    Category, Product, ProductOption, ProductType,
    UsedProduct, UsedProductOption, UsedProductCondition, UsedProductStatus,
    ProductImage
)
from ecommerce.platform.backend.app.router.orders.models import Order, OrderItem
from ecommerce.platform.backend.app.router.orders.schemas import OrderStatus
from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress
from ecommerce.platform.backend.app.router.users.crud import hash_password
from ecommerce.platform.backend.app.router.points.models import IssuedVoucher

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

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
                    
        # 상품 옵션 데이터 확인 및 생성
        if not db.query(ProductOption).first():
            create_product_options(db)

        # 상품 이미지 데이터 확인 및 생성
        if not db.query(ProductImage).first():
            create_product_images(db)
        
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

        # 🔥 8. 테스트 상품권 생성 (항상 체크)
        if not db.query(IssuedVoucher).first():
            logger.info("🛠️ 초기 상품권 생성 중...")
            create_test_vouchers(db)

        db.commit()
        logger.info("✅ 초기 데이터 적재 완료")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 초기 데이터 적재 실패: {e}")
        raise e

def create_test_vouchers(db: Session):
    """테스트용 상품권 생성"""

    existing = db.query(IssuedVoucher).filter(
        IssuedVoucher.voucher_code.in_(["11111111", "22222222"])
    ).first()

    if existing:
        return

    # 🔥 test 사용자 조회
    test_user = db.query(User).filter(User.email == "test@example.com").first()

    if not test_user:
        return

    vouchers = [
        IssuedVoucher(
            user_id=test_user.id,
            voucher_code="11111111",
            amount=10000,
            is_used=False
        ),
        IssuedVoucher(
            user_id=test_user.id,
            voucher_code="22222222",
            amount=10000,
            is_used=False
        ),
    ]

    db.add_all(vouchers)
    db.flush()


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
            agree_email=False,
            role=UserRole.ADMIN
        )
    ]
    db.add_all(users)
    db.flush() 

# ============================================
# categoty
# ============================================
def create_categories(db: Session):
    file_path = DATA_DIR / "categories.csv"

    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.add(Category(
                id=int(row["id"]),
                name=row["name"],
                parent_id=int(row["parent_id"]) if row["parent_id"] else None,
                display_order=int(row["display_order"]),
                is_active = str(row["is_active"]).strip().lower() in ("1", "true", "t", "yes", "y"),
                created_at=datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S") if row["created_at"] else None,
                updated_at=datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S") if row["updated_at"] else None,
            ))
    db.flush()

# ============================================
# product
# ============================================
def create_products(db: Session):
    file_path = DATA_DIR / "products.csv"

    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.add(Product(
                id=int(row["id"]),
                category_id=int(row["category_id"]),
                name=row["name"],
                description=row["description"],
                price=Decimal(row["price"]),
                is_active = str(row["is_active"]).strip().lower() in ("1", "true", "t", "yes", "y"),
                tags=row["tags"],
                created_at=datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S") if row["created_at"] else None,
                updated_at=datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S") if row["updated_at"] else None,
            ))
    db.flush()
    
# ============================================
# product option   
# ============================================
def create_product_options(db: Session):
    file_path = DATA_DIR / "productoptions.csv"

    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.add(ProductOption(
                id=int(row["id"]),
                product_id=int(row["product_id"]),
                size_name=row["size_name"],
                color=row["color"],
                quantity=int(row["quantity"]),
                is_active = str(row["is_active"]).strip().lower() in ("1", "true", "t", "yes", "y"),
                created_at=datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S") if row["created_at"] else None,
                updated_at=datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S") if row["updated_at"] else None,
            ))
    db.flush()

# ============================================
# product image
# ============================================
def create_product_images(db: Session):
    file_path = DATA_DIR / "productimages.csv"

    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.add(ProductImage(
                id=int(row["id"]),
                product_type=row["product_type"],
                product_id=int(row["product_id"]),
                image_url=row["image_url"],
                display_order=int(row["display_order"]),
                is_primary = str(row["is_primary"]).strip().lower() in ("1", "true", "t", "yes", "y"),
                created_at=datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S") if row["created_at"] else None,
            ))
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

if __name__ == "__main__":
    from ecommerce.platform.backend.app.database import SessionLocal

    db = SessionLocal()

    try:
        init_db(db)
        print("✅ 적재 완료")

    except Exception as e:
        print("❌ 에러 발생:", e)

    finally:
        db.close()