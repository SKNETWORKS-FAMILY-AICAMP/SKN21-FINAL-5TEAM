from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load_runtime_module():
    spec = importlib.util.find_spec("chatbot.src.onboarding.shared_widget_runtime")
    assert spec is not None, "shared_widget_runtime module must exist"
    return importlib.import_module("chatbot.src.onboarding.shared_widget_runtime")


def test_site_a_shared_widget_runtime_requires_non_empty_chatbot_server_base_url():
    module = _load_runtime_module()

    with pytest.raises(ValueError, match="chatbot_server_base_url"):
        module.build_widget_runtime_payload(site="food", chatbot_server_base_url="")


def test_site_a_shared_widget_runtime_uses_shared_host_contract():
    module = _load_runtime_module()

    payload = module.build_widget_runtime_payload(
        site="food",
        chatbot_server_base_url="http://127.0.0.1:8100/",
    )

    assert payload["site"] == "food"
    assert {
        "chatbotServerBaseUrl": payload["chatbotServerBaseUrl"],
        "authBootstrapPath": payload["authBootstrapPath"],
        "widgetBundlePath": payload["widgetBundlePath"],
        "widgetElementTag": payload["widgetElementTag"],
        "mountMode": payload["mountMode"],
    } == {
        "chatbotServerBaseUrl": "http://127.0.0.1:8100",
        "authBootstrapPath": "/api/chat/auth-token",
        "widgetBundlePath": "/widget.js",
        "widgetElementTag": "order-cs-widget",
        "mountMode": "floating_launcher",
    }
    assert "site_id" not in payload
