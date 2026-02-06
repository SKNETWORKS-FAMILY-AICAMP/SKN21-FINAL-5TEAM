
from langgraph.graph import StateGraph, START, END
from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.graph.nodes import (
    retrieve, generate, update_state_node, no_info_node,
    check_eligibility_node, execute_action_node, human_approval_node
)

# --- 라우팅 함수 정의 ---

def route_after_nlu(state: AgentState):
    """
    NLU 결과에 따라 '지식 검색' 경로 또는 '액션 수행' 경로로 분기합니다.
    """
    if not state.get("is_relevant"):
        return "no_info"
    
    # 이미 승인된 액션인 경우 바로 실행 노드로
    if state.get("action_status") == "approved":
        return "execute_action"
    
    # 의도 유형에 따른 분기
    if state.get("intent_type") == "execution":
        return "check_eligibility"
    return "retrieve"

def route_after_eligibility(state: AgentState):
    """
    액션 수행 자격 확인 결과에 따라 다음 노드를 결정합니다.
    """
    status = state.get("action_status")
    if status == "approved":
        return "execute_action"
    elif status == "pending_approval":
        return "human_approval"
    return "generate" # 실패 사유를 안내하기 위해 생성 노드로 이동

def route_after_retrieval(state: AgentState):
    """
    검색(retrieve) 결과의 유효성에 따라 답변 생성 여부를 결정합니다.
    """
    if state.get("is_relevant"):
        return "generate"
    return "no_info"

def create_graph():
    """
    고도화된 RAG + Action 에이전트 워크플로우를 생성합니다.
    """
    workflow = StateGraph(AgentState)

    # 1. 노드 등록
    workflow.add_node("update_state", update_state_node)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("check_eligibility", check_eligibility_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("execute_action", execute_action_node)
    workflow.add_node("generate", generate)
    workflow.add_node("no_info", no_info_node)

    # 2. 엣지 연결 (지능형 라우팅 구조)
    workflow.add_edge(START, "update_state")
    
    # [NLU -> 검색 vs 액션 확인]
    workflow.add_conditional_edges(
        "update_state",
        route_after_nlu,
        {
            "retrieve": "retrieve",
            "check_eligibility": "check_eligibility",
            "execute_action": "execute_action",
            "no_info": "no_info"
        }
    )
    
    # [액션 확인 -> 도구 실행]
    workflow.add_conditional_edges(
        "check_eligibility",
        route_after_eligibility,
        {
            "execute_action": "execute_action",
            "human_approval": "human_approval",
            "generate": "generate"
        }
    )
    
    # [승인 요청 -> 사용자 응답 대기]
    # 생성 노드를 거치지 않고 바로 END로 가거나, 
    # 혹은 질문을 generation에 담아 generate 노드(혹은 전용 노드)에서 끝냄
    workflow.add_edge("human_approval", END)
    
    # [도구 실행 -> 답변 생성]
    workflow.add_edge("execute_action", "generate")
    
    # [검색 -> 답변 생성]
    workflow.add_conditional_edges(
        "retrieve",
        route_after_retrieval,
        {
            "generate": "generate",
            "no_info": "no_info"
        }
    )
    
    workflow.add_edge("generate", END)
    workflow.add_edge("no_info", END)

    return workflow.compile()

# 싱글톤 패턴의 그래프 앱 인스턴스
graph_app = create_graph()
