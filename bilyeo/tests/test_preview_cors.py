from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "bilyeo" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app import _build_cors_kwargs


def test_build_cors_kwargs_enables_credentials_for_preview_origins(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    kwargs = _build_cors_kwargs()

    assert kwargs["supports_credentials"] is True
    assert "http://127.0.0.1:3000" in kwargs["origins"]
    assert "http://localhost:3000" in kwargs["origins"]


def test_build_cors_kwargs_respects_env_override(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://example.com, http://demo.local ")

    kwargs = _build_cors_kwargs()

    assert kwargs["origins"] == ["http://example.com", "http://demo.local"]


def test_app_shell_reads_widget_capability_contract_from_env():
    app_shell = (ROOT / "bilyeo" / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "VITE_CAPABILITY_PROFILE" in app_shell
    assert "VITE_ENABLED_RETRIEVAL_CORPORA" in app_shell
    assert "capabilityProfile: CAPABILITY_PROFILE" in app_shell
    assert "enabledRetrievalCorpora: ENABLED_RETRIEVAL_CORPORA" in app_shell


def test_app_shell_supports_disabling_widget_for_capture_mode():
    app_shell = (ROOT / "bilyeo" / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "VITE_ENABLE_ORDER_CS_WIDGET" in app_shell
    assert '<order-cs-widget v-if="widgetEnabled" />' in app_shell
    assert "if (!WIDGET_ENABLED)" in app_shell
    assert "widgetEnabled: WIDGET_ENABLED" in app_shell
