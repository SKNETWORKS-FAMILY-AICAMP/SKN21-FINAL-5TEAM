"""
서비스 관련 Tools (상품권, 리뷰).
"""

from langchain_core.tools import tool
from ecommerce.chatbot.src.tools.base import BaseAPITool


@tool
def register_gift_card(code: str, user_id: str = None) -> dict:
    """
    상품권 코드를 등록합니다.
    
    Args:
        code: 상품권 코드
        user_id: 사용자 ID (선택)
        
    Returns:
        성공 여부, 메시지, 잔액, 유효기간
    """
    api = BaseAPITool(use_mock=True)
    data = {
        "code": code,
        "user_id": user_id
    }
    return api._call_api("/gift-card/register", method="POST", data=data)


@tool
def get_reviews(product_id: str = None, limit: int = 10) -> dict:
    """
    리뷰를 조회합니다.
    
    Args:
        product_id: 상품 ID (선택, 없으면 전체 조회)
        limit: 조회할 리뷰 개수
        
    Returns:
        리뷰 목록
    """
    api = BaseAPITool(use_mock=True)
    endpoint = f"/reviews?limit={limit}"
    if product_id:
        endpoint += f"&product_id={product_id}"
    return api._call_api(endpoint)


@tool
def create_review(
    product_id: str, 
    rating: int, 
    content: str,
    order_id: str = None
) -> dict:
    """
    리뷰를 작성합니다.
    
    Args:
        product_id: 상품 ID
        rating: 평점 (1-5)
        content: 리뷰 내용
        order_id: 주문번호 (선택)
        
    Returns:
        성공 여부, 메시지, 리뷰 ID
    """
    api = BaseAPITool(use_mock=True)
    data = {
        "product_id": product_id,
        "rating": rating,
        "content": content,
        "order_id": order_id
    }
    return api._call_api("/reviews", method="POST", data=data)
