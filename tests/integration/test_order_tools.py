import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# 대상 함수들을 임포트 (chatbot-api 폴더 내)
from chatbot.src.tools.order_tools import (
    cancel_order, 
    _get_order_with_auth,
    _check_return_period
)
from ecommerce.backend.app.models import Order, User, ProductOption, OrderItem, Product, Category
from ecommerce.backend.app.router.shipping.models import ShippingAddress
from ecommerce.backend.app.router.orders.schemas import OrderStatus, ProductType

def test_check_return_period():
    """순수 비즈니스 로직 테스트: 배송 후 7일 경과 확인"""
    now = datetime.now()
    # 3일 전 -> 성공해야 함
    is_valid, err = _check_return_period(now - timedelta(days=3))
    assert is_valid is True
    assert err is None
    
    # 8일 전 -> 실패해야 함
    is_valid, err = _check_return_period(now - timedelta(days=8))
    assert is_valid is False
    assert "7일이 경과" in err

def test_get_order_with_auth(db_session):
    """실제 Test DB를 이용한 통합 테스트: 권한 및 조회 테스트"""
    # 1. 가짜 데이터 삽입 (Seeding)
    user = User(id=1, email="test@test.com", password_hash="123", name="testuser", created_at=datetime.now())
    db_session.add(user)
    db_session.commit()
    
    address = ShippingAddress(id=1, user_id=1, recipient_name="Tester", phone="010-1234-5678", address1="Seoul", address2="123", post_code="12345", is_default=True)
    db_session.add(address)
    db_session.commit()
    
    order = Order(
        id=100, 
        order_number="ORD-TEST-001",
        user_id=1,
        shipping_address_id=1,
        subtotal=10000,
        shipping_fee=0,
        total_amount=10000,
        status=OrderStatus.PAID,
        payment_method="CARD"
    )
    db_session.add(order)
    db_session.commit()
    
    # 2. 조회 결과 확인 (본인 주문)
    res_order, err = _get_order_with_auth(db_session, "ORD-TEST-001", user_id=1)
    assert err is None
    assert res_order is not None
    assert res_order.total_amount == 10000

    # 3. 권한 실패 확인 (비본인 주문)
    res_order, err = _get_order_with_auth(db_session, "ORD-TEST-001", user_id=2)
    assert res_order is None
    assert "PERMISSION_DENIED" in err["error"]

# cancel_order 테스트 시 SessionLocal을 가로채서(test_session 반환) 검증할 수 있습니다.
@patch("chatbot.src.tools.order_tools.SessionLocal")
@patch("chatbot.src.tools.order_tools.interrupt") # 챗봇 인터럽트 모킹
def test_cancel_order_success(mock_interrupt, mock_session_local, db_session):
    """실제 DB 연동 취소 승인 흐름 테스트"""
    mock_session_local.return_value = db_session
    mock_interrupt.return_value = True # 사용자 취소 승인 (확인 누름)
    
    # 기초 데이터 준비
    user = User(id=2, email="cancel@test.com", password_hash="123", name="c_user", created_at=datetime.now())
    db_session.add(user)
    db_session.flush()

    address = ShippingAddress(id=2, user_id=2, recipient_name="Canceler", phone="010-1111-2222", address1="Busan", address2="123", post_code="12345", is_default=True)
    db_session.add(address)
    db_session.flush()

    order = Order(
        order_number="ORD-TEST-999",
        user_id=2,
        shipping_address_id=2,
        subtotal=50000,
        shipping_fee=0,
        total_amount=50000,
        status=OrderStatus.PREPARING,
        payment_method="CARD"
    )
    db_session.add(order)
    db_session.flush() # ID 받아옴
    
    # 카테고리 준비
    category = Category(id=1, name="Test Category")
    db_session.add(category)
    db_session.flush()

    # 상품 준비
    product = Product(id=1, category_id=1, name="Test Product", description="Test", price=25000)
    db_session.add(product)
    db_session.flush()

    # 상품 옵션 및 재고
    product_option = ProductOption(id=10, product_id=1, size_name="M", color="Red", quantity=5, is_active=True)
    db_session.add(product_option)
    db_session.flush()
    
    # 주문 상품
    order_item = OrderItem(
        order_id=order.id, 
        product_option_type=ProductType.NEW,
        product_option_id=product_option.id, 
        quantity=2, 
        unit_price=25000, 
        subtotal=50000
    )
    db_session.add(order_item)
    db_session.commit()

    # 실행
    result = cancel_order.invoke({
        "order_id": "ORD-TEST-999", 
        "user_id": 2, 
        "reason": "테스트",
        "confirmed": True # 사용자 승인 (Interrupt 생략 가능하지만 명시적 주입 지원여부 확인)
    })
    
    # 결과 검증
    assert result["success"] is True
    assert result["status"] == "cancelled"
    
    # DB 상태 검증 (주문 상태 취소됨)
    updated_order = db_session.query(Order).filter_by(order_number="ORD-TEST-999").first()
    assert updated_order.status == OrderStatus.CANCELLED
    
    # 재고 복구 검증 (원래 5개 + 주문 수량 2개 = 7개)
    updated_option = db_session.query(ProductOption).filter_by(id=10).first()
    assert updated_option.quantity == 7
