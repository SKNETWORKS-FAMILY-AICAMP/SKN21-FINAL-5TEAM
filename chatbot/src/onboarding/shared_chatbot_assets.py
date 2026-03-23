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
}


def _normalize_mount_mode(value: str | None) -> str:
    return DEFAULT_MOUNT_MODE if str(value or "").strip() != DEFAULT_MOUNT_MODE else DEFAULT_MOUNT_MODE


def build_shared_widget_host_contract(
    *,
    chatbot_server_base_url: str = DEFAULT_CHATBOT_SERVER_BASE_URL,
    auth_bootstrap_path: str = DEFAULT_AUTH_BOOTSTRAP_PATH,
    widget_bundle_path: str = DEFAULT_WIDGET_BUNDLE_PATH,
    widget_element_tag: str = DEFAULT_WIDGET_ELEMENT_TAG,
    mount_mode: str = DEFAULT_MOUNT_MODE,
) -> dict[str, str]:
    return {
        "chatbotServerBaseUrl": chatbot_server_base_url.rstrip("/"),
        "authBootstrapPath": auth_bootstrap_path,
        "widgetBundlePath": widget_bundle_path,
        "widgetElementTag": widget_element_tag,
        "mountMode": _normalize_mount_mode(mount_mode),
    }


def resolve_shared_widget_host_contract(
    *,
    base_contract: dict[str, str] | None = None,
    attribute_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    resolved = build_shared_widget_host_contract()
    if base_contract:
        for key in resolved:
            if key not in base_contract:
                continue
            value = str(base_contract[key] or "")
            resolved[key] = value.rstrip("/") if key == "chatbotServerBaseUrl" else value

    if attribute_overrides:
        for raw_key, raw_value in attribute_overrides.items():
            key = _CONTRACT_FIELD_MAP.get(str(raw_key).strip(), str(raw_key).strip())
            if key not in resolved:
                continue
            value = str(raw_value or "")
            resolved[key] = value.rstrip("/") if key == "chatbotServerBaseUrl" else value

    resolved["mountMode"] = _normalize_mount_mode(resolved.get("mountMode"))
    return resolved
