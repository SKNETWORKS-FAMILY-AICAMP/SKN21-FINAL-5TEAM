"""
Tool 사용 예시.
각 Tool을 테스트해보는 스크립트.
"""

from ecommerce.chatbot.src.tools.order_tools import (
    get_delivery_status,
    get_courier_contact,
    update_payment_info
)
from ecommerce.chatbot.src.tools.service_tools import (
    register_gift_card,
    get_reviews,
    create_review
)


def test_delivery_tools():
    """배송 관련 Tool 테스트"""
    print("=== 배송 현황 조회 ===")
    result = get_delivery_status.invoke({"order_id": "ORD123"})
    print(result)
    
    print("\n=== 배송업체 연락처 ===")
    result = get_courier_contact.invoke({"order_id": "ORD123"})
    print(result)


def test_payment_tools():
    """결제 관련 Tool 테스트"""
    print("=== 결제정보 변경 ===")
    result = update_payment_info.invoke({
        "order_id": "ORD123",
        "payment_method": "카드",
        "card_number": "1234-5678-9012-3456"
    })
    print(result)


def test_service_tools():
    """서비스 관련 Tool 테스트"""
    print("=== 상품권 등록 ===")
    result = register_gift_card.invoke({"code": "GIFT-1234-5678"})
    print(result)
    
    print("\n=== 리뷰 조회 ===")
    result = get_reviews.invoke({"limit": 5})
    print(result)
    
    print("\n=== 리뷰 작성 ===")
    result = create_review.invoke({
        "product_id": "PROD123",
        "rating": 5,
        "content": "정말 좋아요!"
    })
    print(result)


if __name__ == "__main__":
    test_delivery_tools()
    print("\n" + "="*50 + "\n")
    test_payment_tools()
    print("\n" + "="*50 + "\n")
    test_service_tools()
