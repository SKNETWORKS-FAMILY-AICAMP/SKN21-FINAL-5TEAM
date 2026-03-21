from __future__ import annotations

import os
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

from chatbot.server_fastapi import app


def test_widget_bundle_route_is_served():
    client = TestClient(app)

    response = client.get("/widget.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.text
