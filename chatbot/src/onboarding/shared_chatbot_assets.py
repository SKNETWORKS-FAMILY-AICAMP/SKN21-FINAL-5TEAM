from __future__ import annotations

from dataclasses import dataclass


_DEFAULT_AUTH_BOOTSTRAP_PATH = "/api/chat/auth-token"
_DEFAULT_CHAT_PATH = "/api/chat"
_DEFAULT_STREAM_PATH = "/api/v1/chat/stream"
_DEFAULT_CHATBOT_API_BASE = "http://localhost:8100"
_DEFAULT_FRONTEND_ENV_KEYS = (
    "REACT_APP_CHATBOT_API_BASE",
    "NEXT_PUBLIC_CHATBOT_API_BASE",
)
_SITE_ID_BY_NAME = {
    "food": "site-a",
    "bilyeo": "site-b",
    "ecommerce": "site-c",
}


@dataclass(frozen=True)
class SharedChatbotAssetConfig:
    site_name: str
    site_id: str
    auth_bootstrap_path: str = _DEFAULT_AUTH_BOOTSTRAP_PATH
    chat_path: str = _DEFAULT_CHAT_PATH
    stream_path: str = _DEFAULT_STREAM_PATH
    chatbot_api_base_default: str = _DEFAULT_CHATBOT_API_BASE
    frontend_env_keys: tuple[str, ...] = _DEFAULT_FRONTEND_ENV_KEYS
    source_label: str = "shared_widget_runtime"


def resolve_shared_chatbot_assets(site_name: str | None) -> SharedChatbotAssetConfig:
    normalized_site_name = str(site_name or "").strip().lower()
    site_id = _SITE_ID_BY_NAME.get(normalized_site_name, "site-unknown")
    return SharedChatbotAssetConfig(
        site_name=normalized_site_name,
        site_id=site_id,
    )
