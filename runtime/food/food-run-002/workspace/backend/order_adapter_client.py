import httpx


ORDER_API_BASE = "/api/orders/"


class GeneratedOrderAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_orders(self, headers: dict | None = None) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}{ORDER_API_BASE}", headers=headers or {})
            response.raise_for_status()
            return response.json()

    async def get_order(self, order_id: int, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}{ORDER_API_BASE}{order_id}/",
                headers=headers or {},
            )
            response.raise_for_status()
            return response.json()

    async def submit_order_action(
        self,
        order_id: int,
        action: str,
        headers: dict | None = None,
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}{ORDER_API_BASE}{order_id}/actions/",
                headers=headers or {},
                json={"action": action},
            )
            response.raise_for_status()
            return response.json()
