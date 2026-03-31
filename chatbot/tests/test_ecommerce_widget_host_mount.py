from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHATBOT_FAB_WRAPPER = REPO_ROOT / "ecommerce" / "frontend" / "app" / "ChatbotFabWrapper.tsx"
TSCONFIG = REPO_ROOT / "ecommerce" / "frontend" / "tsconfig.json"
NEXT_CONFIG_SHARED = REPO_ROOT / "ecommerce" / "frontend" / "next.config.shared.js"
ORDER_CS_WIDGET_DECLARATION = REPO_ROOT / "ecommerce" / "frontend" / "app" / "order-cs-widget.d.ts"
SHIPPING_PAGE = REPO_ROOT / "ecommerce" / "frontend" / "app" / "shipping" / "page.tsx"


def test_ecommerce_frontend_bootstraps_shared_widget_bundle() -> None:
    content = CHATBOT_FAB_WRAPPER.read_text(encoding="utf-8")

    assert "@skn/shared-chatbot" not in content
    assert "useAuth" not in content
    assert "__ORDER_CS_WIDGET_HOST_CONTRACT__" in content
    assert "NEXT_PUBLIC_CHATBOT_API_URL" in content
    assert "/api/v1/chat/auth-token" in content
    assert 'script[data-order-cs-widget-bundle="true"]' in content
    assert "/widget.js" in content
    assert "<order-cs-widget" in content
    assert 'capabilities="full"' in content
    assert "siteId: 'site-c'" in content
    assert "capabilityProfile: 'full'" in content


def test_ecommerce_frontend_typescript_config_includes_node_types() -> None:
    assert TSCONFIG.exists(), "ecommerce frontend should define a tsconfig.json for editor type resolution"

    content = TSCONFIG.read_text(encoding="utf-8")

    assert '"types"' in content
    assert '"node"' in content
    assert '"next-env.d.ts"' in content


def test_ecommerce_frontend_next_config_shared_exists() -> None:
    assert NEXT_CONFIG_SHARED.exists(), "shared Next config should exist for next.config.js/ts imports"

    content = NEXT_CONFIG_SHARED.read_text(encoding="utf-8")

    assert "externalDir: true" in content
    assert "NEXT_PUBLIC_API_URL" in content
    assert "NEXT_PUBLIC_CHATBOT_API_URL" in content


def test_ecommerce_frontend_declares_custom_widget_and_daum_window_types() -> None:
    widget_types = ORDER_CS_WIDGET_DECLARATION.read_text(encoding="utf-8")
    shipping_page = SHIPPING_PAGE.read_text(encoding="utf-8")

    assert "order-cs-widget" in widget_types
    assert "interface Window" in shipping_page or "interface Window" in widget_types
    assert "daum" in shipping_page or "daum" in widget_types
