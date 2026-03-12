from typing import Dict, Any, Optional
import httpx
from ..schema import ProductSearchFilter, GetOrderStatusInput, GetDeliveryTrackingInput, SubmitOrderActionInput, AdapterError

class SiteBClient:
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
                raise AdapterError("SITE_B_UPSTREAM_ERROR", f"요청 실패: {exc}", {"url": url}) from exc

    async def validate_session(self, headers: Dict[str, str]) -> Any:
        return await self._request("GET", "/api/orders", headers=headers)

    async def search_products(self, filter_input: ProductSearchFilter, headers: Dict[str, str]) -> Any:
        params = {}
        if filter_input.query:
            params["search"] = filter_input.query
        if filter_input.categoryIds:
            params["category"] = filter_input.categoryIds[0]
            
        return await self._request("GET", "/api/products", headers=headers, params=params)

    async def get_order(self, input_data: GetOrderStatusInput, headers: Dict[str, str]) -> Any:
        # site-b returns orders list in bilyeo
        return await self._request("GET", "/api/orders", headers=headers)

    async def get_delivery(self, input_data: GetDeliveryTrackingInput, headers: Dict[str, str]) -> Any:
        return await self.get_order(GetOrderStatusInput(orderId=input_data.orderId), headers)

    async def submit_order_action(self, input_data: SubmitOrderActionInput, headers: Dict[str, str]) -> Any:
        raise AdapterError("NOT_SUPPORTED", "submit order action endpoint is not provided by bilyeo")
