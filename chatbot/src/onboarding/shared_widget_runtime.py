from __future__ import annotations

from .shared_chatbot_assets import build_shared_widget_host_contract


def build_widget_runtime_payload(
    *,
    site: str,
    chatbot_server_base_url: str = "",
) -> dict[str, str]:
    return {
        "site": site,
        **build_shared_widget_host_contract(chatbot_server_base_url=chatbot_server_base_url),
    }
