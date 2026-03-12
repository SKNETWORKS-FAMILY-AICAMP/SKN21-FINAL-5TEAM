import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

# 대상 함수
from chatbot.src.tools.service_tools import (
    get_reviews,
    create_review,
)
from ecommerce.backend.app.models import (
    Order, User, ProductOption, OrderItem, Product, Category, Review
)
from ecommerce.backend.app.router.orders.schemas import OrderStatus, ProductType
from ecommerce.backend.app.router.shipping.models import ShippingAddress

@patch("chatbot.src.tools.service_tools.SessionLocal")
def test_get_reviews_without_product(mock_session_local, db_session):
    """상품 필터 없이 전체 리뷰 조회 테스트"""
    mock_session_local.return_value = db_session
    
    # User
    user = User(id=10, email="rev@test.com", password_hash="123", name="Reviewer", created_at=datetime.now())
    db_session.add(user)
    db_session.flush()

    # Review (Order나 Item 구조 없이도 연결되지만, 보통 DB 제약조건 상 연결 필요)
    # 단순화를 위해 일단 Review만 넣음. 외래키 제약조건이 있다면 필요 객체 삽입.
    # Review 모델 확인 (가짜 OrderItem 필요할 수도 있음)
    
    # 카테고리/상품/옵션/주문
    category = Category(id=10, name="Cat")
    db_session.add(category)
    db_session.flush()

    product = Product(id=20, category_id=10, name="Review Product", description="Test", price=1000)
    db_session.add(product)
    db_session.flush()

    option = ProductOption(id=30, product_id=20, quantity=10, is_active=True)
    db_session.add(option)
    db_session.flush()
    
    addr = ShippingAddress(id=10, user_id=10, recipient_name="Tester", phone="010", address1="Seoul", post_code="12345", is_default=True)
    db_session.add(addr)
    db_session.flush()
    
    order = Order(
        order_number="REV-001", user_id=10, shipping_address_id=10, 
        subtotal=1000, shipping_fee=0, total_amount=1000, status=OrderStatus.DELIVERED, payment_method="CARD"
    )
    db_session.add(order)
    db_session.flush()

    order_item = OrderItem(order_id=order.id, product_option_type=ProductType.NEW, product_option_id=30, quantity=1, unit_price=1000, subtotal=1000)
    db_session.add(order_item)
    db_session.flush()

    review = Review(user_id=10, order_item_id=order_item.id, rating=5, content="Great!")
    db_session.add(review)
    db_session.commit()

    # 실행
    result = get_reviews.invoke({"product_id": "", "limit": 10})
    
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["rating"] == 5
    assert result[0]["content"] == "Great!"

@patch("chatbot.src.tools.service_tools.SessionLocal")
def test_create_review_success(mock_session_local, db_session):
    """리뷰 작성 흐름 테스트 (UI 인터셉트 및 실제 저장)"""
    mock_session_local.return_value = db_session
    
    # 위와 동일한 데이터 구조 구성
    user = User(id=20, email="write@test.com", password_hash="123", name="Writer", created_at=datetime.now())
    db_session.add(user)
    db_session.flush()
    
    category = Category(id=11, name="Cat")
    db_session.add(category)
    db_session.flush()

    product = Product(id=21, category_id=11, name="Write Product", description="Test", price=1000)
    db_session.add(product)
    db_session.flush()

    option = ProductOption(id=31, product_id=21, quantity=10, is_active=True)
    db_session.add(option)
    db_session.flush()
    
    addr = ShippingAddress(id=20, user_id=20, recipient_name="Tester", phone="010", address1="Seoul", post_code="12345", is_default=True)
    db_session.add(addr)
    db_session.flush()
    
    order = Order(
        order_number="REV-002", user_id=20, shipping_address_id=20, 
        subtotal=1000, shipping_fee=0, total_amount=1000, status=OrderStatus.DELIVERED, payment_method="CARD"
    )
    db_session.add(order)
    db_session.flush()

    order_item = OrderItem(order_id=order.id, product_option_type=ProductType.NEW, product_option_id=31, quantity=1, unit_price=1000, subtotal=1000)
    db_session.add(order_item)
    db_session.commit()

    # 1. UI 호출 (rating=0 인 경우)
    res_ui = create_review.invoke({"order_id": "REV-002", "rating": 0, "content": "", "user_id": 20})
    assert "show_review_form" in res_ui

    # 2. 실제 저장
    res_save = create_review.invoke({"order_id": "REV-002", "rating": 4, "content": "Good!", "user_id": 20})
    assert isinstance(res_save, dict)
    assert res_save["success"] is True

    # 검증
    saved_review = db_session.query(Review).filter_by(order_item_id=order_item.id).first()
    assert saved_review.rating == 4
    assert saved_review.content == "Good!"
