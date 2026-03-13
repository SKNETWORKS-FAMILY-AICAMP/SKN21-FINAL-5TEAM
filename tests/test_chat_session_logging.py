from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from chatbot.src.schemas.chat import FeedbackRequest
from chatbot.src.infrastructure.conversation_logger import SessionConversationLogger


def test_feedback_schema_accepts_supported_labels() -> None:
    good = FeedbackRequest(conversation_id="conv_123", feedback_label="good")
    bad = FeedbackRequest(conversation_id="conv_123", feedback_label="bad")

    assert good.feedback_label == "good"
    assert bad.feedback_label == "bad"


def test_feedback_schema_rejects_unknown_label() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(conversation_id="conv_123", feedback_label="meh")


def test_session_logger_records_selected_state_and_training_pairs(tmp_path) -> None:
    logger = SessionConversationLogger(
        conversation_id="conv_123",
        user_id=7,
        base_dir=str(tmp_path),
        selected_state_fields=("conversation_summary", "search_context", "completed_tasks"),
    )

    logger.append_turn(
        user_message="배송 언제 와?",
        assistant_message="내일 도착 예정입니다.",
        state={
            "conversation_summary": "배송 문의",
            "search_context": {"query": "배송"},
            "completed_tasks": ["shipping_lookup"],
            "order_context": {"ignored": True},
        },
    )
    logger.append_turn(
        user_message="주소 바꿀 수 있어?",
        assistant_message="출고 전이면 가능합니다.",
        state={
            "conversation_summary": "주소 변경 문의",
            "search_context": {"query": "주소 변경"},
            "completed_tasks": ["shipping_lookup", "address_change"],
        },
    )

    current = logger.read_session()

    assert [item["role"] for item in current["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert current["selected_state"] == {
        "conversation_summary": "주소 변경 문의",
        "search_context": {"query": "주소 변경"},
        "completed_tasks": ["shipping_lookup", "address_change"],
    }
    assert current["training_pairs"] == [
        {
            "turn_index": 0,
            "input": "배송 언제 와?",
            "output": "내일 도착 예정입니다.",
        },
        {
            "turn_index": 1,
            "input": "주소 바꿀 수 있어?",
            "output": "출고 전이면 가능합니다.",
        },
    ]


def test_session_logger_finalizes_feedback_and_marks_reset_required(tmp_path) -> None:
    logger = SessionConversationLogger(
        conversation_id="conv_999",
        user_id=99,
        base_dir=str(tmp_path),
    )
    logger.append_turn(
        user_message="추천해줘",
        assistant_message="캐주얼 셔츠를 추천드릴게요.",
        state={"conversation_summary": "추천 요청"},
    )

    result = logger.finalize_feedback("good")

    assert result["status"] == "completed"
    assert result["feedback_label"] == "good"
    assert result["reset_required"] is True
    assert result["ended_at"]

    saved_path = tmp_path / "conv_999.json"
    assert saved_path.exists()

    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["feedback_label"] == "good"
    assert saved["training_pairs"] == [
        {
            "turn_index": 0,
            "input": "추천해줘",
            "output": "캐주얼 셔츠를 추천드릴게요.",
        }
    ]
