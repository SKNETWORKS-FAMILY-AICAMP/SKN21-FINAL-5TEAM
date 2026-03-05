"""
LangGraph 멀티-에이전트 그래프 정의.

흐름 요약:
  START
    │
    ▼
  guardrail ──(차단)──────────────────────────────► END
    │ (통과)
    ▼
  planner ──(GENERAL_CHAT 단독)──────────────────► final_generator ──► END
    │ (서비스 intent 존재)
    ▼
  supervisor ─────────────┐
    │ (queue empty)        │ (loop: SubAgent 완료 후 다시 supervisor)
    ▼                      │
  final_generator          │
    │                      ▼
    ▼         ┌─ order_subagent
   END        ├─ discovery_subagent
              ├─ policy_rag_subagent
              └─ form_action_subagent

조건부 엣지:
  - route_after_guardrail  : guardrail_passed → "planner" | "end"
  - route_after_planner    : pending_tasks 내용 → "final_generator" | "supervisor"
  - route_after_supervisor : current_active_task → 해당 SubAgent 노드 이름 | "final_generator"

모든 SubAgent는 완료 후 반드시 "supervisor"로 돌아감
  (supervisor가 pending_tasks를 소진하면 "final_generator"로 전환).
"""

from langgraph.graph import StateGraph, START, END

from ecommerce.chatbot.src.graph.state import GlobalAgentState

# ── 노드 임포트 ──────────────────────────────────────────
from ecommerce.chatbot.src.graph.nodes.guardrail import (
    guardrail_node,
    route_after_guardrail,
)
from ecommerce.chatbot.src.graph.nodes.planner import (
    planner_node,
    route_after_planner,
)
from ecommerce.chatbot.src.graph.nodes.supervisor import (
    supervisor_node,
    route_after_supervisor,
)
from ecommerce.chatbot.src.graph.nodes.order_subagent import order_subagent_node
from ecommerce.chatbot.src.graph.nodes.discovery_subagent import discovery_subagent_node
from ecommerce.chatbot.src.graph.nodes.policy_rag_subagent import policy_rag_subagent_node
from ecommerce.chatbot.src.graph.nodes.form_action_subagent import form_action_subagent_node
from ecommerce.chatbot.src.graph.nodes.final_generator import final_generator_node
from ecommerce.chatbot.src.graph.nodes.summarize import summarize_node


# ── 그래프 빌드 ──────────────────────────────────────────

def build_graph() -> StateGraph:
    builder = StateGraph(GlobalAgentState)

    # ── 노드 등록 ─────────────────────────────────────
    builder.add_node("guardrail",              guardrail_node)
    builder.add_node("planner",                planner_node)
    builder.add_node("supervisor",             supervisor_node)
    builder.add_node("order_subagent",        order_subagent_node)
    builder.add_node("discovery_subagent",     discovery_subagent_node)
    builder.add_node("policy_rag_subagent",    policy_rag_subagent_node)
    builder.add_node("form_action_subagent",   form_action_subagent_node)
    builder.add_node("final_generator",        final_generator_node)
    builder.add_node("summarize",              summarize_node)

    # ── 엔트리포인트 ──────────────────────────────────
    builder.add_edge(START, "guardrail")

    # ── guardrail → (planner | END) ──────────────────
    builder.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {
            "planner": "planner",
            "end":     END,
        },
    )

    # ── planner → (supervisor | final_generator) ─────
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "supervisor":       "supervisor",
            "final_generator":  "final_generator",
        },
    )

    # ── supervisor → (SubAgent | final_generator) ────
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "order_subagent":       "order_subagent",
            "discovery_subagent":    "discovery_subagent",
            "policy_rag_subagent":   "policy_rag_subagent",
            "form_action_subagent":  "form_action_subagent",
            "final_generator":       "final_generator",
        },
    )

    # ── SubAgent → supervisor (loop) ─────────────────
    # 각 SubAgent는 처리 완료 후 항상 supervisor 로 돌아가
    # supervisor가 pending_tasks 소진 여부를 판단해 final_generator로 전환한다.
    for subagent in (
        "order_subagent",
        "discovery_subagent",
        "policy_rag_subagent",
        "form_action_subagent",
    ):
        builder.add_edge(subagent, "supervisor")

    # ── final_generator → summarize → END ──────────────────
    builder.add_edge("final_generator", "summarize")
    builder.add_edge("summarize", END)

    return builder


# ── 컴파일된 그래프 (싱글톤 인스턴스) ────────────────────────
# chat.py endpoint 에서 `from ...workflow import graph_app` 으로 사용.
graph_app = build_graph().compile()
