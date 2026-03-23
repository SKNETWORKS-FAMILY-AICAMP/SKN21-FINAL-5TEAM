import os
from .base import AdapterRegistry
from .site_a.client import SiteAClient
from .site_a.adapter import SiteAAdapter
from .site_b.client import SiteBClient
from .site_b.adapter import SiteBAdapter
from .site_c.client import SiteCClient
from .site_c.adapter import SiteCAdapter

DEFAULT_SITE_ID = "site-c"


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

# 전역 함수로 바로 호출 가능하도록 초기화 지원
def get_adapter(site_id: str):
    setup_adapters()
    return AdapterRegistry.get(site_id)


def resolve_site_adapter(site_id: str | None):
    normalized_site_id = (site_id or DEFAULT_SITE_ID).strip() or DEFAULT_SITE_ID
    return get_adapter(normalized_site_id)
