from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.graph.nodes import (
    discovery_subagent,
    final_generator,
    form_action_subagent,
    order_subagent,
    planner,
    policy_rag_subagent,
)
from chatbot.src.graph.brand_profiles import resolve_brand_profile
from chatbot.src.schemas.planner import TaskIntent


def _base_state(*, site_id: str) -> dict:
    return {
        "messages": [HumanMessage(content="환불 규정 알려줘")],
        "pending_tasks": [],
        "completed_tasks": [],
        "current_active_task": None,
        "order_context": {},
        "search_context": {},
        "ui_action_required": None,
        "user_info": {"id": 1, "name": "테스터", "site_id": site_id, "access_token": "token"},
        "llm_provider": "openai",
        "llm_model": "test-model",
        "agent_results": {},
        "guardrail_passed": True,
        "use_guardrail": True,
        "conversation_id": "conv-test",
        "turn_id": "turn-test",
        "conversation_summary": None,
        "is_direct_routing": False,
    }


class _CapturingLLM:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("unexpected extra invoke")
        return AIMessage(content=self.responses.pop(0))


def test_resolve_brand_profile_falls_back_to_moyeo():
    assert resolve_brand_profile(None).display_name == "moyeo"
    assert resolve_brand_profile("unknown-site").display_name == "moyeo"


def test_planner_messages_use_food_branding():
    messages = planner._build_planner_messages(
        {**_base_state(site_id="site-a"), "conversation_summary": None},
        include_label_text_contract=False,
    )

    assert "food" in messages[0].content
    assert "MOYEO" not in messages[0].content


def test_planner_messages_use_bilyeo_branding():
    messages = planner._build_planner_messages(
        {**_base_state(site_id="site-b"), "conversation_summary": None},
        include_label_text_contract=False,
    )

    assert "bilyeo" in messages[0].content
    assert "MOYEO" not in messages[0].content


def test_planner_messages_use_moyeo_branding():
    messages = planner._build_planner_messages(
        {**_base_state(site_id="site-c"), "conversation_summary": None},
        include_label_text_contract=False,
    )

    assert "moyeo" in messages[0].content
    assert "MOYEO" not in messages[0].content


def test_final_generator_general_chat_uses_site_brand(monkeypatch):
    fake_llm = _CapturingLLM(["브랜드 응답"])
    monkeypatch.setattr(final_generator, "make_chat_llm", lambda **_: fake_llm)

    result = final_generator.final_generator_node(_base_state(site_id="site-b"))

    assert result["messages"][0].content == "브랜드 응답"
    assert "bilyeo" in fake_llm.calls[0][0].content
    assert "MOYEO" not in fake_llm.calls[0][0].content


def test_order_subagent_prompt_uses_site_brand(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(order_subagent, "make_chat_llm", lambda **_: object())

    def _fake_agent(*, model, tools, prompt):
        del model, tools
        captured["prompt"] = prompt.content
        return SimpleNamespace(invoke=lambda payload: {"messages": payload["messages"]})

    monkeypatch.setattr(order_subagent, "create_react_agent", _fake_agent)

    state = _base_state(site_id="site-a")
    state["messages"] = [HumanMessage(content="주문 취소해줘")]
    state["current_active_task"] = TaskIntent.ORDER_CS

    order_subagent.order_subagent_node(state)

    assert "food" in captured["prompt"]
    assert "MOYEO" not in captured["prompt"]


def test_policy_rag_pipeline_uses_site_brand(monkeypatch):
    fake_llm = _CapturingLLM(["환불 규정", "정책 답변"])
    monkeypatch.setattr(policy_rag_subagent, "make_chat_llm", lambda **_: fake_llm)
    monkeypatch.setattr(
        policy_rag_subagent,
        "search_knowledge_base",
        SimpleNamespace(
            invoke=lambda payload: {
                "documents": ["교환은 7일 이내 가능합니다."],
                "items": [],
                "count": 1,
            }
        ),
    )

    state = _base_state(site_id="site-b")
    result = policy_rag_subagent.policy_rag_subagent_node(state)

    assert result["messages"][0].content == "정책 답변"
    assert len(fake_llm.calls) == 2
    assert "bilyeo" in fake_llm.calls[1][0].content
    assert "MOYEO" not in fake_llm.calls[1][0].content


def test_discovery_subagent_prompt_uses_site_brand(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(discovery_subagent, "_run_direct_text_search", lambda query: None)
    monkeypatch.setattr(discovery_subagent, "make_chat_llm", lambda **_: object())

    def _fake_agent(*, model, tools, prompt):
        del model, tools
        captured["prompt"] = prompt.content
        return SimpleNamespace(invoke=lambda payload: {"messages": [AIMessage(content="추천 결과")]})

    monkeypatch.setattr(discovery_subagent, "create_react_agent", _fake_agent)

    state = _base_state(site_id="site-c")
    state["messages"] = [HumanMessage(content="검은 자켓 추천해줘")]
    state["current_active_task"] = TaskIntent.SEARCH_SIMILAR_TEXT

    discovery_subagent.discovery_subagent_node(state)

    assert "moyeo" in captured["prompt"]
    assert "MOYEO" not in captured["prompt"]


def test_form_action_subagent_prompt_uses_site_brand(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(form_action_subagent, "make_chat_llm", lambda **_: object())

    def _fake_agent(*, model, tools, prompt):
        del model, tools
        captured["prompt"] = prompt.content
        return SimpleNamespace(invoke=lambda payload: {"messages": [AIMessage(content="폼 안내")]})

    monkeypatch.setattr(form_action_subagent, "create_react_agent", _fake_agent)

    state = _base_state(site_id="site-a")
    state["messages"] = [HumanMessage(content="리뷰 쓰고 싶어")]
    state["current_active_task"] = TaskIntent.WRITE_REVIEW

    form_action_subagent.form_action_subagent_node(state)

    assert "food" in captured["prompt"]
    assert "MOYEO" not in captured["prompt"]
