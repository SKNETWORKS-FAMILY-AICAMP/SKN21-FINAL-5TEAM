from __future__ import annotations


DEFAULT_CHATBOT_SERVER_BASE_URL = ""
DEFAULT_WIDGET_BUNDLE_PATH = "/widget.js"
DEFAULT_WIDGET_ELEMENT_TAG = "order-cs-widget"
DEFAULT_AUTH_BOOTSTRAP_PATH = "/api/chat/auth-token"
DEFAULT_MOUNT_MODE = "floating_launcher"
_CONTRACT_FIELD_MAP = {
    "chatbot-server-base-url": "chatbotServerBaseUrl",
    "auth-bootstrap-path": "authBootstrapPath",
    "widget-bundle-path": "widgetBundlePath",
    "widget-element-tag": "widgetElementTag",
    "mount-mode": "mountMode",
    "site-id": "siteId",
    "brand-display-name": "brandDisplayName",
    "brand-store-label": "brandStoreLabel",
    "assistant-title": "assistantTitle",
    "initial-greeting": "initialGreeting",
    "capability-profile": "capabilityProfile",
    "enabled-retrieval-corpora": "enabledRetrievalCorpora",
    "widget-features": "widgetFeatures",
}


def _normalize_mount_mode(value: str | None) -> str:
    return DEFAULT_MOUNT_MODE if str(value or "").strip() != DEFAULT_MOUNT_MODE else DEFAULT_MOUNT_MODE


def _normalize_chatbot_server_base_url(value: str | None, *, required: bool) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if required and not normalized:
        raise ValueError("chatbot_server_base_url must be non-empty")
    return normalized


def build_shared_widget_host_contract(
    *,
    chatbot_server_base_url: str | None = None,
    auth_bootstrap_path: str = DEFAULT_AUTH_BOOTSTRAP_PATH,
    widget_bundle_path: str = DEFAULT_WIDGET_BUNDLE_PATH,
    widget_element_tag: str = DEFAULT_WIDGET_ELEMENT_TAG,
    mount_mode: str = DEFAULT_MOUNT_MODE,
    site_id: str | None = None,
    brand_display_name: str | None = None,
    brand_store_label: str | None = None,
    assistant_title: str | None = None,
    initial_greeting: str | None = None,
    capability_profile: str | None = None,
    enabled_retrieval_corpora: list[str] | None = None,
    widget_features: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_base_url = _normalize_chatbot_server_base_url(
        chatbot_server_base_url,
        required=chatbot_server_base_url is not None,
    )
    contract: dict[str, object] = {
        "chatbotServerBaseUrl": normalized_base_url,
        "authBootstrapPath": auth_bootstrap_path,
        "widgetBundlePath": widget_bundle_path,
        "widgetElementTag": widget_element_tag,
        "mountMode": _normalize_mount_mode(mount_mode),
    }
    if str(site_id or "").strip():
        contract["siteId"] = str(site_id).strip()
    if str(brand_display_name or "").strip():
        contract["brandDisplayName"] = str(brand_display_name).strip()
    if str(brand_store_label or "").strip():
        contract["brandStoreLabel"] = str(brand_store_label).strip()
    if str(assistant_title or "").strip():
        contract["assistantTitle"] = str(assistant_title).strip()
    if str(initial_greeting or "").strip():
        contract["initialGreeting"] = str(initial_greeting).strip()
    if str(capability_profile or "").strip():
        contract["capabilityProfile"] = str(capability_profile).strip()
    normalized_corpora = [
        str(item).strip()
        for item in (enabled_retrieval_corpora or [])
        if str(item).strip()
    ]
    if normalized_corpora:
        contract["enabledRetrievalCorpora"] = normalized_corpora
    if widget_features:
        contract["widgetFeatures"] = dict(widget_features)
    return contract


def resolve_shared_widget_host_contract(
    *,
    base_contract: dict[str, object] | None = None,
    attribute_overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    resolved = build_shared_widget_host_contract()
    if base_contract:
        for key in resolved:
            if key not in base_contract:
                continue
            value = str(base_contract[key] or "")
            resolved[key] = (
                _normalize_chatbot_server_base_url(value, required=True)
                if key == "chatbotServerBaseUrl"
                else value
            )

    if attribute_overrides:
        for raw_key, raw_value in attribute_overrides.items():
            key = _CONTRACT_FIELD_MAP.get(str(raw_key).strip(), str(raw_key).strip())
            value = str(raw_value or "")
            if key == "chatbotServerBaseUrl":
                resolved[key] = _normalize_chatbot_server_base_url(value, required=True)
                continue
            if key in {
                "siteId",
                "brandDisplayName",
                "brandStoreLabel",
                "assistantTitle",
                "initialGreeting",
            }:
                if value.strip():
                    resolved[key] = value.strip()
                continue
            if key not in resolved:
                continue
            resolved[key] = value
        capability_profile = str(attribute_overrides.get("capability-profile") or "").strip()
        if capability_profile:
            resolved["capabilityProfile"] = capability_profile
        enabled_corpora = str(attribute_overrides.get("enabled-retrieval-corpora") or "").strip()
        if enabled_corpora:
            resolved["enabledRetrievalCorpora"] = [
                token.strip() for token in enabled_corpora.split(",") if token.strip()
            ]

    if base_contract:
        if isinstance(base_contract.get("enabledRetrievalCorpora"), list):
            resolved["enabledRetrievalCorpora"] = [
                str(item).strip()
                for item in list(base_contract.get("enabledRetrievalCorpora") or [])
                if str(item).strip()
            ]
        if isinstance(base_contract.get("widgetFeatures"), dict):
            resolved["widgetFeatures"] = dict(base_contract.get("widgetFeatures") or {})
        for key in ("siteId", "brandDisplayName", "brandStoreLabel", "assistantTitle", "initialGreeting"):
            if str(base_contract.get(key) or "").strip():
                resolved[key] = str(base_contract.get(key) or "").strip()
        if str(base_contract.get("capabilityProfile") or "").strip():
            resolved["capabilityProfile"] = str(base_contract.get("capabilityProfile") or "").strip()

    resolved["mountMode"] = _normalize_mount_mode(resolved.get("mountMode"))
    return resolved
