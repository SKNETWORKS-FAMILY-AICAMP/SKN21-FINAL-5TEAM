
import sys
import os
import random
from datetime import datetime
from decimal import Decimal

# 프로젝트 루트 경로 추가 (모듈 임포트용)
sys.path.append(os.getcwd())

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# 1. 모델 임포트 (위치 주의)
from ecommerce.platform.backend.app.database import DATABASE_URL, Base
from ecommerce.platform.backend.app.router.users.models import User, UserStatus
from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress
from ecommerce.platform.backend.app.db.models import (
    Product, Category, Order, OrderItem, OrderStatus, 
    Payment, PaymentStatus, ProductOption, ProductType
)

# 2. DB 세션 설정
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def seed_data():
    session = SessionLocal()
    try:
        print("🌱 데이터 시딩 시작...")

        # --------------------------------------------------------
        # 1. 카테고리 생성
        # --------------------------------------------------------
        print("📦 카테고리 생성 중...")
        categories = [
            {"name": "상의", "display_order": 1},
            {"name": "하의", "display_order": 2},
            {"name": "아우터", "display_order": 3},
            {"name": "신발", "display_order": 4},
        ]
        
        db_categories = []
        for cat_data in categories:
            # 중복 체크
            stmt = select(Category).where(Category.name == cat_data["name"])
            existing = session.execute(stmt).scalar_one_or_none()
            if not existing:
                cat = Category(**cat_data)
                session.add(cat)
                db_categories.append(cat)
            else:
                db_categories.append(existing)
        
        session.flush() # ID 할당

        # --------------------------------------------------------
        # 2. 상품 생성
        # --------------------------------------------------------
        print("👕 상품 생성 중...")
        products_data = [
            {
                "name": "오버핏 코튼 티셔츠",
                "price": Decimal("35000"),
                "category_id": db_categories[0].id,
                "description": "편안한 착용감의 데일리 티셔츠",
                "options": ["M", "L", "XL"]
            },
            {
                "name": "와이드 데님 팬츠",
                "price": Decimal("59000"),
                "category_id": db_categories[1].id,
                "description": "트렌디한 핏의 데님 팬츠",
                "options": ["28", "30", "32"]
            },
            {
                "name": "울 블렌드 코트",
                "price": Decimal("249000"),
                "category_id": db_categories[2].id,
                "description": "겨울철 필수 아이템",
                "options": ["95", "100", "105"]
            }
        ]

        db_products = []
        for p_data in products_data:
            stmt = select(Product).where(Product.name == p_data["name"])
            existing = session.execute(stmt).scalar_one_or_none()
            
            if not existing:
                prod = Product(
                    name=p_data["name"],
                    price=p_data["price"],
                    category_id=p_data["category_id"],
                    description=p_data["description"],
                    is_active=True
                )
                session.add(prod)
                session.flush() # ID 생성

                # 옵션 생성
                for opt_name in p_data["options"]:
                    option = ProductOption(
                        product_id=prod.id,
                        size_name=opt_name,
                        quantity=100, # 재고
                        is_active=True
                    )
                    session.add(option)
                
                db_products.append(prod)
            else:
                db_products.append(existing)

        # --------------------------------------------------------
        # 3. 사용자 생성
        # --------------------------------------------------------
        print("👤 사용자 생성 중...")
        users_data = [
            {"email": "test@example.com", "name": "테스트유저", "phone": "010-1234-5678"},
            {"email": "vip@example.com", "name": "VIP회원", "phone": "010-9876-5432"},
        ]

        db_users = []
        for u_data in users_data:
            stmt = select(User).where(User.email == u_data["email"])
            existing = session.execute(stmt).scalar_one_or_none()
            
            if not existing:
                user = User(
                    email=u_data["email"],
                    password_hash="hashed_secret_password", # 실제론 해싱해야 함
                    name=u_data["name"],
                    phone=u_data["phone"],
                    status=UserStatus.ACTIVE
                )
                session.add(user)
                session.flush()
                
                # 배송지 추가
                shipping = ShippingAddress(
                    user_id=user.id,
                    recipient_name=user.name,
                    phone=user.phone,
                    address1="서울시 강남구 테헤란로 123",
                    address2="CS타워 10층",
                    is_default=True
                )
                session.add(shipping)
                db_users.append(user)
            else:
                db_users.append(existing)

        # --------------------------------------------------------
        # 4. 주문 내역 생성 (테스트유저)
        # --------------------------------------------------------
        print("🛍️ 주문 내역 생성 중...")
        if db_users and db_products:
            target_user = db_users[0]
            
            # 배송지 조회
            stmt = select(ShippingAddress).where(ShippingAddress.user_id == target_user.id)
            shipping_addr = session.execute(stmt).scalars().first()

            # 주문 1: 결제 완료 상태
            order1 = Order(
                user_id=target_user.id,
                order_number=f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}",
                shipping_address_id=shipping_addr.id,
                subtotal=Decimal("35000"),
                total_amount=Decimal("38000"), # 배송비 3000원 가정
                shipping_fee=Decimal("3000"),
                status=OrderStatus.PAID,
                payment_method="CARD"
            )
            session.add(order1)
            session.flush()

            # 주문 아이템 (상품 1번)
            item1 = OrderItem(
                order_id=order1.id,
                product_option_type=ProductType.NEW,
                product_option_id=1, # 간단하게 1번 옵션 (실제론 조회 필요)
                quantity=1,
                unit_price=Decimal("35000"),
                subtotal=Decimal("35000")
            )
            session.add(item1)

            # 결제 정보
            payment1 = Payment(
                order_id=order1.id,
                payment_method="CARD",
                payment_status=PaymentStatus.COMPLETED,
                amount=Decimal("38000")
            )
            session.add(payment1)

        session.commit()
        print("✅ 데이터 시딩 완료!")
        
    except Exception as e:
        session.rollback()
        print(f"❌ 에러 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    seed_data()
