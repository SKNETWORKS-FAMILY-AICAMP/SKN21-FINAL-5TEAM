import pytest
from unittest.mock import patch
from ecommerce.backend.app.models import Category, User
from ecommerce.backend.app.router.products.models import UsedProductCondition, UsedProduct, UsedProductOption
from chatbot.src.tools.used_tools import open_used_sale_form, register_used_sale

@patch("chatbot.src.tools.used_tools.SessionLocal")
def test_open_used_sale_form(mock_session_local, db_session):
    """중고 판매 폼 호출 테스트 (DB 의존성 확인)"""
    mock_session_local.return_value = db_session
    
    # 기초 데이터 준비
    category = Category(id=1, name="Top", is_active=True)
    db_session.add(category)
    db_session.flush()

    condition = UsedProductCondition(id=1, condition_name="S급", description="새상품급", depreciation_percent=5)
    db_session.add(condition)
    db_session.commit()

    # 실행
    result = open_used_sale_form.invoke({})
    
    assert result["ui_action"] == "show_used_sale_form"
    assert len(result["ui_data"]["category_options"]) == 1
    assert result["ui_data"]["category_options"][0]["name"] == "Top"
    assert len(result["ui_data"]["condition_options"]) == 1
    assert result["ui_data"]["condition_options"][0]["name"] == "S급"


@patch("chatbot.src.tools.used_tools.SessionLocal")
@patch("chatbot.src.tools.used_tools._call_products_api")
def test_register_used_sale_fallback(mock_call_api, mock_session_local, db_session):
    """API 호출 실패 시 DB Fallback 로직 정상 작동 테스트"""
    mock_session_local.return_value = db_session
    # API 요청 강제 실패 유도
    mock_call_api.side_effect = Exception("API Connection Failed")
    
    user = User(id=1, email="seller@test.com", password_hash="123", name="Seller")
    db_session.add(user)
    db_session.flush()

    category = Category(id=2, name="Bottom", is_active=True)
    db_session.add(category)
    db_session.flush()

    condition = UsedProductCondition(id=2, condition_name="A급", description="좋음", depreciation_percent=10)
    db_session.add(condition)
    db_session.commit()

    # 실행
    result = register_used_sale.invoke({
        "category_id": 2,
        "item_name": "Test Item",
        "description": "Used bottom, good condition",
        "condition_id": 2,
        "expected_price": 5000,
        "user_id": 1
    })
    
    # 검증
    assert result["success"] is True
    assert result["used_product_id"] is not None
    assert "tracking_id" in result

    # DB 저장 확인
    saved_product = db_session.query(UsedProduct).filter_by(id=result["used_product_id"]).first()
    assert saved_product is not None
    assert saved_product.name == "Test Item"
    assert saved_product.price == 5000
    assert saved_product.condition_id == 2
    
    saved_option = db_session.query(UsedProductOption).filter_by(used_product_id=saved_product.id).first()
    assert saved_option is not None
    assert saved_option.quantity == 1
