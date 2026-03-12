"""
Planner 노드.

역할:
  1. 사용자의 최근 메시지를 분석해 서비스 관련 질문인지 판별 (다이어그램의 'sllm 비슷한가?' 체크).
  2. 관련 질문이면 처리해야 할 TaskIntent 목록(pending_tasks)을 순서대로 추출.
  3. 무관한 질문이면 [GENERAL_CHAT] 을 반환 → 워크플로우는 Final Generator로 직행.

출력:
  GlobalAgentState 의 pending_tasks 필드를 갱신.
"""

from typing import cast

from langchain_core.messages import SystemMessage
from pydantic import ValidationError

from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.schemas.planner import PlannerOutput, TaskIntent
from chatbot.src.graph.llm_providers import make_chat_llm

# ── 프롬프트 ──────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """당신은 MOYEO 쇼핑몰 CS 챗봇의 Planner입니다.
사용자의 메시지를 분석하여 처리해야 할 작업 목록을 결정합니다.

[서비스 범위]
MOYEO는 패션 이커머스 플랫폼입니다. 아래 도메인의 질문만 처리합니다:
- 주문 취소 / 반품 / 교환
- 상품 검색 및 스타일 추천 (텍스트 or 이미지)
- 배송/환불/교환 정책 및 약관 조회
- 중고상품 등록, 리뷰 작성, 상품권 등록

[작업 분류 기준]
- ORDER_CS            : "취소해줘", "환불", "반품", "교환", "주문 문제", "주문목록 조회" 등 주문과 관련된 모든 CS 요청.
                        취소/반품/교환의 구체적 구분은 하지 않는다. DB 기반 판단은 RefundSubAgent가 처리.
- SEARCH_SIMILAR_TEXT : "이런 옷 찾아줘", "~스타일 추천", 텍스트 기반 상품 탐색
- SEARCH_SIMILAR_IMAGE: "이 사진이랑 비슷한 거" 같은 이미지 기반 검색.
                        현재 턴에 URL이 없더라도 직전 턴에 업로드된 이미지를 참조하는 표현(예: "이 이미지", "방금 올린 사진")이면 포함.
- POLICY_RAG          : "환불 규정", 정책/약관 질문
- REGISTER_USED_ITEM  : "중고 팔고 싶어요", "중고 등록"
- WRITE_REVIEW        : "리뷰 쓰고 싶어요", "후기 작성"
- REGISTER_GIFT_CARD  : "상품권 등록", "쿠폰 코드"
- GENERAL_CHAT        : 위 어디에도 해당하지 않는 무관한 질문

[출력 규칙]
- 복합 요청(예: "취소하고 비슷한 상품도 찾아줘")은 여러 TaskIntent를 순서대로 나열.
- 서비스와 완전히 무관한 질문(날씨, 정치, 코딩 등)은 반드시 [GENERAL_CHAT] 만 반환.
- 절대 추측하지 말고, 메시지에 명시된 의도만 추출.
"""


# ── 노드 함수 ─────────────────────────────────────────────

def planner_node(state: GlobalAgentState) -> dict:
    """
    사용자 메시지를 분석해 pending_tasks 를 결정합니다.
    GlobalAgentState 의 messages 를 읽어 pending_tasks 를 반환합니다.
    """
    provider = state.get("llm_provider", "openai")
    model = state.get("llm_model", "gpt-4o-mini")

    llm = make_chat_llm(provider=provider, model=model, temperature=0)
    structured_llm = llm.with_structured_output(PlannerOutput)

    # 이전 대화 요약이 있으면 시스템 프롬프트 앞에 주입
    conversation_summary: str | None = state.get("conversation_summary")
    summary_prefix = (
        f"\n\n[이전 대화 요약]\n{conversation_summary}\n"
        if conversation_summary else ""
    )
    system_content = PLANNER_SYSTEM_PROMPT + summary_prefix

    # 시스템 프롬프트 + 현재까지의 대화 이력 전달
    input_messages = [SystemMessage(content=system_content)] + list(state["messages"])

    try:
        result = cast(PlannerOutput, structured_llm.invoke(input_messages))
        pending = [t.value for t in result.pending_tasks]
    except (ValidationError, Exception):
        # LLM이 빈 배열 또는 스키마 위반 반환 시 → GENERAL_CHAT으로 안전하게 fallback
        pending = [TaskIntent.GENERAL_CHAT]

    return {"pending_tasks": pending}


# ── 라우팅 조건 함수 ──────────────────────────────────────

def route_after_planner(state: GlobalAgentState) -> str:
    """
    Planner 실행 후 다음 노드를 결정하는 조건 함수.

    - pending_tasks 가 [GENERAL_CHAT] 이면 → "final_generator" (직접 종료 응답)
    - 그 외 실행할 작업이 있으면     → "supervisor"
    """
    tasks = state.get("pending_tasks", [])

    if not tasks or tasks == [TaskIntent.GENERAL_CHAT]:
        return "final_generator"

    return "supervisor"
