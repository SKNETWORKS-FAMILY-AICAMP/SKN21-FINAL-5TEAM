from __future__ import annotations

import os
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

fake_llm_module = ModuleType("chatbot.src.graph.llm_providers")
fake_llm_module.resolve_llm_runtime_policy = lambda provider=None, model=None: SimpleNamespace(  # type: ignore[attr-defined]
    provider=provider or "openai",
    model=model or "gpt-5-mini",
)
sys.modules["chatbot.src.graph.llm_providers"] = fake_llm_module

fake_workflow_module = ModuleType("chatbot.src.graph.workflow")
fake_workflow_module.graph_app = SimpleNamespace()
sys.modules["chatbot.src.graph.workflow"] = fake_workflow_module

fake_redis_runtime_module = ModuleType("chatbot.src.onboarding.redis_runtime")
fake_redis_runtime_module.build_onboarding_event_store = lambda redis_url=None: None  # type: ignore[attr-defined]
fake_redis_runtime_module.close_onboarding_event_store = lambda store=None: None  # type: ignore[attr-defined]
sys.modules["chatbot.src.onboarding.redis_runtime"] = fake_redis_runtime_module

fake_guardrail_module = ModuleType("chatbot.src.graph.nodes.guardrail")
fake_guardrail_module.load_guardrail_model = lambda: None  # type: ignore[attr-defined]
sys.modules["chatbot.src.graph.nodes.guardrail"] = fake_guardrail_module

from chatbot.src.api.v1.endpoints import chat as chat_endpoint
from chatbot.server_fastapi import app


def test_widget_bundle_route_serves_built_artifact(tmp_path, monkeypatch):
    bundle_path = tmp_path / "widget.js"
    bundle_path.write_text("console.log('widget bundle');\n", encoding="utf-8")
    monkeypatch.setattr(chat_endpoint, "WIDGET_BUNDLE_PATH", bundle_path)

    client = TestClient(app)

    response = client.get("/widget.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "content-disposition" not in response.headers
    assert response.text == "console.log('widget bundle');\n"


def test_widget_bundle_route_returns_404_when_artifact_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_endpoint, "WIDGET_BUNDLE_PATH", tmp_path / "missing-widget.js")

    client = TestClient(app)

    response = client.get("/widget.js")

    assert response.status_code == 404
    assert response.json() == {"detail": "Shared widget bundle unavailable"}


def test_widget_bundle_path_points_to_built_dist_artifact():
    assert chat_endpoint.WIDGET_BUNDLE_PATH.name == "widget.js"
    assert chat_endpoint.WIDGET_BUNDLE_PATH.parent.name == "dist"


def test_shared_widget_build_inlines_browser_safe_chatbot_api_env() -> None:
    shared_widget_dir = Path(__file__).resolve().parents[2] / "frontend" / "shared_widget"

    subprocess.run(["node", "build.mjs"], cwd=shared_widget_dir, check=True)

    bundle_source = (shared_widget_dir / "dist" / "widget.js").read_text(encoding="utf-8")
    assert "process.env.NEXT_PUBLIC_CHATBOT_API_URL" not in bundle_source
