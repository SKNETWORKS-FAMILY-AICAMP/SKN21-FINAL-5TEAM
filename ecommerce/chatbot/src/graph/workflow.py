from langgraph.graph import StateGraph, START, END
from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.graph.nodes_v2 import (
    guardrail_node,
    route_after_guardrail,
    preprocess_node,
    agent_node,
    tool_node,
    should_continue,
    process_output_node,
    smart_validation_node,
    human_approval_node,
    route_after_validation,
    route_after_approval,
    route_after_tools,
)


def create_graph():
    """
    Agent 중심 워크플로우 (v2)

    구조:
    START -> Guardrail -> (Process Output | Preprocess)
          -> Preprocess -> Agent
          -> Agent -> (Validation | Process Output)
          -> Validation -> (Tools | Approval | Process Output)
          -> Approval -> (Tools | Process Output)
          -> Tools -> (Agent | Process Output)
          -> Process Output -> End
    """
    workflow = StateGraph(AgentState)

    # 1. 노드 등록
    workflow.add_node("guardrail", guardrail_node)
    workflow.add_node("preprocess", preprocess_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("validation", smart_validation_node)
    workflow.add_node("approval", human_approval_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("process_output", process_output_node)

    # 2. 엣지 연결
    workflow.add_edge(START, "guardrail")

    # [Guardrail -> Preprocess / Process Output]
    workflow.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {
            "preprocess": "preprocess",
            "process_output": "process_output",
        },
    )

    # [Preprocess -> Agent] (항상)
    workflow.add_edge("preprocess", "agent")

    # [Agent -> Validation or Process Output]
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "validation",
            "end": "process_output",
        },
    )

    # [Validation -> Tools / Approval / Process Output]
    workflow.add_conditional_edges(
        "validation",
        route_after_validation,
        {"tools": "tools", "human_approval": "approval", "end": "process_output"},
    )

    # [Approval -> Tools / Process Output]
    workflow.add_conditional_edges(
        "approval",
        route_after_approval,
        {"tools": "tools", "process_output": "process_output"},
    )

    # [Tools -> Agent / Process Output]
    workflow.add_conditional_edges(
        "tools",
        route_after_tools,
        {"agent": "agent", "process_output": "process_output"},
    )

    workflow.add_edge("process_output", END)

    return workflow.compile()


# 싱글톤 패턴의 그래프 앱 인스턴스
graph_app = create_graph()
