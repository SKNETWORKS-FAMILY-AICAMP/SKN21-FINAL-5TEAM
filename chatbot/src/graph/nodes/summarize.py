"""
Summarize 노드.

역할:
  - final_generator 완료 직후 실행 (사용자는 이미 답변을 받은 상태).
  - 오래된 메시지 이력을 kobart로 요약 → conversation_summary 업데이트.
  - 요약된 메시지는 state에서 RemoveMessage로 제거 → 컨텍스트 길이 절약.

트리거 조건 (둘 중 하나라도 만족 시 요약 실행):
  - len(messages) >= 8   : 4턴 이상 누적 (Human + AI 각 1개 = 1턴 = 2개)
  - completed_tasks 존재 : CS 처리가 완료된 턴 (환불/교환/취소 등)

요약 후 state 변화:
  - conversation_summary : 이전 요약 + 현재 대화를 kobart로 재요약
  - messages             : 최근 KEEP_TURNS턴(기본 2개 메시지)만 유지, 나머지는 RemoveMessage로 삭제
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from ecommerce.chatbot.src.graph.state import GlobalAgentState
from ecommerce.chatbot.src.infrastructure.kobart_summarizer import summarize_conversation

logger = logging.getLogger(__name__)

# 최근 N개 메시지(Human+AI 쌍)는 truncate하지 않고 유지
# 2 = 마지막 1턴(Human 1 + AI 1)만 보존
_KEEP_MESSAGES = 2

# 트리거: messages 누적 수 임계값
_TRIGGER_MSG_COUNT = 8


def summarize_node(state: GlobalAgentState) -> dict[str, Any]:
    """
    대화 요약 노드.

    조건을 만족하면:
      1. 오래된 messages → 텍스트 변환 → kobart 요약
      2. conversation_summary 업데이트
      3. 오래된 messages RemoveMessage로 제거
    조건 불만족 시 state 변경 없이 빈 dict 반환.
    """
    messages: list = list(state.get("messages", []))
    completed_tasks: list = state.get("completed_tasks", [])
    prev_summary: str | None = state.get("conversation_summary")

    # ── 트리거 조건 체크 ──────────────────────────────────
    should_summarize = (
        len(messages) >= _TRIGGER_MSG_COUNT
        or bool(completed_tasks)
    )

    if not should_summarize:
        logger.debug("[Summarize] 조건 미충족 (messages=%d, tasks=%s) → 스킵",
                     len(messages), completed_tasks)
        return {}

    # 보존할 메시지 수 이하면 요약 불필요
    if len(messages) <= _KEEP_MESSAGES:
        return {}

    # ── 요약 대상 분리 ────────────────────────────────────
    to_summarize = messages[:-_KEEP_MESSAGES]   # 오래된 메시지들
    # recent = messages[-_KEEP_MESSAGES:]       # 보존할 최근 메시지 (참고용)

    # ── 텍스트 변환 ───────────────────────────────────────
    lines: list[str] = []

    # 이전 요약이 있으면 먼저 추가 (누적 요약)
    if prev_summary:
        lines.append(f"[이전 대화 요약]\n{prev_summary}")

    for msg in to_summarize:
        if isinstance(msg, HumanMessage):
            content = str(msg.content)[:300]   # 개별 메시지 300자 제한
            lines.append(f"사용자: {content}")
        elif isinstance(msg, AIMessage):
            content = str(msg.content)[:300]
            lines.append(f"상담원: {content}")
        # ToolMessage, SystemMessage 등은 요약 대상에서 제외

    if not lines:
        return {}

    text_to_summarize = "\n".join(lines)

    # ── kobart 요약 호출 ──────────────────────────────────
    logger.info("[Summarize] 요약 시작 (대상 %d개 메시지)", len(to_summarize))
    new_summary = summarize_conversation(text_to_summarize)

    if not new_summary:
        logger.warning("[Summarize] kobart 요약 실패 → 메시지 유지")
        return {}

    logger.info("[Summarize] 요약 완료: %d자", len(new_summary))

    # ── 오래된 메시지 RemoveMessage로 삭제 ───────────────
    remove_ops = []
    for msg in to_summarize:
        msg_id = getattr(msg, "id", None)
        if msg_id:
            remove_ops.append(RemoveMessage(id=msg_id))

    return {
        "conversation_summary": new_summary,
        "messages": remove_ops,  # add_messages 리듀서가 RemoveMessage 처리
    }
