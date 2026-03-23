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
    ▼         ┌─ order_entry -> order_intent_router -> cancel/refund/exchange/shipping
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
from langgraph.checkpoint.memory import InMemorySaver

from chatbot.src.graph.state import GlobalAgentState

# ── 노드 임포트 ──────────────────────────────────────────
from chatbot.src.graph.nodes.guardrail import (
    guardrail_node,
    route_after_guardrail,
)
from chatbot.src.graph.nodes.planner import (
    planner_node,
    route_after_planner,
)
from chatbot.src.graph.nodes.supervisor import (
    supervisor_node,
    route_after_supervisor,
)
from chatbot.src.graph.nodes.order_flow import (
    order_entry_node,
    order_intent_router_node,
    route_after_order_intent_router,
    route_after_order_action,
    cancel_subagent_node,
    refund_subagent_node,
    exchange_subagent_node,
    shipping_subagent_node,
    order_list_subagent_node,
)
from chatbot.src.graph.nodes.discovery_subagent import discovery_subagent_node
from chatbot.src.graph.nodes.policy_rag_subagent import policy_rag_subagent_node
from chatbot.src.graph.nodes.form_action_subagent import form_action_subagent_node
from chatbot.src.graph.nodes.final_generator import final_generator_node
from chatbot.src.graph.nodes.summarize import summarize_node


# ── 라우팅 함수 (Direct Routing 모드 지원) ─────────────────

def route_from_start(state: GlobalAgentState) -> str:
    """START 지점에서 직행 평가 모드 여부에 따라 분기합니다.
    
    - is_direct_routing == True  → order_intent_router 직행 (평가 모드)
    - is_direct_routing == False → guardrail 경유 (운영 모드, 기본값)
    """
    if state.get("is_direct_routing", False):
        return "order_intent_router"
    return "guardrail"


# ── 그래프 빌드 ──────────────────────────────────────────

def build_graph() -> StateGraph:
    builder = StateGraph(GlobalAgentState)

    # ── 노드 등록 ─────────────────────────────────────
    builder.add_node("guardrail",              guardrail_node)
    builder.add_node("planner",                planner_node)
    builder.add_node("supervisor",             supervisor_node)
    builder.add_node("order_entry",            order_entry_node)
    builder.add_node("order_intent_router",    order_intent_router_node)
    builder.add_node("cancel_subagent",        cancel_subagent_node)
    builder.add_node("refund_subagent",        refund_subagent_node)
    builder.add_node("exchange_subagent",      exchange_subagent_node)
    builder.add_node("shipping_subagent",      shipping_subagent_node)
    builder.add_node("order_list_subagent",    order_list_subagent_node)
    builder.add_node("discovery_subagent",     discovery_subagent_node)
    builder.add_node("policy_rag_subagent",    policy_rag_subagent_node)
    builder.add_node("form_action_subagent",   form_action_subagent_node)
    builder.add_node("final_generator",        final_generator_node)
    builder.add_node("summarize",              summarize_node)

    # ── 엔트리포인트 (조건부: 운영 vs 평가 모드) ──────────
    # is_direct_routing == True  → order_intent_router 직행
    # is_direct_routing == False → guardrail 경유 (기존 흐름)
    builder.add_conditional_edges(
        START,
        route_from_start,
        {
            "guardrail":            "guardrail",
            "order_intent_router":  "order_intent_router",
        },
    )

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
            "order_entry":           "order_entry",
            "discovery_subagent":    "discovery_subagent",
            "policy_rag_subagent":   "policy_rag_subagent",
            "form_action_subagent":  "form_action_subagent",
            "order_list_subagent":   "order_list_subagent",
            "final_generator":       "final_generator",
        },
    )

    # ── ORDER_CS 세부 라우팅 ─────────────────────────────
    builder.add_edge("order_entry", "order_intent_router")
    builder.add_conditional_edges(
        "order_intent_router",
        route_after_order_intent_router,
        {
            "cancel_subagent": "cancel_subagent",
            "refund_subagent": "refund_subagent",
            "exchange_subagent": "exchange_subagent",
            "shipping_subagent": "shipping_subagent",
            "order_list_subagent": "order_list_subagent",
            "final_generator": "final_generator",
        },
    )

    for order_node in (
        "cancel_subagent",
        "refund_subagent",
        "exchange_subagent",
        "shipping_subagent",
    ):
        builder.add_conditional_edges(
            order_node,
            route_after_order_action,
            {
                "supervisor": "supervisor",
                "final_generator": "final_generator",
            },
        )

    builder.add_edge("order_list_subagent", "final_generator")

    # ── 나머지 SubAgent → supervisor (loop) ───────────────
    for subagent in (
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
_checkpointer = InMemorySaver()
graph_app = build_graph().compile(checkpointer=_checkpointer)
