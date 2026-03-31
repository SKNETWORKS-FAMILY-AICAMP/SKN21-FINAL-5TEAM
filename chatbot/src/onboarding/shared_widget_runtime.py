from __future__ import annotations

from .shared_chatbot_assets import build_shared_widget_host_contract
from chatbot.src.graph.brand_profiles import resolve_brand_profile


def build_widget_runtime_payload(
    *,
    site: str,
    chatbot_server_base_url: str,
    capability_profile: str | None = None,
    enabled_retrieval_corpora: list[str] | None = None,
    widget_features: dict[str, object] | None = None,
) -> dict[str, object]:
    brand_profile = resolve_brand_profile(site)
    return {
        "site": site,
        **build_shared_widget_host_contract(
            chatbot_server_base_url=chatbot_server_base_url,
            site_id=site,
            brand_display_name=brand_profile.display_name,
            brand_store_label=brand_profile.store_label,
            assistant_title=brand_profile.assistant_title,
            initial_greeting=brand_profile.initial_greeting,
            capability_profile=capability_profile,
            enabled_retrieval_corpora=enabled_retrieval_corpora,
            widget_features=widget_features,
        ),
    }
