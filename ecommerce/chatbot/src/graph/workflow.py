
from langgraph.graph import StateGraph, START, END
from ecommerce.chatbot.src.graph.state import AgentState
# Import new nodes from nodes_v2
from ecommerce.chatbot.src.graph.nodes_v2 import (
    agent_node, 
    tool_node, 
    should_continue, 
    process_output_node,
    smart_validation_node,
    human_approval_node,
    route_after_validation,
    route_after_approval,
    route_after_tools
)

def create_graph():
    """
    Tool Calling 기반의 Agent 워크플로우를 생성합니다.
    구조: Agent -> (Tools or End) -> Process Output -> End
    [Updated] Validation & Human Approval 추가
    """
    workflow = StateGraph(AgentState)

    # 1. 노드 등록
    workflow.add_node("agent", agent_node)
    workflow.add_node("validation", smart_validation_node)
    workflow.add_node("approval", human_approval_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("process_output", process_output_node)

    # 2. 엣지 연결
    workflow.add_edge(START, "agent")
    
    # [Agent -> Decision: Tools or End]
    # 도구 호출이 없으면 바로 종료(Process Output), 있으면 검증(Validation)으로 이동
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "validation", # 도구 호출 시 바로 실행하지 않고 검증 단계를 거침
            "end": "process_output"
        }
    )
    
    # [Validation -> Decision: Approval or Tools]
    # 검증 후, 민감한 도구(Sensitive)는 승인(Approval)으로, 안전한 도구는 실행(Tools)으로, 
    # 검증 결과 도구 호출이 취소되었으면 종료(End)로 갈 수도 있음
    workflow.add_conditional_edges(
        "validation",
        route_after_validation,
        {
            "tools": "tools",
            "human_approval": "approval",
            "end": "process_output"
        }
    )
    
    # [Approval -> Decision: Tools or End]
    # 승인되면 Tools, 아니면 Process Output (UI 표시 후 종료)
    workflow.add_conditional_edges(
        "approval",
        route_after_approval,
        {
            "tools": "tools",
            "process_output": "process_output"
        }
    )
    
    # [Tools -> Decision: Agent or Process Output]
    # UI Action이 있는 경우 Agent를 거치지 않고 바로 종료 (텍스트 생성 방지)
    workflow.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "agent": "agent",
            "process_output": "process_output"
        }
    )
    
    # [Process Output -> End]
    workflow.add_edge("process_output", END)

    return workflow.compile()

# 싱글톤 패턴의 그래프 앱 인스턴스
graph_app = create_graph()
