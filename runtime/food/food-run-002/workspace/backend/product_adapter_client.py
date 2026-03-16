import httpx


PRODUCT_API_BASE = "/api/products/"


class GeneratedProductAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_products(self, headers: dict | None = None, params: dict | None = None) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}{PRODUCT_API_BASE}",
                headers=headers or {},
                params=params or {},
            )
            response.raise_for_status()
            return response.json()

    async def get_product(self, product_id: int, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}{PRODUCT_API_BASE}{product_id}/",
                headers=headers or {},
            )
            response.raise_for_status()
            return response.json()
