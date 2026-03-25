from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.graph.nodes import final_generator
from chatbot.src.schemas.planner import TaskIntent


def _base_state() -> dict:
    return {
        "messages": [HumanMessage(content="교환 처리 결과 알려줘")],
        "pending_tasks": [],
        "completed_tasks": [],
        "current_active_task": None,
        "order_context": {},
        "search_context": {},
        "ui_action_required": None,
        "user_info": {"id": 1, "name": "테스트유저"},
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


def test_final_generator_formats_single_completed_order_cs_without_llm(monkeypatch):
    state = _base_state()
    state["completed_tasks"] = [TaskIntent.ORDER_CS]
    state["agent_results"] = {
        TaskIntent.ORDER_CS: "교환 신청이 완료되었습니다. 상품 회수를 위해 기사님이 방문할 예정입니다.",
    }
    state["order_context"] = {
        "pending_action": "exchange",
        "target_order_id": "ORD-20260303-0001",
        "last_action_status": "exchange_requested",
        "action_status": "completed",
    }

    monkeypatch.setattr(
        final_generator,
        "make_chat_llm",
        lambda **_: (_ for _ in ()).throw(AssertionError("LLM should not be called for single ORDER_CS formatting")),
    )

    result = final_generator.final_generator_node(state)

    assert result["messages"]
    content = result["messages"][0].content
    assert "요청하신 교환 처리 결과입니다." in content
    assert "주문번호: ORD-20260303-0001" in content
    assert "처리 상태: 교환 신청 접수" in content
    assert "교환 신청이 완료되었습니다." in content


def test_final_generator_formats_single_failed_order_cs_even_without_completed_tasks(monkeypatch):
    state = _base_state()
    state["agent_results"] = {
        TaskIntent.ORDER_CS: "교환 가능한 주문을 찾지 못했습니다.",
    }
    state["order_context"] = {
        "pending_action": "exchange",
        "target_order_id": "ORD-20260303-0001",
        "last_action_status": "failed",
        "action_status": "failed",
    }

    monkeypatch.setattr(
        final_generator,
        "make_chat_llm",
        lambda **_: (_ for _ in ()).throw(AssertionError("LLM should not be called for single ORDER_CS formatting")),
    )

    result = final_generator.final_generator_node(state)

    assert result["messages"]
    content = result["messages"][0].content
    assert "요청하신 교환 처리 결과입니다." in content
    assert "주문번호: ORD-20260303-0001" in content
    assert "처리 상태: 처리 실패" in content
    assert "교환 가능한 주문을 찾지 못했습니다." in content


def test_final_generator_formats_single_policy_rag_result_without_llm(monkeypatch):
    state = _base_state()
    state["completed_tasks"] = [TaskIntent.POLICY_RAG]
    state["agent_results"] = {
        TaskIntent.POLICY_RAG: "교환은 상품 수령 후 7일 이내에 신청하실 수 있습니다.",
    }

    monkeypatch.setattr(
        final_generator,
        "make_chat_llm",
        lambda **_: (_ for _ in ()).throw(AssertionError("LLM should not be called for single task formatting")),
    )

    result = final_generator.final_generator_node(state)

    assert result["messages"]
    content = result["messages"][0].content
    assert content.startswith("문의하신 정책 안내입니다.")
    assert "교환은 상품 수령 후 7일 이내에 신청하실 수 있습니다." in content


def test_final_generator_keeps_ui_waiting_turn_textless(monkeypatch):
    state = _base_state()
    state["ui_action_required"] = "show_option_list"
    state["completed_tasks"] = [TaskIntent.ORDER_CS]
    state["agent_results"] = {
        TaskIntent.ORDER_CS: "옵션을 선택해 주세요.",
    }

    monkeypatch.setattr(
        final_generator,
        "make_chat_llm",
        lambda **_: (_ for _ in ()).throw(AssertionError("LLM should not be called while waiting for UI")),
    )

    result = final_generator.final_generator_node(state)

    assert result["ui_action_required"] == "show_option_list"
    assert result["messages"] == []
