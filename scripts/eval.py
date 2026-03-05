"""
평가용 데이터 적재 스크립트
벤치마크 평가에 필요한 추가 주문 데이터를 DB에 적재합니다.
"""
import os
import sys

# -------------------------------------------------
# 프로젝트 루트를 PYTHONPATH에 추가 (직접 실행용)
# -------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)

import logging
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import Session

import ecommerce.platform.backend.app.router.users.models
import ecommerce.platform.backend.app.router.products.models
import ecommerce.platform.backend.app.router.orders.models
import ecommerce.platform.backend.app.router.shipping.models
import ecommerce.platform.backend.app.router.carts.models
import ecommerce.platform.backend.app.router.points.models
import ecommerce.platform.backend.app.router.reviews.models
import ecommerce.platform.backend.app.router.user_history.models
import ecommerce.platform.backend.app.router.payments.models
import ecommerce.platform.backend.app.router.inventories.models
import ecommerce.platform.backend.app.router.chatbot_logs.models

from ecommerce.platform.backend.app.router.users.models import User, UserStatus, UserGender
from ecommerce.platform.backend.app.router.users.crud import hash_password
from ecommerce.platform.backend.app.router.products.models import ProductOption, ProductType, Category, Product
from ecommerce.platform.backend.app.router.orders.models import Order, OrderItem
from ecommerce.platform.backend.app.router.orders.schemas import OrderStatus
from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_eval_orders(db: Session):
    """평가용 추가 주문 데이터 생성 (Argument Accuracy 벤치마크 대응)"""

    def get_or_create_user(email, name):
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                password_hash=hash_password("password123"), 
                name=name,
                phone="010-2222-2222",
                status=UserStatus.ACTIVE,
                agree_marketing=True,
                agree_sms=True,
                agree_email=True,
                gender=UserGender.MALE,
            )
            db.add(user)
            db.flush()
            logger.info(f"✅ {email} 유저 생성 완료")
        
        address = db.query(ShippingAddress).filter(ShippingAddress.user_id == user.id).first()
        if not address:
            address = ShippingAddress(
                user_id=user.id,
                recipient_name=name,
                address1="서울시 강남구 테헤란로 123",
                address2="SKN 타워 10층",
                post_code="06123",
                phone="010-2222-2222",
                is_default=True
            )
            db.add(address)
            db.flush()
            logger.info(f"✅ {email} 배송지 생성 완료")
        return user, address

    user1, addr1 = get_or_create_user("test@example.com", "테스트1유저")
    user2, addr2 = get_or_create_user("test2@example.com", "테스트2유저")
    user3, addr3 = get_or_create_user("test3@example.com", "테스트3유저")

    new_product_option = db.query(ProductOption).first()
    if not new_product_option:
        logger.info("상품/옵션 데이터가 없어 평가용 임시 카테고리 및 상품 데이터를 생성합니다.")
        
        category = Category(id=9999, name="평가용 카테고리", display_order=1, is_active=True)
        db.add(category)
        db.flush()
        
        product = Product(
            id=9999,
            category_id=category.id,
            name="평가용 임시 상품",
            description="평가용으로 자동 생성된 상품입니다.",
            price=Decimal("15000"),
            is_active=True,
            tags="eval"
        )
        db.add(product)
        db.flush()
        
        for i, color in enumerate(["BLACK", "WHITE", "NAVY", "GREY"]):
            opt = ProductOption(
                product_id=product.id,
                size_name="FREE",
                color=color,
                quantity=100,
                is_active=True
            )
            db.add(opt)
        db.flush()
        
        new_product_option = db.query(ProductOption).first()

    all_new_options = db.query(ProductOption).filter(ProductOption.is_active == True).limit(20).all()

    def create_order(user, address, order_num, subtotal, ship_fee, status, request_memo, opt_idx, qty, unit_price):
        opt = all_new_options[opt_idx % len(all_new_options)] if len(all_new_options) > opt_idx else new_product_option
        order = Order(
            user_id=user.id,
            order_number=order_num,
            shipping_address_id=address.id,
            subtotal=Decimal(subtotal),
            shipping_fee=Decimal(ship_fee),
            total_amount=Decimal(subtotal) + Decimal(ship_fee),
            status=status,
            payment_method="CARD",
            shipping_request=request_memo
        )
        db.add(order)
        db.flush()
        db.add(OrderItem(
            order_id=order.id,
            product_option_type=ProductType.NEW,
            product_option_id=opt.id,
            quantity=qty,
            unit_price=Decimal(unit_price),
            subtotal=Decimal(subtotal)
        ))
        db.flush()

    # 테스트 1번 유저 (test@example.com)
    create_order(user1, addr1, "ORD-eval_dataset-0001", "25000", "3000", OrderStatus.PREPARING, "부재 시 경비실에 맡겨주세요", 1, 1, "25000")
    create_order(user1, addr1, "ORD-eval_dataset-0002", "39000", "0", OrderStatus.DELIVERED, "문 앞에 놔주세요", 2, 1, "39000")
    create_order(user1, addr1, "ORD-eval_dataset-0003", "52000", "3000", OrderStatus.DELIVERED, "택배함에 넣어주세요", 3, 2, "26000")

    # 테스트 2번 유저 (test2@example.com)
    create_order(user2, addr2, "ORD-eval_dataset-0004", "25000", "3000", OrderStatus.PREPARING, "부재 시 경비실에 맡겨주세요", 1, 1, "25000")
    create_order(user2, addr2, "ORD-eval_dataset-0005", "39000", "0", OrderStatus.DELIVERED, "문 앞에 놔주세요", 2, 1, "39000")
    create_order(user2, addr2, "ORD-eval_dataset-0006", "52000", "3000", OrderStatus.DELIVERED, "택배함에 넣어주세요", 3, 2, "26000")

    # 테스트 3번 유저 (test3@example.com)
    create_order(user3, addr3, "ORD-eval_dataset-0007", "25000", "3000", OrderStatus.PREPARING, "부재 시 경비실에 맡겨주세요", 1, 1, "25000")
    create_order(user3, addr3, "ORD-eval_dataset-0008", "39000", "0", OrderStatus.DELIVERED, "문 앞에 놔주세요", 2, 1, "39000")
    create_order(user3, addr3, "ORD-eval_dataset-0009", "52000", "3000", OrderStatus.DELIVERED, "택배함에 넣어주세요", 3, 2, "26000")

    logger.info("✅ 3개의 계정에 대해 각각 3건씩 총 9건 생성 완료")


if __name__ == "__main__":
    from ecommerce.platform.backend.app.database import SessionLocal

    db = SessionLocal()

    try:
        logger.info("🚀 평가용 데이터 적재 시작...")
        create_eval_orders(db)
        db.commit()
        logger.info("✅ 평가용 데이터 적재 완료!")

    except Exception as e:
        logger.error(f"❌ 에러 발생: {e}", exc_info=True)
        db.rollback()

    finally:
        db.close()
