"""
Final Generator 노드.

역할:
  - SubAgent들이 agent_results 에 남긴 결과를 읽어 하나의 최종 응답으로 synthesis.
  - DB 조회, API 호출 등 어떤 외부 액션도 수행하지 않음.
  - 오직 데이터 취합(Synthesis) + 사용자 친화적 포맷팅(Formatting) 만 담당.

분기 로직:
  - completed_tasks 없음  → GENERAL_CHAT 직접 응답 (LLM 자유 응답)
  - completed_tasks 1개   → agent_results 의 해당 결과 그대로 반환 (추가 LLM 호출 없음)
  - completed_tasks 2개+  → LLM 이 agent_results 를 통합 요약 (synthesis)
"""

from langchain_core.messages import SystemMessage, AIMessage

from chatbot.src.graph.brand_profiles import resolve_brand_profile
from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.graph.llm_providers import make_chat_llm
from chatbot.src.schemas.planner import TaskIntent

# ── 프롬프트 ──────────────────────────────────────────────

GENERAL_CHAT_SYSTEM_PROMPT = """당신은 {brand_store_label}의 AI CS 상담원입니다.
서비스와 무관한 일반적인 질문에도 친절하고 자연스럽게 응답하세요.
항상 존댓말을 사용하고, 간결하게 답변하세요.
쇼핑 관련 도움이 필요하면 언제든 말씀해 달라고 안내해 주세요."""

SYNTHESIS_SYSTEM_PROMPT = """당신은 {brand_store_label}의 AI CS 상담원입니다.
아래 [처리 결과]는 각 SubAgent가 처리한 결과를 요약한 것입니다.
이 내용을 바탕으로 하나의 자연스럽고 매끄러운 응답을 작성하세요.

[엄격한 규칙]
1. [처리 결과] 에 없는 내용은 절대 추가하지 마세요.
2. 항상 존댓말을 사용하세요.
3. 여러 작업 결과를 자연스럽게 연결하되, 각 내용의 핵심은 반드시 포함하세요.
4. UI 안내 문구가 필요한 경우({ui_instruction}) 응답 끝에 반드시 포함하세요.

[처리 결과]
{agent_results_text}
"""

# UI 액션 → 사용자 안내 문구 매핑
_UI_ACTION_INSTRUCTIONS: dict[str, str] = {
    "show_order_list":      "아래 주문 목록에서 원하시는 주문을 선택해 주세요.",
    "show_option_list":     "아래 옵션 목록에서 변경하실 옵션을 선택해 주세요.",
    "show_address_search":  "아래 주소 검색 버튼을 눌러 수거지 주소를 입력해 주세요.",
    "show_review_form":     "아래 리뷰 작성 폼에서 평점과 내용을 입력해 주세요.",
    "show_used_sale_form":  "아래 폼에서 중고 상품 정보를 입력해 주세요.",
}

_TASK_HEADERS: dict[str, str] = {
    TaskIntent.POLICY_RAG.value: "문의하신 정책 안내입니다.",
    TaskIntent.SEARCH_SIMILAR_TEXT.value: "요청하신 상품 탐색 결과입니다.",
    TaskIntent.SEARCH_SIMILAR_IMAGE.value: "요청하신 상품 탐색 결과입니다.",
    TaskIntent.REGISTER_USED_ITEM.value: "중고 상품 등록 안내입니다.",
    TaskIntent.WRITE_REVIEW.value: "리뷰 작성 안내입니다.",
    TaskIntent.REGISTER_GIFT_CARD.value: "상품권 등록 결과입니다.",
}

_ORDER_ACTION_LABELS: dict[str, str] = {
    "cancel": "주문 취소",
    "refund": "환불",
    "exchange": "교환",
    "shipping": "배송 조회",
    "list_orders": "주문 조회",
    "change_option": "옵션 변경",
}

_ORDER_STATUS_LABELS: dict[str, str] = {
    "cancelled": "취소 완료",
    "exchange_requested": "교환 신청 접수",
    "updated": "옵션 변경 완료",
    "refunded (return requested)": "반품 환불 접수",
    "refund_requested": "환불 접수",
    "no_change": "변경 사항 없음",
    "failed": "처리 실패",
    "completed": "처리 완료",
}

# ── 노드 함수 ─────────────────────────────────────────────

