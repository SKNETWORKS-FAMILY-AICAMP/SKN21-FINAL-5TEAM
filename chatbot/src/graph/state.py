from typing import TypedDict, Dict, Any, Optional, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class GlobalAgentState(TypedDict):
    # ---------------------------------------------------------
    # 1. LLM Context State (대화 이력)
    # ---------------------------------------------------------
    # add_messages 리듀서: 동일 ID 메시지 중복 적재 방지 (Tool Call ↔ Tool Result 올바른 매핑 보장)
    messages: Annotated[list[BaseMessage], add_messages]

    # ---------------------------------------------------------
    # 2. System Control & Routing State (작업 큐 관리)
    # ---------------------------------------------------------
    pending_tasks: list[str]            # 실행 대기 중인 작업 식별자 큐 (예: ["REFUND_PROCESS", "POLICY_RAG"])
    completed_tasks: list[str]          # 완료된 작업 목록 (Final Generator 노드에서 참고)
    current_active_task: Optional[str]  # 현재 Supervisor가 Sub-agent에게 할당한 작업

    # ---------------------------------------------------------
    # 3. Business Payload State (노드 간 & 프론트엔드 통신용 데이터)
    # ---------------------------------------------------------
    # 도메인별 페이로드 격리 → Sub-agent 간 Instruction Pollution 방지
    order_context: Dict[str, Any]
    # 예:
    # {
    #   "target_order_id": "ORD-123",
    #   "pending_action": "refund",
    #   "action_status": "waiting_user",
    #   "awaiting_resume_for": "order_selection",
    # }

    search_context: Dict[str, Any]
    # 예: {"search_query": "파티용 하의", "image_url": "https://...", "retrieved_products": []}

    # ---------------------------------------------------------
    # 4. Human-in-the-Loop (HITL) & UI Interaction State
    # ---------------------------------------------------------
    # Sub-agent가 이 플래그를 Overwrite → FastAPI → Next.js UI 컴포넌트 마운트
    ui_action_required: Optional[str]
    # 예: "RENDER_REFUND_LIST", "RENDER_SIZE_SELECTOR", "RENDER_USED_ITEM_FORM"

    # ---------------------------------------------------------
    # 5. User Identity State (인증된 사용자 정보)
    # ---------------------------------------------------------
    user_info: Dict[str, Any]
    # 예: {"id": 1, "name": "홍길동", "email": "user@example.com", "site_id": "site-c", "access_token": "..."}

    # ---------------------------------------------------------
    # 6. LLM Routing State (Provider / Model 선택)
    # ---------------------------------------------------------
    llm_provider: str   # "openai" | "vllm"
    llm_model: str      # 예: "gpt-4o-mini", "Qwen/Qwen2.5-7B-Instruct"

    # ---------------------------------------------------------
    # 7. Agent Results (Final Generator 전용 취합 필드)
    # ---------------------------------------------------------
    # SubAgent들이 messages 를 오염시키지 않고 결과를 기록하는 격리된 공간.
    # Final Generator 는 이 필드만 읽어 최종 응답을 synthesis 한다.
    # 형식: { "ORDER_CS": "취소 완료 요약", "POLICY_RAG": "정책 조회 결과" }
    agent_results: Dict[str, Any]

    # ---------------------------------------------------------
    # 8. Guardrail State
    # ---------------------------------------------------------
    guardrail_passed: bool  # True = 통과, False = 차단 (guardrail_node 기록 → route_after_guardrail 참조)
    use_guardrail: bool     # 제어용: 가드레일 활성화 여부

    # ---------------------------------------------------------
    # 9. Session Metadata
    # ---------------------------------------------------------
    conversation_id: str    # 대화 세션 식별자
    turn_id: str            # 현재 턴 식별자

    # ---------------------------------------------------------
    # 10. Conversation Summary (대화 압축 요약)
    # ---------------------------------------------------------
    # summarize_node가 이전 메시지를 kobart로 요약하여 저장.
    # LLM 컨텍스트 길이 절약 + 멀티턴 기억력 유지.
    # 형식: "사용자가 ORD-123 환불을 요청했고 처리 완료됨. 다음 교환 요청 대기 중."
    conversation_summary: Optional[str]

    # ---------------------------------------------------------
    # 11. Direct Routing (평가 전용 플래그)
    # ---------------------------------------------------------
    # True이면 guardrail/planner/supervisor/order_entry를 건너뛰고
    # order_intent_router로 직행합니다. (order_intent_router 독립 평가용)
    # 운영 모드에서는 항상 False (기본값).
    is_direct_routing: bool
