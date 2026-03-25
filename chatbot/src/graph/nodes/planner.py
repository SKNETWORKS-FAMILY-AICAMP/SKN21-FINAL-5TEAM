"""
Planner 노드.

역할:
  1. 사용자의 최근 메시지를 분석해 서비스 관련 질문인지 판별 (다이어그램의 'sllm 비슷한가?' 체크).
  2. 관련 질문이면 처리해야 할 TaskIntent 목록(pending_tasks)을 순서대로 추출.
  3. 무관한 질문이면 [GENERAL_CHAT] 을 반환 → 워크플로우는 Final Generator로 직행.

출력:
  GlobalAgentState 의 pending_tasks 필드를 갱신.
"""

import re
from typing import cast

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.schemas.planner import PlannerOutput, TaskIntent
from chatbot.src.graph.llm_providers import make_chat_llm, resolve_llm_runtime_policy
from chatbot.src.graph.brand_profiles import resolve_brand_profile

# ── 프롬프트 ──────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """당신은 {brand_store_label} CS 챗봇의 Planner입니다.
사용자의 메시지를 분석하여 처리해야 할 작업 목록을 결정합니다.

[서비스 범위]
{brand_display_name}는 패션 이커머스 플랫폼입니다. 아래 도메인의 질문만 처리합니다:
- 주문 취소 / 반품 / 교환
- 상품 검색 및 스타일 추천 (텍스트 or 이미지)
- 배송/환불/교환 정책 및 약관 조회
- 중고상품 등록, 리뷰 작성, 상품권 등록

[작업 분류 기준]
- ORDER_CS            : "취소해줘", "환불", "반품", "교환", "배송", "송장 조회", "주문 문제", "주문목록 조회" 등 주문과 관련된 모든 CS 요청.
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

PLANNER_LABEL_TEXT_OUTPUT_CONTRACT = """[출력 형식: strict-label-text]
- 반드시 허용된 라벨 이름만 출력하세요.
- 복합 요청은 쉼표로 구분한 한 줄로만 출력하세요.
- 설명, 이유, JSON, 따옴표, 불릿, 자연어 문장을 출력하지 마세요.
- GENERAL_CHAT은 단독으로만 출력할 수 있습니다.

허용된 라벨:
ORDER_CS, SEARCH_SIMILAR_TEXT, SEARCH_SIMILAR_IMAGE, POLICY_RAG,
REGISTER_USED_ITEM, WRITE_REVIEW, REGISTER_GIFT_CARD, GENERAL_CHAT

출력 예시:
ORDER_CS
ORDER_CS, SEARCH_SIMILAR_TEXT
GENERAL_CHAT
"""

PLANNER_LABEL_TEXT_RETRY_PROMPT = """직전 응답이 형식을 위반했습니다.
허용된 라벨만 사용해서 한 줄로 다시 출력하세요.
설명, JSON, 자연어 문장은 금지입니다."""

_TASK_INTENT_VALUES = tuple(intent.value for intent in TaskIntent)
_TASK_INTENT_PATTERN = re.compile(
    "|".join(re.escape(value) for value in sorted(_TASK_INTENT_VALUES, key=len, reverse=True))
)
_WHITESPACE_PATTERN = re.compile(r"\s+")

_GIFT_CARD_RULES: tuple[tuple[str, ...], ...] = (
    ("선물함", "상품권", "코드"),
    ("상품권", "코드", "입력"),
    ("상품권", "코드", "등록"),
    ("모바일 쿠폰", "등록"),
    ("바코드", "등록"),
)
_REVIEW_RULES: tuple[tuple[str, ...], ...] = (
    ("후기",),
    ("리뷰",),
    ("체형", "착용 사진"),
    ("구매자분들", "공유"),
    ("구매자", "공유"),
)
_USED_ITEM_RULES: tuple[tuple[str, ...], ...] = (
    ("넘기고 싶",),
    ("판매하고 싶",),
    ("버리기", "아까"),
    ("정리하려고",),
    ("필요한 분께",),
    ("한꺼번에", "판매"),
)
_POLICY_RULES: tuple[tuple[str, ...], ...] = (
    ("개봉", "반품"),
    ("도서산간", "배송비"),
    ("적립금", "현금처럼"),
    ("적립금", "쓸 수 있"),
    ("영수증 없이",),
    ("가능한지", "궁금"),
    ("불가능한지", "궁금"),
)
_ORDER_CS_RULES: tuple[tuple[str, ...], ...] = (
    ("배송 조회",),
    ("주문 상태",),
    ("배송", "지연"),
    ("언제쯤", "도착"),
    ("배송", "확인해보고"),
)
_DISCOVERY_RULES: tuple[tuple[str, ...], ...] = (
    ("뭘 입을까",),
    ("기본템",),
    ("면접", "옷"),
    ("면접", "룩"),
    ("신뢰감", "옷"),
    ("어떤 스타일",),
)


# ── 노드 함수 ─────────────────────────────────────────────