def final_generator_node(state: GlobalAgentState) -> dict:
    """
    최종 응답 생성 노드.
    agent_results 를 읽어 completed_tasks 수에 따라 분기 처리합니다.
    """
    provider = state.get("llm_provider", "openai")
    model = state.get("llm_model", "gpt-4o-mini")
    completed_tasks: list[str] = state.get("completed_tasks", [])
    agent_results: dict = state.get("agent_results", {})
    ui_action: str | None = state.get("ui_action_required")

    # UI 액션 대기 상태에서는 텍스트를 생성하지 않고 UI 이벤트만 전달
    if ui_action:
        # UI 이벤트 우선순위가 있으므로 어떤 텍스트도 생성하지 않고 플래그만 유지합니다.
        return {"ui_action_required": ui_action, "messages": []}

    # ── Case 1. 작업 없음 → GENERAL_CHAT 직접 응답 ────────
    if not completed_tasks:
        order_result = str(agent_results.get("ORDER_CS", "")).strip()
        if order_result:
            return {"messages": [AIMessage(content=_format_single_task_result(state, TaskIntent.ORDER_CS, order_result))]}
        return _general_chat_response(state, provider, model)

    # ── Case 2. 단일 작업 → formatter를 거쳐 반환 ────────
    if len(completed_tasks) == 1:
        task = completed_tasks[0]
        result_text = agent_results.get(task, "").strip()

        if result_text:
            return {"messages": [AIMessage(content=_format_single_task_result(state, task, result_text))]}

        # agent_results 가 비어있는 경우 GENERAL_CHAT으로 fallback
        return _general_chat_response(state, provider, model)

    # ── Case 3. 복합 작업 → LLM synthesis ─────────────────
    return _synthesis_response(state, provider, model, completed_tasks, agent_results, ui_action)


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _general_chat_response(state: GlobalAgentState, provider: str, model: str) -> dict:
    """서비스 무관 질문 또는 fallback 시 LLM 자유 응답 생성."""
    brand_profile = resolve_brand_profile((state.get("user_info") or {}).get("site_id"))
    llm = make_chat_llm(provider=provider, model=model, temperature=0.3)
    response = llm.invoke([
        SystemMessage(
            content=GENERAL_CHAT_SYSTEM_PROMPT.format(
                brand_store_label=brand_profile.store_label,
            )
        ),
        *state["messages"],
    ])
    return {"messages": [AIMessage(content=response.content)]}


def _format_single_task_result(state: GlobalAgentState, task: str, result_text: str) -> str:
    normalized_text = str(result_text or "").strip()
    if not normalized_text:
        return ""

    task_key = task.value if isinstance(task, TaskIntent) else str(task)

    if task_key == TaskIntent.ORDER_CS.value:
        return _format_order_cs_result(state, normalized_text)

    header = _TASK_HEADERS.get(task_key, "")
    if header:
        return f"{header}\n\n{normalized_text}"
    return normalized_text


def _format_order_cs_result(state: GlobalAgentState, result_text: str) -> str:
    order_context = state.get("order_context", {})
    action = str(order_context.get("pending_action") or "").strip().lower()
    action_label = _ORDER_ACTION_LABELS.get(action, "주문")
    order_id = str(order_context.get("target_order_id") or "").strip()
    status = _format_order_status(order_context)

    lines = [f"요청하신 {action_label} 처리 결과입니다."]
    if order_id:
        lines.append(f"주문번호: {order_id}")
    if status:
        lines.append(f"처리 상태: {status}")
    lines.append(result_text)
    return "\n".join(lines)


def _format_order_status(order_context: dict) -> str:
    raw_status = str(
        order_context.get("last_action_status")
        or order_context.get("action_status")
        or ""
    ).strip().lower()
    if not raw_status:
        return ""
    return _ORDER_STATUS_LABELS.get(raw_status, raw_status)


def _synthesis_response(
    state: GlobalAgentState,
    provider: str,
    model: str,
    completed_tasks: list[str],
    agent_results: dict,
    ui_action: str | None,
) -> dict:
    """복합 작업 결과를 LLM 이 하나의 응답으로 통합."""

    # agent_results 를 보기 좋은 텍스트 블록으로 변환
    result_blocks = []
    for task in completed_tasks:
        content = agent_results.get(task, "").strip()
        if content:
            result_blocks.append(f"[{task}]\n{content}")

    agent_results_text = "\n\n".join(result_blocks) if result_blocks else "처리 결과 없음"

    # UI 안내 문구
    ui_instruction = _UI_ACTION_INSTRUCTIONS.get(ui_action or "", "")
    brand_profile = resolve_brand_profile((state.get("user_info") or {}).get("site_id"))

    llm = make_chat_llm(provider=provider, model=model, temperature=0)
    response = llm.invoke([
        SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT.format(
            brand_store_label=brand_profile.store_label,
            agent_results_text=agent_results_text,
            ui_instruction=ui_instruction,
        )),
        # 사용자의 원래 질문을 함께 전달해 context 유지
        *state["messages"],
    ])

    return {"messages": [AIMessage(content=response.content)]}
