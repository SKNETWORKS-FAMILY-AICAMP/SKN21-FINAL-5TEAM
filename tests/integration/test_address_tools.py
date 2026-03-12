import pytest
from unittest.mock import patch
from datetime import datetime

from chatbot.src.tools.address_tools import open_address_search, save_shipping_address_from_ui
from ecommerce.backend.app.models import User, ShippingAddress

def test_open_address_search():
    """주소 검색 폼 UI 액션 정상 반환 테스트"""
    result = open_address_search.invoke({})
    assert result["ui_action"] == "show_address_search"


@patch("chatbot.src.tools.address_tools.SessionLocal")
def test_save_shipping_address_from_ui_success(mock_session_local, db_session):
    """주소 정보 정상 저장 테스트"""
    mock_session_local.return_value = db_session
    
    # 1. User 생성
    user = User(id=1, email="test@test.com", password_hash="123", name="TestUser", phone="010-1234-5678", created_at=datetime.now())
    db_session.add(user)
    db_session.flush()

    # 2. 실행
    result = save_shipping_address_from_ui.invoke({
        "user_id": 1,
        "road_address": "Seoul Gangnam",
        "post_code": "06000",
        "detail_address": "123-45",
        "is_default": True
    })

    # 3. 반환값 검증
    assert result["success"] is True
    assert "address_id" in result
    assert result["address"]["road_address"] == "Seoul Gangnam"
    
    # 4. DB 검증
    saved_addr = db_session.query(ShippingAddress).filter_by(id=result["address_id"]).first()
    assert saved_addr is not None
    assert saved_addr.address1 == "Seoul Gangnam"
    assert saved_addr.post_code == "06000"
    assert saved_addr.recipient_name == "TestUser" # fallback to user name
    assert saved_addr.phone == "010-1234-5678" # fallback to user phone
    assert saved_addr.is_default is True
