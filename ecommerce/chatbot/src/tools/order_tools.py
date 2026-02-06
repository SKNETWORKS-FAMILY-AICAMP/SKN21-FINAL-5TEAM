"""
배송 및 주문 관련 Tools.
"""

from langchain_core.tools import tool
from ecommerce.chatbot.src.tools.base import BaseAPITool


@tool
def get_order_details(order_id: str) -> dict:
    """
    주문 상세 정보를 조회합니다.
    
    Args:
        order_id: 주문번호
        
    Returns:
        주문 상태, 상품 목록, 금액, 환불 가능 여부 등
    """
    api = BaseAPITool(use_mock=True)
    return api._call_api(f"/orders/{order_id}/details")


@tool
def request_refund(order_id: str, reason: str) -> dict:
    """
    환불을 요청합니다.
    
    Args:
        order_id: 주문번호
        reason: 환불 사유
        
    Returns:
        환불 요청 결과 (성공 여부, 환불 금액 등)
    """
    api = BaseAPITool(use_mock=True)
    data = {"reason": reason}
    return api._call_api(f"/orders/{order_id}/refund", method="POST", data=data)


@tool
def get_delivery_status(order_id: str) -> dict:
    """
    주문 번호로 배송 현황을 조회합니다.
    
    Args:
        order_id: 주문번호
        
    Returns:
        배송 상태, 택배사, 송장번호, 현재 위치, 예상 도착일
    """
    api = BaseAPITool(use_mock=True)
    return api._call_api(f"/orders/{order_id}/delivery")


@tool
def get_courier_contact(order_id: str) -> dict:
    """
    주문의 배송업체 연락처를 조회합니다.
    
    Args:
        order_id: 주문번호
        
    Returns:
        택배사명, 전화번호, 웹사이트
    """
    api = BaseAPITool(use_mock=True)
    return api._call_api(f"/orders/{order_id}/courier/contact")


@tool
def update_payment_info(order_id: str, payment_method: str, card_number: str = None) -> dict:
    """
    주문의 결제 정보를 변경합니다.
    
    Args:
        order_id: 주문번호
        payment_method: 결제 수단 (카드/계좌이체/무통장입금)
        card_number: 카드번호 (카드 결제 시)
        
    Returns:
        성공 여부, 메시지, 새로운 결제 수단
    """
    api = BaseAPITool(use_mock=True)
    data = {
        "payment_method": payment_method,
        "card_number": card_number
    }
    return api._call_api(f"/orders/{order_id}/payment", method="PUT", data=data)