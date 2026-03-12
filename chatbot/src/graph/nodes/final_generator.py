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

from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.graph.llm_providers import make_chat_llm

# ── 프롬프트 ──────────────────────────────────────────────

GENERAL_CHAT_SYSTEM_PROMPT = """당신은 MOYEO 쇼핑몰의 AI CS 상담원입니다.
서비스와 무관한 일반적인 질문에도 친절하고 자연스럽게 응답하세요.
항상 존댓말을 사용하고, 간결하게 답변하세요.
쇼핑 관련 도움이 필요하면 언제든 말씀해 달라고 안내해 주세요."""

SYNTHESIS_SYSTEM_PROMPT = """당신은 MOYEO 쇼핑몰의 AI CS 상담원입니다.
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
    "show_address_search":  "아래 주소 검색 버튼을 눌러 수거지 주소를 입력해 주세요.",
    "show_review_form":     "아래 리뷰 작성 폼에서 평점과 내용을 입력해 주세요.",
    "show_used_sale_form":  "아래 폼에서 중고 상품 정보를 입력해 주세요.",
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
        return {}

    # ── Case 1. 작업 없음 → GENERAL_CHAT 직접 응답 ────────
    if not completed_tasks:
        return _general_chat_response(state, provider, model)

    # ── Case 2. 단일 작업 → agent_results 결과 그대로 반환 ─
    if len(completed_tasks) == 1:
        task = completed_tasks[0]
        result_text = agent_results.get(task, "").strip()

        # ui_action 안내 문구 추가
        ui_instruction = _UI_ACTION_INSTRUCTIONS.get(ui_action or "", "")
        if ui_instruction:
            result_text = f"{result_text}\n\n{ui_instruction}" if result_text else ui_instruction

        if result_text:
            return {"messages": [AIMessage(content=result_text)]}

        # agent_results 가 비어있는 경우 GENERAL_CHAT으로 fallback
        return _general_chat_response(state, provider, model)

    # ── Case 3. 복합 작업 → LLM synthesis ─────────────────
    return _synthesis_response(state, provider, model, completed_tasks, agent_results, ui_action)


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _general_chat_response(state: GlobalAgentState, provider: str, model: str) -> dict:
    """서비스 무관 질문 또는 fallback 시 LLM 자유 응답 생성."""
    llm = make_chat_llm(provider=provider, model=model, temperature=0.3)
    response = llm.invoke([
        SystemMessage(content=GENERAL_CHAT_SYSTEM_PROMPT),
        *state["messages"],
    ])
    return {"messages": [AIMessage(content=response.content)]}


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

    llm = make_chat_llm(provider=provider, model=model, temperature=0)
    response = llm.invoke([
        SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT.format(
            agent_results_text=agent_results_text,
            ui_instruction=ui_instruction,
        )),
        # 사용자의 원래 질문을 함께 전달해 context 유지
        *state["messages"],
    ])

    return {"messages": [AIMessage(content=response.content)]}
