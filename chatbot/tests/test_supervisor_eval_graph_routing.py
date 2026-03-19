from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load_run_intent_eval_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "chatbot_eval"
        / "benchmarkV2"
        / "intent-bench"
        / "run_intent_eval.py"
    )
    spec = importlib.util.spec_from_file_location("intent_eval_graph_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_predict_nodes_uses_planner_and_supervisor_only(monkeypatch):
    module = _load_run_intent_eval_module()
    calls: list[str] = []

    def fake_graph_app(*args, **kwargs):
        raise AssertionError("graph_app should not be called for route-only supervisor evaluation")

    def fake_planner_node(state):
        calls.append("planner")
        assert state["llm_provider"] == "local"
        assert state["llm_model"] == "Qwen/Qwen3.5-2B"
        assert state["user_info"]["email"] == "intent-eval@example.com"
        return {"pending_tasks": ["ORDER_CS"]}

    def fake_supervisor_node(state):
        calls.append("supervisor")
        assert state["pending_tasks"] == ["ORDER_CS"]
        return {"current_active_task": "ORDER_CS", "pending_tasks": []}

    def fake_route_after_supervisor(state):
        calls.append("route")
        assert state["current_active_task"] == "ORDER_CS"
        return "order_entry"

    monkeypatch.setattr(module, "graph_app", fake_graph_app, raising=False)
    monkeypatch.setattr(module, "planner_node", fake_planner_node, raising=False)
    monkeypatch.setattr(module, "supervisor_node", fake_supervisor_node, raising=False)
    monkeypatch.setattr(module, "route_after_supervisor", fake_route_after_supervisor, raising=False)

    predicted_nodes = module.predict_nodes(
        "주문을 취소하고 싶어요",
        model="Qwen/Qwen3.5-2B",
        provider="local",
    )

    assert predicted_nodes == ["order_intent_router"]
    assert calls == ["planner", "supervisor", "route"]


def test_predict_nodes_returns_route_after_supervisor(monkeypatch):
    module = _load_run_intent_eval_module()

    monkeypatch.setattr(module, "planner_node", lambda state: {"pending_tasks": ["SEARCH_SIMILAR_TEXT"]}, raising=False)
    monkeypatch.setattr(
        module,
        "supervisor_node",
        lambda state: {"current_active_task": "SEARCH_SIMILAR_TEXT", "pending_tasks": []},
        raising=False,
    )
    monkeypatch.setattr(module, "route_after_supervisor", lambda state: "discovery_subagent", raising=False)

    predicted_nodes = module.predict_nodes(
        "이 스타일 비슷한 옷 찾아줘",
        model="gpt-4o-mini",
        provider="openai",
    )

    assert predicted_nodes == ["discovery_subagent"]


def test_predict_nodes_handles_final_generator_route(monkeypatch):
    module = _load_run_intent_eval_module()

    monkeypatch.setattr(module, "planner_node", lambda state: {"pending_tasks": ["GENERAL_CHAT"]}, raising=False)
    monkeypatch.setattr(
        module,
        "supervisor_node",
        lambda state: {"current_active_task": "GENERAL_CHAT", "pending_tasks": []},
        raising=False,
    )
    monkeypatch.setattr(module, "route_after_supervisor", lambda state: "final_generator", raising=False)

    predicted_nodes = module.predict_nodes(
        "오늘 날씨 어때?",
        model="gpt-4o-mini",
        provider="openai",
    )

    assert predicted_nodes == ["final_generator"]
