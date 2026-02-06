from typing import Annotated, TypedDict, List, Dict, Any, Union, Optional
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
    
    # 3. 분석 결과 (NLU)
    category: Optional[str]         # '배송', '취소/반품/교환' 등
    intent_type: str               # 'info_search' (규정 조회) vs 'execution' (직접 실행)
    action_name: Optional[str]      # 'refund', 'tracking', 'address_change' 등 구체적 액션
    
    # 4. 거래 및 사용자 컨텍스트
    order_id: Optional[str]
    user_info: Dict[str, Any]
    
    # 5. 액션 제어 및 도구 실행 결과
    action_status: str             # 'idle', 'pending', 'approved', 'completed', 'failed'
    refund_status: Optional[str]   # 'pending_approval', 'approved', 'completed'
    refund_amount: Optional[int]
    tool_outputs: List[Dict[str, Any]]
    
    # 6. 제어 플래그
    is_relevant: bool
    retry_count: int

    # (From remote version - potentially for future use)
    current_intent: Optional[str]
    order_slots: Optional[OrderInfo]
    missing_slot: Optional[str]
