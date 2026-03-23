from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.graph.nodes import planner
from chatbot.src.schemas.planner import PlannerOutput, TaskIntent


@dataclass(frozen=True)
class _FakeRuntimePolicy:
    provider: str
    model: str
    supports_structured_output: bool
    planner_output_mode: str
    planner_prompt_variant: str


class _SchemaStructuredLLM:
    def __init__(self, result: PlannerOutput):
        self.result = result
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.result


class _SchemaLLM:
    def __init__(self, result: PlannerOutput):
        self.result = result
        self.requested_schema = None
        self.structured = _SchemaStructuredLLM(result)

    def with_structured_output(self, schema):
        self.requested_schema = schema
        return self.structured


class _LabelTextLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("unexpected extra invoke")
        return AIMessage(content=self._responses.pop(0))


def _state(message: str, provider: str = "openai") -> dict:
    return {
        "messages": [HumanMessage(content=message)],
        "llm_provider": provider,
        "llm_model": "test-model",
        "conversation_summary": None,
    }


def test_planner_node_uses_structured_schema_for_schema_capable_provider(monkeypatch):
    fake_llm = _SchemaLLM(
        PlannerOutput(pending_tasks=[TaskIntent.ORDER_CS, TaskIntent.POLICY_RAG])
    )

    monkeypatch.setattr(
        planner,
        "resolve_llm_runtime_policy",
        lambda provider, model: _FakeRuntimePolicy(
            provider=provider,
            model=model,
            supports_structured_output=True,
            planner_output_mode="strict-schema",
            planner_prompt_variant="strict-schema",
        ),
        raising=False,
    )
    monkeypatch.setattr(planner, "make_chat_llm", lambda **_: fake_llm)

    result = planner.planner_node(_state("취소하고 환불 규정도 알려줘"))

    assert result["pending_tasks"] == ["ORDER_CS", "POLICY_RAG"]
    assert fake_llm.requested_schema is PlannerOutput
    assert len(fake_llm.structured.calls) == 1


def test_planner_node_uses_label_text_contract_for_local_provider(monkeypatch):
    fake_llm = _LabelTextLLM(["ORDER_CS, SEARCH_SIMILAR_TEXT"])

    monkeypatch.setattr(
        planner,
        "resolve_llm_runtime_policy",
        lambda provider, model: _FakeRuntimePolicy(
            provider=provider,
            model=model,
            supports_structured_output=False,
            planner_output_mode="strict-label-text",
            planner_prompt_variant="strict-label-text",
        ),
        raising=False,
    )
    monkeypatch.setattr(planner, "make_chat_llm", lambda **_: fake_llm)

    result = planner.planner_node(_state("취소하고 비슷한 상품도 찾아줘", provider="local"))

    assert result["pending_tasks"] == ["ORDER_CS", "SEARCH_SIMILAR_TEXT"]
    assert len(fake_llm.calls) == 1
    assert "허용된 라벨" in fake_llm.calls[0][0].content


def test_planner_node_retries_local_label_text_output_once(monkeypatch):
    fake_llm = _LabelTextLLM(["취소 요청 같아요", "ORDER_CS"])

    monkeypatch.setattr(
        planner,
        "resolve_llm_runtime_policy",
        lambda provider, model: _FakeRuntimePolicy(
            provider=provider,
            model=model,
            supports_structured_output=False,
            planner_output_mode="strict-label-text",
            planner_prompt_variant="strict-label-text",
        ),
        raising=False,
    )
    monkeypatch.setattr(planner, "make_chat_llm", lambda **_: fake_llm)

    result = planner.planner_node(_state("주문 취소할래요", provider="local"))

    assert result["pending_tasks"] == ["ORDER_CS"]
    assert len(fake_llm.calls) == 2
    assert "형식을 위반" in fake_llm.calls[1][-1].content


def test_planner_node_falls_back_to_general_chat_when_local_retry_still_invalid(monkeypatch):
    fake_llm = _LabelTextLLM(["잘 모르겠어요", "주문 같긴 한데요"])

    monkeypatch.setattr(
        planner,
        "resolve_llm_runtime_policy",
        lambda provider, model: _FakeRuntimePolicy(
            provider=provider,
            model=model,
            supports_structured_output=False,
            planner_output_mode="strict-label-text",
            planner_prompt_variant="strict-label-text",
        ),
        raising=False,
    )
    monkeypatch.setattr(planner, "make_chat_llm", lambda **_: fake_llm)

    result = planner.planner_node(_state("주문 취소할래요", provider="local"))

    assert result["pending_tasks"] == [TaskIntent.GENERAL_CHAT]
    assert len(fake_llm.calls) == 2


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("배송이 너무 지연되고 있어서 확인해보고 싶어요. 언제쯤 도착하나요?", ["ORDER_CS"]),
        ("매일 아침 뭘 입을까 고민하는데, 아무거나 걸쳐도 괜찮은 기본템 있으면 좋겠어요.", ["SEARCH_SIMILAR_TEXT"]),
        ("곧 면접이 있는데, 너무 딱딱하지 않으면서 신뢰감을 줄 수 있는 옷이 뭐가 있을까요?", ["SEARCH_SIMILAR_TEXT"]),
        ("택배를 받았는데 제품에 문제가 있어요. 개봉하면 반품이 불가능한지 궁금합니다.", ["POLICY_RAG"]),
        ("도서산간 지역에 사는데, 배송비가 추가로 얼마 더 드는지 알고 싶어요.", ["POLICY_RAG"]),
        ("적립금이 좀 쌓였는데, 이걸 현금처럼 자유롭게 쓸 수 있는지 알고 싶어요.", ["POLICY_RAG"]),
        ("결혼식 때만 입은 정장이 앞으로는 안 입을 것 같아서 상태 좋은 걸 넘기고 싶어요.", ["REGISTER_USED_ITEM"]),
        ("사이즈 고민하시는 분들 위해서 제 체형과 착용 사진을 공유하고 싶은데 어떻게 하면 될까요?", ["WRITE_REVIEW"]),
        ("세탁 후에 약간 변형이 있었는데, 이런 점도 다른 구매자분들이 알면 좋을 것 같아서 공유할게요.", ["WRITE_REVIEW"]),
        ("배송이 아주 빠르고 포장도 완벽해서 칭찬 후기를 어디에 남기면 좋을까요?", ["WRITE_REVIEW"]),
        ("카카오톡 선물함에 있는 상품권 코드 입력하는 곳이 어디인지 알고 싶어요.", ["REGISTER_GIFT_CARD"]),
    ],
)
def test_planner_node_short_circuits_known_hard_failures_with_rules(monkeypatch, message, expected):
    def fail_if_llm_called(**kwargs):
        raise AssertionError("high-precision planner rules should handle this case before LLM")

    monkeypatch.setattr(
        planner,
        "resolve_llm_runtime_policy",
        lambda provider, model: _FakeRuntimePolicy(
            provider=provider,
            model=model,
            supports_structured_output=False,
            planner_output_mode="strict-label-text",
            planner_prompt_variant="strict-label-text",
        ),
        raising=False,
    )
    monkeypatch.setattr(planner, "make_chat_llm", fail_if_llm_called)

    result = planner.planner_node(_state(message, provider="local"))

    assert result["pending_tasks"] == expected
