"""
Supervisor Router 노드.

역할:
  1. pending_tasks 큐에서 작업을 하나씩 꺼내 current_active_task 에 할당.
  2. TaskIntent 에 따라 적절한 SubAgent 노드로 라우팅.
  3. 큐가 비어 있으면 → final_generator 로 이동.

설계 원칙:
  - Supervisor 자체는 LLM 호출 없음. 순수 Python 라우팅 로직.
  - 큐(pending_tasks) 기반 순차 처리: 복합 요청도 한 번에 하나씩 처리.
"""

from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.schemas.planner import TaskIntent

# TaskIntent → SubAgent 노드 이름 매핑
_INTENT_TO_NODE: dict[str, str] = {
    TaskIntent.ORDER_CS:             "order_entry",
    TaskIntent.SEARCH_SIMILAR_TEXT:  "discovery_subagent",
    TaskIntent.SEARCH_SIMILAR_IMAGE: "discovery_subagent",
    TaskIntent.POLICY_RAG:           "policy_rag_subagent",
    TaskIntent.REGISTER_USED_ITEM:   "form_action_subagent",
    TaskIntent.WRITE_REVIEW:         "form_action_subagent",
    TaskIntent.REGISTER_GIFT_CARD:   "form_action_subagent",
    TaskIntent.GENERAL_CHAT:         "final_generator",
}


# ── 노드 함수 ─────────────────────────────────────────────

def supervisor_node(state: GlobalAgentState) -> dict:
    """
    pending_tasks 큐의 첫 번째 작업을 꺼내 current_active_task 에 할당.
    처리한 작업은 큐에서 제거.
    """
    pending = list(state.get("pending_tasks", []))

    if not pending:
        # 큐가 비어 있음 → route_after_supervisor 에서 final_generator 로 분기
        return {
            "current_active_task": None,
            "pending_tasks": [],
        }

    # 큐의 첫 번째 작업 추출
    current_task = pending.pop(0)

    return {
        "current_active_task": current_task,
        "pending_tasks": pending,       # 나머지 작업은 큐에 유지
    }


# ── 라우팅 조건 함수 ──────────────────────────────────────

def route_after_supervisor(state: GlobalAgentState) -> str:
    """
    current_active_task 에 따라 다음 노드를 결정.
    작업이 없으면 final_generator 로 직행.
    """
    task = state.get("current_active_task")

    if not task:
        return "final_generator"

    return _INTENT_TO_NODE.get(task, "final_generator")
