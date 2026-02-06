"""
Base Tool 클래스.
Mock/Real API 전환이 간편하도록 설계.
"""

from typing import Any, Dict, Optional
import httpx
from ecommerce.chatbot.src.core.config import settings


class BaseAPITool:
    """
    API 호출을 위한 Base Tool 클래스.
    
    Args:
        use_mock (bool): True면 Mock 데이터 반환, False면 실제 API 호출
    """
    
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        self.api_base_url = getattr(settings, "BACKEND_API_URL", "http://localhost:8000")
    
    def _call_api(
        self, 
        endpoint: str, 
        method: str = "GET", 
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        API 호출 또는 Mock 데이터 반환.
        
        Args:
            endpoint: API 엔드포인트 (예: /orders/123/delivery)
            method: HTTP 메서드
            data: 요청 바디 데이터
            
        Returns:
            API 응답 또는 Mock 데이터
        """
        if self.use_mock:
            return self._mock_response(endpoint, method, data)
        
        # 실제 API 호출
        url = f"{self.api_base_url}{endpoint}"
        response = httpx.request(method, url, json=data, **kwargs)
        response.raise_for_status()
        return response.json()
    
    def _mock_response(
        self, 
        endpoint: str, 
        method: str, 
        data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Mock 응답 데이터 반환.
        나중에 실제 API로 전환할 때 이 메서드는 삭제됨.
        """
        # 배송 현황 조회
        if "/delivery" in endpoint:
            return {
                "status": "배송중",
                "courier": "CJ대한통운",
                "tracking_number": "123456789",
                "current_location": "대전HUB",
                "estimated_arrival": "2026-02-07"
            }
        
        # 배송업체 연락처
        if "/courier/contact" in endpoint:
            return {
                "courier_name": "CJ대한통운",
                "phone": "1588-1255",
                "website": "https://www.cjlogistics.com"
            }
        
        # 결제정보 변경
        if "/payment" in endpoint and method == "PUT":
            return {
                "success": True,
                "message": "결제정보가 성공적으로 변경되었습니다.",
                "new_payment_method": data.get("payment_method") if data else "카드"
            }
        
        # 상품권 등록
        if "/gift-card" in endpoint and method == "POST":
            return {
                "success": True,
                "message": "상품권이 등록되었습니다.",
                "balance": 50000,
                "expiry_date": "2027-02-06"
            }
        
        # 리뷰 조회
        if "/reviews" in endpoint and method == "GET":
            return {
                "reviews": [
                    {
                        "id": 1,
                        "product_name": "나이키 에어포스",
                        "rating": 5,
                        "content": "정말 만족스러운 제품입니다!",
                        "created_at": "2026-02-01"
                    }
                ]
            }
        
        # 리뷰 작성
        if "/reviews" in endpoint and method == "POST":
            return {
                "success": True,
                "message": "리뷰가 작성되었습니다.",
                "review_id": 42
            }
        
        # 기본 응답
        return {"error": "Unknown endpoint", "endpoint": endpoint}
