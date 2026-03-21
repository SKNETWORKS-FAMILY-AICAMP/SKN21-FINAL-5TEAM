from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load_runtime_module():
    spec = importlib.util.find_spec("chatbot.src.onboarding.shared_widget_runtime")
    assert spec is not None, "shared_widget_runtime module must exist"
    return importlib.import_module("chatbot.src.onboarding.shared_widget_runtime")


def test_shared_widget_runtime_exposes_host_bootstrap_contract():
    module = _load_runtime_module()

    payload = module.build_widget_runtime_payload(site="food")

    assert "chatbot_server_base_url" in payload
    assert payload["auth_bootstrap_path"] == "/api/chat/auth-token"
    assert payload["mount_mode"] == "floating_launcher"
    assert "site_id" not in payload
