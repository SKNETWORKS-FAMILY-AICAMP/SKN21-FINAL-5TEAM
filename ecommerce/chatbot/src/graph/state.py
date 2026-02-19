from typing import Annotated, TypedDict, List, Dict, Any, Union, Optional, Literal
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

# OrderInfo as a Dict for slot information (from remote version)
OrderInfo = Dict[str, Any]

class AgentState(TypedDict):
    """
    이커머스 CS 상담 및 액션 수행 에이전트의 통합 상태 관리 클래스
    """
    
    # 1. 대화 관리
    # Note: Using Union[BaseMessage, Dict[str, Any]] to support both formats if needed, 
    # but the logic generally expects a list of messages.
    messages: Annotated[List[Any], add_messages]
    question: str
    generation: str
    
    # 2. 검색 및 지식 베이스
    documents: List[str] 
    refined_context: str
    
    # 3. 분석 결과 (NLU) & 사용자 컨텍스트
    category: Optional[str]         # '배송', '취소/반품/교환' 등
    intent_type: str               # 'info_search' (규정 조회) vs 'execution' (직접 실행)
    is_authenticated: bool
    user_info: Dict[str, Any]
    
    # 4. 액션 제어 및 도구 실행 결과
    tool_outputs: List[Dict[str, Any]]
    
    # 5. [Refactored State] Structured Task Context
    # 모든 기존 액션 상태(action_name, action_status, prior_action, order_id 등)는 여기에 통합됨
    current_task: Optional["TaskContext"]
    
    # 6. 제어 플래그
    is_relevant: bool
    is_general_chat: bool
    retry_count: int
    requires_selection: Optional[bool]  # 주문 목록 조회 시 선택 UI 표시 여부

class TaskContext(TypedDict):
    """
    현재 진행 중인 작업의 컨텍스트를 구조화하여 관리합니다.
    """
    type: Literal["refund", "cancel", "exchange", "search", "general"]  # 작업 유형
    status: Literal["idle", "validating", "approving", "executing", "completed"] # 진행 단계
    target_id: Optional[str]  # 대상 ID (예: order_id)
    reason: Optional[str]     # 사유 (예: 반품 사유)
    missing_info: Optional[List[str]] # 부족한 정보 목록
