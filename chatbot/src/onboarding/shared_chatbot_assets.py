from __future__ import annotations


DEFAULT_CHATBOT_SERVER_BASE_URL = ""
DEFAULT_WIDGET_BUNDLE_PATH = "/widget.js"
DEFAULT_WIDGET_ELEMENT_TAG = "order-cs-widget"
DEFAULT_AUTH_BOOTSTRAP_PATH = "/api/chat/auth-token"
DEFAULT_MOUNT_MODE = "floating_launcher"


def build_shared_widget_host_contract(
    *,
    chatbot_server_base_url: str = DEFAULT_CHATBOT_SERVER_BASE_URL,
    auth_bootstrap_path: str = DEFAULT_AUTH_BOOTSTRAP_PATH,
    widget_bundle_path: str = DEFAULT_WIDGET_BUNDLE_PATH,
    widget_element_tag: str = DEFAULT_WIDGET_ELEMENT_TAG,
    mount_mode: str = DEFAULT_MOUNT_MODE,
) -> dict[str, str]:
    return {
        "chatbot_server_base_url": chatbot_server_base_url.rstrip("/"),
        "auth_bootstrap_path": auth_bootstrap_path,
        "widget_bundle_path": widget_bundle_path,
        "widget_element_tag": widget_element_tag,
        "mount_mode": mount_mode,
    }
