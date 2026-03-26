from __future__ import annotations

from .shared_chatbot_assets import build_shared_widget_host_contract


def build_widget_runtime_payload(
    *,
    site: str,
    chatbot_server_base_url: str,
    capability_profile: str | None = None,
    enabled_retrieval_corpora: list[str] | None = None,
    widget_features: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "site": site,
        **build_shared_widget_host_contract(
            chatbot_server_base_url=chatbot_server_base_url,
            capability_profile=capability_profile,
            enabled_retrieval_corpora=enabled_retrieval_corpora,
            widget_features=widget_features,
        ),
    }
