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

from ecommerce.platform.backend.app.router.users.models import User
from ecommerce.platform.backend.app.router.products.models import ProductOption, ProductType
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
    user = db.query(User).filter(User.email == "test@example.com").first()
    if not user:
        logger.warning("테스트 유저가 없습니다. seed.py를 먼저 실행하세요.")
        return

    address = db.query(ShippingAddress).filter(ShippingAddress.user_id == user.id).first()
    if not address:
        logger.warning("배송지가 없습니다. seed.py를 먼저 실행하세요.")
        return

    new_product_option = db.query(ProductOption).first()
    if not new_product_option:
        logger.warning("상품 옵션이 없습니다. seed.py를 먼저 실행하세요.")
        return

    # 서로 다른 상품 옵션을 연결하여 시나리오 다양성 확보
    all_new_options = db.query(ProductOption).filter(ProductOption.is_active == True).limit(5).all()

    # 4. 상품준비중 주문 (취소 테스트 2건째)
    opt4 = all_new_options[1] if len(all_new_options) > 1 else new_product_option
    order4 = Order(
        user_id=user.id,
        order_number="ORD-eval_dataset-0004",
        shipping_address_id=address.id,
        subtotal=Decimal("25000"),
        shipping_fee=Decimal("3000"),
        total_amount=Decimal("28000"),
        status=OrderStatus.PREPARING,
        payment_method="CARD",
        shipping_request="부재 시 경비실에 맡겨주세요"
    )
    db.add(order4)
    db.flush()
    db.add(OrderItem(
        order_id=order4.id,
        product_option_type=ProductType.NEW,
        product_option_id=opt4.id,
        quantity=1,
        unit_price=Decimal("25000"),
        subtotal=Decimal("25000")
    ))

    # 5. 배송완료 주문 (환불/리뷰 테스트 2건째)
    opt5 = all_new_options[2] if len(all_new_options) > 2 else new_product_option
    order5 = Order(
        user_id=user.id,
        order_number="ORD-eval_dataset-0005",
        shipping_address_id=address.id,
        subtotal=Decimal("39000"),
        shipping_fee=Decimal("0"),
        total_amount=Decimal("39000"),
        status=OrderStatus.DELIVERED,
        payment_method="CARD",
        shipping_request="문 앞에 놔주세요"
    )
    db.add(order5)
    db.flush()
    db.add(OrderItem(
        order_id=order5.id,
        product_option_type=ProductType.NEW,
        product_option_id=opt5.id,
        quantity=1,
        unit_price=Decimal("39000"),
        subtotal=Decimal("39000")
    ))

    # 6. 배송완료 주문 (교환/리뷰 테스트 3건째)
    opt6 = all_new_options[3] if len(all_new_options) > 3 else new_product_option
    order6 = Order(
        user_id=user.id,
        order_number="ORD-eval_dataset-0006",
        shipping_address_id=address.id,
        subtotal=Decimal("52000"),
        shipping_fee=Decimal("3000"),
        total_amount=Decimal("55000"),
        status=OrderStatus.DELIVERED,
        payment_method="계좌이체",
        shipping_request="택배함에 넣어주세요"
    )
    db.add(order6)
    db.flush()
    db.add(OrderItem(
        order_id=order6.id,
        product_option_type=ProductType.NEW,
        product_option_id=opt6.id,
        quantity=2,
        unit_price=Decimal("26000"),
        subtotal=Decimal("52000")
    ))

    db.flush()
    logger.info("✅ 평가용 추가 주문 3건 생성 완료")


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
