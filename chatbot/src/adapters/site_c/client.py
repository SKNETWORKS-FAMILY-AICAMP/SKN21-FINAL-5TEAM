from typing import Dict, Any, Optional
import httpx
from ..schema import ProductSearchFilter, GetOrderStatusInput, GetDeliveryTrackingInput, SubmitOrderActionInput, AdapterError

class SiteCClient:
    def __init__(self, base_url: str, timeout_ms: int = 10000, default_headers: Optional[Dict[str, str]] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_ms / 1000.0
        self.default_headers = default_headers or {}

    async def _request(self, method: str, path: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> Any:
        req_headers = {
            "Content-Type": "application/json",
            **self.default_headers,
            **(headers or {})
        }
        url = f"{self.base_url}{path}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(method, url, headers=req_headers, params=params, json=json)
                response.raise_for_status()
                return response.json() if response.text else None
            except httpx.HTTPError as exc:
                raise AdapterError("SITE_C_UPSTREAM_ERROR", f"요청 실패: {exc}", {"url": url}) from exc

    async def validate_session(self, headers: Dict[str, str]) -> Any:
        return await self._request("GET", "/users/me", headers=headers)

    async def search_products(self, filter_input: ProductSearchFilter, headers: Dict[str, str]) -> Any:
        params = {}
        if filter_input.query:
            params["keyword"] = filter_input.query
        if filter_input.minPrice is not None:
            params["min_price"] = filter_input.minPrice
        if filter_input.maxPrice is not None:
            params["max_price"] = filter_input.maxPrice
        if filter_input.limit is not None:
            params["limit"] = filter_input.limit
            
        return await self._request("GET", "/products/new", headers=headers, params=params)

    async def get_order(self, user_id: str, input_data: GetOrderStatusInput, headers: Dict[str, str]) -> Any:
        return await self._request("GET", f"/orders/{user_id}/orders/{input_data.orderId}", headers=headers)

    async def get_order_by_number(self, order_number: str, headers: Dict[str, str]) -> Any:
        return await self._request("GET", f"/orders/orders/number/{order_number}", headers=headers)

    async def list_orders(self, user_id: str, headers: Dict[str, str], limit: int = 20) -> Any:
        params = {"limit": limit}
        return await self._request("GET", f"/orders/{user_id}/orders", headers=headers, params=params)

    async def get_delivery(self, input_data: GetDeliveryTrackingInput, headers: Dict[str, str]) -> Any:
        return await self._request("GET", f"/shipping/order/{input_data.orderId}", headers=headers)

    async def submit_cancel(self, user_id: str, input_data: SubmitOrderActionInput, headers: Dict[str, str]) -> Any:
        params = {}
        if input_data.reasonText:
            params["reason"] = input_data.reasonText
        return await self._request("POST", f"/orders/{user_id}/orders/{input_data.orderId}/cancel", headers=headers, params=params)

    async def submit_refund(self, user_id: str, input_data: SubmitOrderActionInput, headers: Dict[str, str]) -> Any:
        reason = input_data.reasonText or input_data.reasonCode.value or "환불 요청"
        params = {"reason": reason}
        return await self._request("POST", f"/orders/{user_id}/orders/{input_data.orderId}/refund", headers=headers, params=params)
