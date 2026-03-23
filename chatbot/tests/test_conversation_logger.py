import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.infrastructure.conversation_logger import SessionConversationLogger


def test_record_feedback_updates_active_session_without_completing(tmp_path):
    logger = SessionConversationLogger(
        conversation_id="conv_test",
        user_id=7,
        base_dir=str(tmp_path),
    )

    logger.append_turn(
        user_message="배송 언제 와?",
        assistant_message="내일 도착 예정입니다.",
        state={"conversation_summary": "배송 문의"},
    )

    recorded = logger.record_feedback("good")

    assert recorded["feedback_label"] == "good"
    assert recorded["status"] == "in_progress"
    assert recorded["reset_required"] is False
    assert recorded["ended_at"] is None

    appended = logger.append_turn(
        user_message="주소 변경도 가능해?",
        assistant_message="출고 전이면 가능합니다.",
        state={"conversation_summary": "주소 변경 문의"},
    )

    assert appended["feedback_label"] == "good"
    assert appended["status"] == "in_progress"


def test_finalize_feedback_marks_session_completed(tmp_path):
    logger = SessionConversationLogger(
        conversation_id="conv_test",
        user_id=7,
        base_dir=str(tmp_path),
    )

    logger.append_turn(
        user_message="반품 문의",
        assistant_message="반품 접수를 도와드릴게요.",
    )

    finalized = logger.finalize_feedback("bad")

    assert finalized["feedback_label"] == "bad"
    assert finalized["status"] == "completed"
    assert finalized["reset_required"] is True
    assert finalized["ended_at"] is not None
