"""
Base Tool 클래스.
Mock/Real API 전환이 간편하도록 설계.
"""

from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import random
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
    