from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load_shared_assets_module():
    spec = importlib.util.find_spec("chatbot.src.onboarding.shared_chatbot_assets")
    assert spec is not None, "shared_chatbot_assets module must exist"
    return importlib.import_module("chatbot.src.onboarding.shared_chatbot_assets")


def _load_runtime_module():
    spec = importlib.util.find_spec("chatbot.src.onboarding.shared_widget_runtime")
    assert spec is not None, "shared_widget_runtime module must exist"
    return importlib.import_module("chatbot.src.onboarding.shared_widget_runtime")


def _extract_ts_default_contract(ts_content: str) -> dict[str, str]:
    start_marker = "export const DEFAULT_SHARED_WIDGET_HOST_CONTRACT: SharedWidgetHostContract = {"
    start = ts_content.index(start_marker) + len(start_marker)
    end = ts_content.index("};", start)
    contract_block = ts_content[start:end]

    contract: dict[str, str] = {}
    for raw_line in contract_block.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        name, value = line.split(": ", 1)
        contract[name] = value
    return contract


def test_shared_widget_host_contract_defaults_align_with_typescript():
    assets_module = _load_shared_assets_module()
    ts_source = Path(__file__).resolve().parents[1] / "frontend" / "shared_widget" / "index.ts"
    ts_content = ts_source.read_text(encoding="utf-8")
    ts_contract = _extract_ts_default_contract(ts_content)

    contract = assets_module.build_shared_widget_host_contract()

    assert set(contract) == {
        "chatbotServerBaseUrl",
        "authBootstrapPath",
        "widgetBundlePath",
        "widgetElementTag",
        "mountMode",
    }
    assert contract["chatbotServerBaseUrl"] == ""
    assert contract["authBootstrapPath"] == "/api/chat/auth-token"
    assert contract["widgetBundlePath"] == "/widget.js"
    assert contract["widgetElementTag"] == "order-cs-widget"
    assert contract["mountMode"] == "floating_launcher"
    assert ts_contract == {
        "chatbotServerBaseUrl": "''",
        "authBootstrapPath": "'/api/chat/auth-token'",
        "widgetBundlePath": "'/widget.js'",
        "widgetElementTag": "'order-cs-widget'",
        "mountMode": "'floating_launcher'",
    }
    assert "type SharedWidgetMountMode = 'floating_launcher';" in ts_content


def test_shared_widget_host_contract_rejects_explicit_empty_chatbot_server_base_url():
    assets_module = _load_shared_assets_module()

    with pytest.raises(ValueError, match="chatbot_server_base_url"):
        assets_module.build_shared_widget_host_contract(chatbot_server_base_url="")


def test_shared_widget_host_contract_overrides_take_precedence():
    assets_module = _load_shared_assets_module()

    contract = assets_module.build_shared_widget_host_contract(
        chatbot_server_base_url="https://chat.example.com/",
        auth_bootstrap_path="/custom/auth-token",
        widget_bundle_path="/custom/widget.js",
        widget_element_tag="custom-widget",
        mount_mode="embedded",
    )

    assert contract["chatbotServerBaseUrl"] == "https://chat.example.com"
    assert contract["authBootstrapPath"] == "/custom/auth-token"
    assert contract["widgetBundlePath"] == "/custom/widget.js"
    assert contract["widgetElementTag"] == "custom-widget"
    assert contract["mountMode"] == "floating_launcher"


def test_shared_widget_host_contract_attribute_overrides_take_precedence():
    assets_module = _load_shared_assets_module()

    resolved = assets_module.resolve_shared_widget_host_contract(
        base_contract=assets_module.build_shared_widget_host_contract(
            chatbot_server_base_url="https://base.example.com/",
            auth_bootstrap_path="/base/auth-token",
            widget_bundle_path="/base/widget.js",
            widget_element_tag="base-widget",
            mount_mode="floating_launcher",
        ),
        attribute_overrides={
            "chatbot-server-base-url": "https://attr.example.com/",
            "auth-bootstrap-path": "/attr/auth-token",
            "widget-bundle-path": "/attr/widget.js",
            "widget-element-tag": "attr-widget",
            "mount-mode": "embedded",
        },
    )

    assert resolved["chatbotServerBaseUrl"] == "https://attr.example.com"
    assert resolved["authBootstrapPath"] == "/attr/auth-token"
    assert resolved["widgetBundlePath"] == "/attr/widget.js"
    assert resolved["widgetElementTag"] == "attr-widget"
    assert resolved["mountMode"] == "floating_launcher"


def test_shared_widget_host_contract_rejects_explicit_empty_override_values():
    assets_module = _load_shared_assets_module()

    with pytest.raises(ValueError, match="chatbot_server_base_url"):
        assets_module.resolve_shared_widget_host_contract(
            base_contract={"chatbotServerBaseUrl": ""},
        )

    with pytest.raises(ValueError, match="chatbot_server_base_url"):
        assets_module.resolve_shared_widget_host_contract(
            attribute_overrides={"chatbot-server-base-url": ""},
        )


def test_shared_widget_runtime_exposes_site_without_site_id():
    module = _load_runtime_module()

    payload = module.build_widget_runtime_payload(
        site="food",
        chatbot_server_base_url="https://chat.example.com/",
        capability_profile="order_cs_plus_retrieval",
        enabled_retrieval_corpora=["faq"],
        widget_features={"image_upload": False},
    )

    assert payload["site"] == "food"
    assert payload["chatbotServerBaseUrl"] == "https://chat.example.com"
    assert payload["authBootstrapPath"] == "/api/chat/auth-token"
    assert payload["widgetBundlePath"] == "/widget.js"
    assert payload["widgetElementTag"] == "order-cs-widget"
    assert payload["mountMode"] == "floating_launcher"
    assert payload["capabilityProfile"] == "order_cs_plus_retrieval"
    assert payload["enabledRetrievalCorpora"] == ["faq"]
    assert payload["widgetFeatures"] == {"image_upload": False}
    assert "site_id" not in payload