def planner_node(state: GlobalAgentState) -> dict:
    """
    사용자 메시지를 분석해 pending_tasks 를 결정합니다.
    GlobalAgentState 의 messages 를 읽어 pending_tasks 를 반환합니다.
    """
    provider = state.get("llm_provider", "openai")
    model = state.get("llm_model", "gpt-4o-mini")
    runtime_policy = resolve_llm_runtime_policy(provider=provider, model=model)
    latest_user_message = _get_last_user_message(state.get("messages", []))
    heuristic_pending = _match_high_precision_intent(latest_user_message)
    if heuristic_pending:
        return {"pending_tasks": heuristic_pending}

    llm = make_chat_llm(
        provider=runtime_policy.provider,
        model=runtime_policy.model,
        temperature=0,
    )

    input_messages = _build_planner_messages(
        state,
        include_label_text_contract=(runtime_policy.planner_prompt_variant == "strict-label-text"),
    )

    if runtime_policy.planner_output_mode == "strict-schema":
        pending = _invoke_schema_planner(llm, input_messages)
    else:
        pending = _invoke_label_text_planner(llm, input_messages)

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


def _get_last_user_message(messages: list) -> str | None:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = str(msg.content).strip()
            if content:
                return content
    return None


def _build_planner_messages(
    state: GlobalAgentState,
    *,
    include_label_text_contract: bool,
) -> list:
    conversation_summary: str | None = state.get("conversation_summary")
    brand_profile = resolve_brand_profile((state.get("user_info") or {}).get("site_id"))
    summary_prefix = (
        f"\n\n[이전 대화 요약]\n{conversation_summary}\n"
        if conversation_summary else ""
    )
    system_content = PLANNER_SYSTEM_PROMPT.format(
        brand_store_label=brand_profile.store_label,
        brand_display_name=brand_profile.display_name,
    ) + summary_prefix
    if include_label_text_contract:
        system_content += f"\n\n{PLANNER_LABEL_TEXT_OUTPUT_CONTRACT}"

    latest_user_message = _get_last_user_message(state.get("messages", []))
    input_messages = [SystemMessage(content=system_content)]
    if latest_user_message:
        input_messages.append(HumanMessage(content=latest_user_message))
    return input_messages


def _match_high_precision_intent(message: str | None) -> list[str] | None:
    if not message:
        return None

    normalized = _normalize_message(message)

    if _matches_any_rule(normalized, _GIFT_CARD_RULES):
        return [TaskIntent.REGISTER_GIFT_CARD]
    if _matches_any_rule(normalized, _REVIEW_RULES):
        return [TaskIntent.WRITE_REVIEW]
    if _matches_any_rule(normalized, _USED_ITEM_RULES):
        return [TaskIntent.REGISTER_USED_ITEM]
    if _matches_policy_rule(normalized):
        return [TaskIntent.POLICY_RAG]
    if _matches_any_rule(normalized, _ORDER_CS_RULES):
        return [TaskIntent.ORDER_CS]
    if _matches_discovery_rule(normalized):
        return [TaskIntent.SEARCH_SIMILAR_TEXT]

    return None


def _normalize_message(message: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", message.casefold()).strip()


def _matches_any_rule(message: str, rules: tuple[tuple[str, ...], ...]) -> bool:
    return any(all(token in message for token in rule) for rule in rules)


def _matches_policy_rule(message: str) -> bool:
    if _matches_any_rule(message, _POLICY_RULES):
        return True

    return (
        ("배송비" in message and "얼마" in message)
        or ("반품" in message and any(token in message for token in ("가능", "불가능", "규정", "절차")))
    )


def _matches_discovery_rule(message: str) -> bool:
    if _matches_any_rule(message, _DISCOVERY_RULES):
        return True

    return (
        ("옷" in message and any(token in message for token in ("추천", "코디", "기본템", "입을까")))
        or ("신뢰감" in message and any(token in message for token in ("줄 수 있", "주고 싶")))
    )


def _invoke_schema_planner(llm, input_messages: list) -> list[str]:
    try:
        structured_llm = llm.with_structured_output(PlannerOutput)
        result = cast(PlannerOutput, structured_llm.invoke(input_messages))
        return [t.value for t in result.pending_tasks]
    except (ValidationError, Exception):
        return [TaskIntent.GENERAL_CHAT]


def _invoke_label_text_planner(llm, input_messages: list) -> list[str]:
    pending = _parse_label_text_output(_extract_response_text(llm.invoke(input_messages)))
    if pending:
        return pending

    retry_messages = [
        *input_messages,
        AIMessage(content="형식 위반 응답"),
        HumanMessage(content=PLANNER_LABEL_TEXT_RETRY_PROMPT),
    ]
    retry_pending = _parse_label_text_output(_extract_response_text(llm.invoke(retry_messages)))
    if retry_pending:
        return retry_pending

    return [TaskIntent.GENERAL_CHAT]


def _extract_response_text(response) -> str:
    content = getattr(response, "content", response)
    return str(content).strip()


def _parse_label_text_output(text: str) -> list[str]:
    if not text:
        return []

    found: list[str] = []
    for match in _TASK_INTENT_PATTERN.finditer(text.upper()):
        label = match.group(0)
        if label not in found:
            found.append(label)

    if not found:
        return []
    if TaskIntent.GENERAL_CHAT in found and len(found) > 1:
        return []
    return found
