import os
from .base import AdapterRegistry
from .site_a.client import SiteAClient
from .site_a.adapter import SiteAAdapter
from .site_b.client import SiteBClient
from .site_b.adapter import SiteBAdapter
from .site_c.client import SiteCClient
from .site_c.adapter import SiteCAdapter

def setup_adapters() -> None:
    # 이미 등록되어 있다면 스킵
    if getattr(setup_adapters, "_initialized", False):
        return
        
    # 환경변수에서 URL 가져오기 (fallback 포함)
    food_url = os.environ.get("FOOD_API_URL", "http://food-backend:8002")
    bilyeo_url = os.environ.get("BILYEO_API_URL", "http://bilyeo-backend:5000")
    ecommerce_url = os.environ.get("BACKEND_API_URL", "http://ecommerce-backend:8000")

    # 클라이언트 및 어댑터 초기화 (site-id 매핑 주의)
    # site-a: Food (SaaS/src/adapters/site-a 는 siteId: site-b 사용중)
    # site-b: Bilyeo (SaaS/src/adapters/site-b 는 siteId: site-c 사용중)
    # site-c: Ecommerce (SaaS/src/adapters/site-c 는 siteId: site-a 사용중)
    
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
