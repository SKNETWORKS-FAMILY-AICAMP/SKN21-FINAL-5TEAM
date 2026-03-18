from typing import Dict, Any, Optional
import httpx
from ..schema import ProductSearchFilter, GetOrderStatusInput, GetDeliveryTrackingInput, SubmitOrderActionInput, AdapterError

class SiteAClient:
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
            except httpx.HTTPStatusError as exc:
                response = exc.response
                message = None
                try:
                    payload = response.json()
                    message = payload.get("detail") or payload.get("message")
                except Exception:
                    message = response.text or None

                code = {
                    400: "INVALID_INPUT",
                    401: "UNAUTHORIZED",
                    403: "FORBIDDEN",
                    404: "NOT_FOUND",
                }.get(response.status_code, "SITE_A_UPSTREAM_ERROR")
                raise AdapterError(
                    code,
                    message or f"요청 실패: {exc}",
                    {"url": url, "status_code": response.status_code},
                ) from exc
            except httpx.HTTPError as exc:
                raise AdapterError("SITE_A_UPSTREAM_ERROR", f"요청 실패: {exc}", {"url": url}) from exc

    async def validate_session(self, headers: Dict[str, str]) -> Any:
        return await self._request("GET", "/api/users/me/", headers=headers)

    async def search_products(self, filter_input: ProductSearchFilter, headers: Dict[str, str]) -> Any:
        params = {}
        if filter_input.query:
            params["search"] = filter_input.query
        if filter_input.categoryIds:
            params["category"] = filter_input.categoryIds[0]
            
        return await self._request("GET", "/api/products/", headers=headers, params=params)

    async def get_order(self, input_data: GetOrderStatusInput, headers: Dict[str, str]) -> Any:
        return await self._request("GET", f"/api/orders/{input_data.orderId}/", headers=headers)

    async def list_orders(self, headers: Dict[str, str]) -> Any:
        return await self._request("GET", "/api/orders/", headers=headers)

    async def get_delivery(self, input_data: GetDeliveryTrackingInput, headers: Dict[str, str]) -> Any:
        # site-a는 get_order와 동일한 엔드포인트 사용
        return await self.get_order(GetOrderStatusInput(orderId=input_data.orderId), headers)

    async def submit_order_action(self, input_data: SubmitOrderActionInput, headers: Dict[str, str]) -> Any:
        payload: Dict[str, Any] = {"action": input_data.actionType.value}
        if input_data.reasonText:
            payload["reason"] = input_data.reasonText

        return await self._request(
            "POST",
            f"/api/orders/{input_data.orderId}/actions/",
            headers=headers,
            json=payload,
        )
