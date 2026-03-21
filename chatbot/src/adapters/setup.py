import os
from .base import AdapterRegistry
from .site_a.client import SiteAClient
from .site_a.adapter import SiteAAdapter
from .site_b.client import SiteBClient
from .site_b.adapter import SiteBAdapter
from .site_c.client import SiteCClient
from .site_c.adapter import SiteCAdapter


def resolve_ecommerce_backend_url() -> str:
    explicit_url = (os.environ.get("BACKEND_API_URL") or "").strip()
    if explicit_url:
        return explicit_url.rstrip("/")

    if os.path.exists("/.dockerenv"):
        return "http://ecommerce-backend:8000"

    return "http://localhost:8000"


def setup_adapters() -> None:
    # 이미 등록되어 있다면 스킵
    if getattr(setup_adapters, "_initialized", False):
        return

    # 환경변수에서 URL 가져오기 (fallback 포함)
    food_url = os.environ.get("FOOD_API_URL", "http://food-backend:8002")
    bilyeo_url = os.environ.get("BILYEO_API_URL", "http://bilyeo-backend:5000")
    ecommerce_url = resolve_ecommerce_backend_url()

    # site-c는 현재 정식 지원 대상이며, 기존 site-a/site-b 어댑터는 등록만 유지합니다.
    food_client = SiteAClient(base_url=food_url)
    food_adapter = SiteAAdapter(client=food_client)

    bilyeo_client = SiteBClient(base_url=bilyeo_url)
    bilyeo_adapter = SiteBAdapter(client=bilyeo_client)

    ecommerce_client = SiteCClient(base_url=ecommerce_url)
    ecommerce_adapter = SiteCAdapter(client=ecommerce_client)

    # 레지스트리 등록
    AdapterRegistry.register_many([
        food_adapter,
        bilyeo_adapter,
        ecommerce_adapter
    ])

    setup_adapters._initialized = True

def resolve_site_adapter(site_id: str):
    setup_adapters()
    effective_site_id = (site_id or "site-c").strip() or "site-c"
    return AdapterRegistry.get(effective_site_id)


def resolve_order_tool_registry(site_id: str | None) -> dict[str, object]:
    effective_site_id = (site_id or "site-c").strip() or "site-c"

    from chatbot.src.tools import adapter_order_tools, order_tools

    def list_orders(**kwargs):
        return adapter_order_tools.get_user_orders_for_site(
            user_id=kwargs.get("user_id", 1),
            site_id=effective_site_id,
            access_token=kwargs.get("access_token"),
            limit=kwargs.get("limit", 5),
            days=kwargs.get("days", 30),
            requires_selection=kwargs.get("requires_selection", False),
            action_context=kwargs.get("action_context"),
        )

    registry: dict[str, object] = {
        "list_orders": list_orders,
        "cancel": adapter_order_tools.cancel_order_via_adapter,
        "refund": adapter_order_tools.register_return_via_adapter,
        "exchange": adapter_order_tools.register_exchange_via_adapter,
        "shipping": adapter_order_tools.get_shipping_via_adapter,
        "get_order_status": adapter_order_tools.get_order_status_via_adapter,
    }

    if effective_site_id == "site-c":
        registry["change_option"] = order_tools.change_product_option

    return registry


# 전역 함수로 바로 호출 가능하도록 초기화 지원
def get_adapter(site_id: str):
    return resolve_site_adapter(site_id)
