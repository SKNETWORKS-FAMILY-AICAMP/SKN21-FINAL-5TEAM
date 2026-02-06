import random
from datetime import datetime, timedelta

def get_order_details(order_id: str):
    """
    가상의 주문 정보를 반환합니다.
    """
    # 실제 환경에서는 DB 조회를 수행합니다.
    mock_orders = {
        "ORD-123": {
            "status": "배송완료",
            "date": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
            "items": ["청바지", "흰 티셔츠"],
            "amount": 85000,
            "can_refund": True
        },
        "ORD-456": {
            "status": "배송중",
            "date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
            "items": ["검정 슬랙스"],
            "amount": 49000,
            "can_refund": False # 배송 중에는 환불 불가
        }
    }
    return mock_orders.get(order_id)

def request_refund(order_id: str, reason: str):
    """
    가상의 환불 API 호출 함수입니다.
    """
    order = get_order_details(order_id)
    if not order:
        return {"status": "error", "message": "주문 번호를 찾을 수 없습니다."}
    
    if not order["can_refund"]:
        return {"status": "error", "message": f"현재 '{order['status']}' 상태이므로 환불이 불가능합니다."}
    
    # 환불 로직 수행 (가상)
    return {
        "status": "success",
        "order_id": order_id,
        "refund_amount": order["amount"],
        "transaction_id": f"REF-{random.randint(10000, 99999)}"
    }

def get_tracking_info(order_id: str):
    """
    가상의 배송 조회 API입니다.
    """
    order = get_order_details(order_id)
    if not order:
        return {"status": "error", "message": "주문 번호를 찾을 수 없습니다."}
    
    status_msg = {
        "배송완료": "고객님께 배송이 완료되었습니다. (도착시간: 2월 5일 14:30)",
        "배송중": "현재 '서울 관악구' 영업소에서 배달 출발했습니다. (예상 도착: 오늘 저녁)",
    }
    
    return {
        "status": "success",
        "current_location": "관악구",
        "message": status_msg.get(order["status"], "위치 정보를 가져올 수 없습니다.")
    }
