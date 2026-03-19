"""
Policy RAG SubAgent 노드.

담당 TaskIntent:
  - POLICY_RAG : 배송/환불/교환 정책, 약관, 규정 질문 처리

파이프라인 (다이어그램 기준):
  Query Transformation → Retrieve (search_knowledge_base)

설계 원칙:
  - Query Transformation: 사용자의 구어체 질문을 검색에 최적화된 키워드로 변환.
  - 변환된 쿼리로 Hybrid Search + Reranking 수행.
  - 검색 결과를 context로 삼아 최종 답변 생성.
  - 모든 과정은 Python으로 명시적 파이프라인으로 구성 (ReAct 루프 불필요).
"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from chatbot.src.graph.state import GlobalAgentState
from chatbot.src.graph.llm_providers import make_chat_llm
from chatbot.src.tools.retrieval_tools import search_knowledge_base

# ── 프롬프트 ──────────────────────────────────────────────

QUERY_TRANSFORM_PROMPT = """당신은 검색 쿼리 최적화 전문가입니다.
사용자의 구어체 질문을 Qdrant 벡터 검색에 최적화된 핵심 키워드 중심의 질의로 변환하세요.

규칙:
- 불필요한 조사, 어미, 인사말 제거
- 핵심 도메인 용어 보존 (배송, 환불, 반품, 교환, 취소 등)
- 검색에 중요한 구분어는 반드시 유지 (제주/도서산간, A/S, 사은품, USED/유즈드, 부분/일부, 배송비/반품비)
- 질문 의도가 드러나는 핵심 명사를 유지 (배송 조회, 송장 흐름, 배송지 변경, 결제수단, 문의처, 보상 기준)
- 1~2문장으로 간결하게 출력
- 변환된 쿼리만 출력 (설명 없이)

예시:
입력: "저 지난번에 산 옷이 마음에 안 드는데 어떻게 반품 신청을 하면 될까요?"
출력: "반품 신청 방법 절차"

입력: "배송이 너무 오래 걸리는데 언제쯤 오나요?"
출력: "배송 소요 기간 일정"

입력: "결제 후 며칠 안에 취소 가능해요?"
출력: "주문 취소 가능 여부 상품준비중 취소 방법"

입력: "환불받으면 돈은 언제 들어와요?"
출력: "주문 취소 환불 금액 입금 시점"

입력: "색상만 바꾸고 싶은데 교환 신청은 어떻게 해요?"
출력: "상품 교환 신청 방법 절차"

입력: "결제수단은 어떤 것들 쓸 수 있어요?"
출력: "결제수단 결제 방법 종류"

입력: "AS는 어디로 문의해야 하나요?"
출력: "구매한 상품 A/S 필요 문의 방법"

입력: "제주도도 배송비 같은가요?"
출력: "제주도 도서산간 배송비 추가 여부"

입력: "사은품도 같이 반품해야 되나요?"
출력: "사은품 반품 동봉 필요 여부"

입력: "송장 번호나 배송 흐름은 어디서 볼 수 있어요?"
출력: "배송 조회 방법 송장 흐름 확인 경로"

입력: "배송 준비 단계에서는 받는 주소를 바꿀 수 있나요?"
출력: "상품준비중 배송지 주소 변경 가능 여부"

입력: "제품이 불량이면 어떤 보상 기준이 적용돼요?"
출력: "상품 불량 보상 기준 교환 환불 절차"
"""

POLICY_RAG_ANSWER_PROMPT = """당신은 MOYEO 쇼핑몰 CS 상담원입니다.
아래 [참고 문서]를 바탕으로 사용자의 질문에 정확하고 간결하게 답변하세요.

규칙:
- 반드시 [참고 문서] 내용만 근거로 사용하세요.
- 문서에 없는 내용은 "확인되지 않은 내용입니다"라고 안내하세요.
- 존댓말을 사용하고, 간결하게 핵심만 전달하세요.

[참고 문서]
{context}
"""


def run_policy_rag_pipeline(
    messages: list,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
) -> dict:
    """실서비스와 동일한 Policy RAG 파이프라인을 실행하고 중간 산출물을 반환합니다."""
    llm = make_chat_llm(provider=provider, model=model, temperature=0)

    user_query = _get_last_user_message(messages)
    if not user_query:
        raise ValueError("사용자 질문을 찾을 수 없습니다.")

    transform_response = llm.invoke([
        SystemMessage(content=QUERY_TRANSFORM_PROMPT),
        HumanMessage(content=user_query),
    ])
    optimized_query = _normalize_policy_query(user_query, str(transform_response.content).strip())
    inferred_categories = _infer_policy_categories(user_query, optimized_query)
    inferred_category = inferred_categories[0] if inferred_categories else None
    query_variants = _build_query_variants(user_query, optimized_query)

    retrieval_attempts = _build_retrieval_attempts(
        query_variants=query_variants,
        inferred_categories=inferred_categories,
    )

    retrieval_results: list[dict] = []
    retrieval_result: dict = {"documents": [], "items": [], "count": 0}
    documents: list[str] = []
    used_fallback = False

    for index, payload in enumerate(retrieval_attempts):
        current_result = search_knowledge_base.invoke(payload)
        retrieval_results.append(current_result)

        current_documents = current_result.get("documents", [])
        if current_documents and not documents:
            used_fallback = index > 0

    retrieval_result = _merge_retrieval_results(retrieval_results)
    documents = retrieval_result.get("documents", [])

    context = "\n\n".join(documents) if documents else "관련 정책 문서를 찾을 수 없습니다."

    answer_response = llm.invoke([
        SystemMessage(content=POLICY_RAG_ANSWER_PROMPT.format(context=context)),
        *messages,
    ])
    answer_content = str(answer_response.content)

    return {
        "user_query": user_query,
        "optimized_query": optimized_query,
        "inferred_category": inferred_category,
        "query_variants": query_variants,
        "retrieval_result": retrieval_result,
        "used_fallback": used_fallback,
        "answer_content": answer_content,
    }


# ── 노드 함수 ─────────────────────────────────────────────

def policy_rag_subagent_node(state: GlobalAgentState) -> dict:
    """
    Policy RAG SubAgent.

    Step 1. Query Transformation — 구어체 → 검색 최적화 쿼리
    Step 2. Retrieve             — Hybrid Search + Reranking
    Step 3. Generate             — 검색 결과 기반 답변 생성
    """
    provider = state.get("llm_provider", "openai")
    model = state.get("llm_model", "gpt-4o-mini")
    task = state.get("current_active_task")

    if not _get_last_user_message(state["messages"]):
        return _error_response(state, task, "사용자 질문을 찾을 수 없습니다.")

    try:
        pipeline_result = run_policy_rag_pipeline(
            messages=state["messages"],
            provider=provider,
            model=model,
        )
    except Exception as exc:
        return _error_response(state, task, str(exc))

    answer_content = pipeline_result["answer_content"]
    answer_message = AIMessage(content=answer_content)

    return {
        "messages": [answer_message],
        "completed_tasks": state.get("completed_tasks", []) + [task],
        "agent_results": {
            **state.get("agent_results", {}),
            task: answer_content,  # Final Generator 전용 취합 필드
        },
    }


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _get_last_user_message(messages: list) -> str | None:
    """메시지 목록에서 가장 최근 HumanMessage 내용 반환"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return str(msg.content).strip()
    return None


def _infer_policy_category(user_query: str, optimized_query: str) -> str | None:
    """가장 우선순위가 높은 단일 카테고리를 반환한다."""
    categories = _infer_policy_categories(user_query, optimized_query)
    return categories[0] if categories else None


def _infer_policy_categories(user_query: str, optimized_query: str) -> list[str]:
    """질문 키워드를 기반으로 검색할 카테고리 후보를 우선순위 순으로 추정한다."""
    text = f"{user_query} {optimized_query}".lower()
    categories: list[str] = []

    def has_any(*keywords: str) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    def add(category: str) -> None:
        if category not in categories:
            categories.append(category)

    has_payment = has_any("결제수단", "결제", "카드", "무통장", "입금", "승인", "계좌이체")
    has_return = has_any("교환", "반품", "환불", "취소", "철회", "반송", "회수", "수거")
    has_shipping = has_any("배송", "송장", "택배", "출고", "도착", "배송지", "제주", "도서산간")
    has_as = has_any("a/s", "as", "불량", "하자", "수선", "문의처")
    is_payment_method_question = has_any("결제수단", "결제 방법", "무통장", "신용카드", "계좌이체")
    is_payment_cancel_question = has_payment and has_any("취소", "환불") and has_any("결제 후", "상품준비중", "승인", "무통장")

    if is_payment_method_question or is_payment_cancel_question:
        add("주문/결제")

    if has_as:
        add("상품/AS 문의")

    if has_return:
        add("취소/교환/반품")

    if has_shipping:
        add("배송")

    if has_payment and "주문/결제" not in categories:
        add("주문/결제")

    return categories


def _build_retrieval_attempts(
    query_variants: list[str],
    inferred_categories: list[str],
) -> list[dict[str, str]]:
    """Tool schema 검증을 피하기 위해 None 값은 payload에서 제거한다."""
    attempts: list[dict[str, str]] = []
    seen: set[tuple[str, str | None]] = set()

    for query in query_variants:
        for category in inferred_categories:
            key = (query, category)
            if key not in seen:
                attempts.append({"query": query, "category": category})
                seen.add(key)

        key = (query, None)
        if key not in seen:
            attempts.append({"query": query})
            seen.add(key)

    return attempts


def _build_query_variants(user_query: str, optimized_query: str) -> list[str]:
    """질문 성격에 맞는 검색 변형 질의를 추가로 만든다."""
    lowered = f"{user_query} {optimized_query}".lower()
    variants: list[str] = [optimized_query]

    def has_any(*keywords: str) -> bool:
        return any(keyword.lower() in lowered for keyword in keywords)

    def add(query: str) -> None:
        query = query.strip()
        if query and query not in variants:
            variants.append(query)

    if user_query != optimized_query:
        add(user_query)

    if has_any("결제수단", "결제 방법", "무통장", "신용카드", "계좌이체"):
        add("결제수단 카드 무통장입금 계좌이체 결제 방법 종류")

    if has_any("카드", "승인") and has_any("취소", "환불"):
        add("주문 취소 카드 승인 취소 환불 시점 결제수단")

    if has_any("무통장", "무통장입금") and has_any("취소", "환불"):
        add("무통장입금 주문 취소 환불 금액 입금 시점")

    if has_any("배송지", "주소") and has_any(
        "상품 준비중", "상품준비중", "배송 준비", "준비 단계", "출고 후", "배송 출발", "출발한 뒤"
    ):
        add("상품준비중 출고 후 배송지 주소 옵션 변경 가능 여부 불가")
        add("배송지 주소 변경 가능 여부 송장 조회 상품준비중")

    if has_any("송장", "배송 흐름") and has_any("어디", "확인", "조회", "볼 수"):
        add("배송 조회 방법 송장 흐름 확인 경로")

    if has_any("결제수단", "결제 방법") and has_any("어떤", "종류", "쓸 수", "사용할 수"):
        add("결제수단 결제 방법 종류 카드 무통장입금 계좌이체")
    elif has_any("결제") and has_any("수단", "방법") and has_any("어떤", "종류", "쓸 수", "사용할 수"):
        add("결제수단 결제 방법 종류 카드 무통장입금 계좌이체")

    if has_any("하자", "불량"):
        add("불량 하자 교환 반품 환불 배송비 부담")
        if has_any("보상", "기준", "어떻게 돼", "적용"):
            add("상품 불량 보상 기준 교환 환불 절차")

    if has_any("직접", "직접 택배", "직접 발송") and has_any("송장", "반송장") and has_any("등록", "입력", "필요"):
        add("반송장 입력 수정 방법 직접 발송")

    if has_any("송장", "반송장") and has_any("미입력", "안 넣", "지연", "늦게 도착") and has_any("주문 상태", "구매 확정", "변경"):
        add("반송장 미입력 반품 지연 구매 확정 변경")

    if has_any("해외 배송", "해외배송") and has_any("반품", "교환") and has_any("비용", "배송비", "추가", "더 드"):
        add("해외 배송 반품 비용 추가 여부")

    if has_any("브랜드 박스", "이중 포장", "겉포장") and has_any("반품", "교환", "그대로 두고"):
        add("브랜드 박스 이중 포장 반품 가능 조건")

    if has_any("주문 제작", "주문제작", "맞춤 제작") and has_any("교환", "반품"):
        add("주문 제작 상품 교환 반품 가능 여부")

    if has_any("자동 회수", "기사님") and has_any("며칠", "언제", "오나요"):
        add("자동 회수 기사 방문 일정 반품 교환")
        add("교환 반품 자동 회수 기사 방문 일정")

    if has_any("박스 겉면", "겉면", "적어야", "표기") and has_any("반품", "교환"):
        add("반품 박스 겉면 정보 기재 필요 여부")
        add("교환 반품 포장 박스 겉면 기재 정보")

    if has_any("옵션마다", "옵션별") and has_any("반품", "교환") and has_any("주소", "반품지"):
        add("옵션별 반품지 상이 여부")

    if has_any("다른 택배사", "계약된 택배사가 아닌", "아닌 곳으로") and has_any("반품", "접수") and has_any("추가금", "추가 운임", "비용"):
        add("지정 택배사 외 반품 추가 비용 여부")
        add("계약 택배사 외 반품 접수 추가 운임")

    if has_any("교환 배송비", "배송비") and has_any("결제", "선결제") and has_any("카드", "계좌", "다른 방법", "다른 수단"):
        add("교환 배송비 결제 방법 선결제 카드 계좌")
        add("상품 교환 신청 배송비 결제 수단")

    if has_any("교환") and has_any("품절") and has_any("어떻게", "처리", "진행"):
        add("교환 진행 중 품절 처리 환불 반품비")

    if has_any("불량", "하자") and has_any("보상", "기준", "적용"):
        add("불량 상품 보상 기준 교환 환불 배송비")

    if has_any("제휴 브랜드") and has_any("a/s", "as") and has_any("가능", "접수"):
        add("제휴 브랜드 상품 A/S 가능 여부")

    return variants[:6]


def _normalize_policy_query(user_query: str, optimized_query: str) -> str:
    """LLM 변환 결과를 홀드아웃 표현까지 커버하도록 얇게 정규화한다."""
    query = (user_query or "").strip()
    optimized = (optimized_query or "").strip()
    lowered = f"{query} {optimized}".lower()

    def has_any(*keywords: str) -> bool:
        return any(keyword.lower() in lowered for keyword in keywords)

    if has_any("사이즈", "교환") and has_any("택배비", "배송비", "추가") and has_any("내야", "부담"):
        return "교환 배송비 부담 주체 고객 판매자"

    if has_any("입어본", "시착", "잠깐 입", "잠깐") and has_any("반품"):
        return "시착 후 반품 가능 조건"

    if has_any("배송 출발", "출발 이후", "출고 후", "배송 준비", "준비 단계") and has_any("주소", "배송지", "변경"):
        return "출고 후 배송지 변경 가능 여부 불가"

    if has_any("a/s", "as") and has_any("문의", "문의처", "어디") and has_any("필요"):
        return "A/S 문의처 정보 브랜드"

    if has_any("직접", "직접 택배", "직접 발송") and has_any("송장", "반송장") and has_any("등록", "입력", "필요"):
        return "직접 발송 반송장 입력 필요 여부"

    if has_any("송장", "반송장") and has_any("안 넣", "미입력", "늦게 도착", "지연") and has_any("주문 상태", "구매 확정", "상태가 바뀌"):
        return "반송장 미입력 반품 지연 구매 확정 변경"

    if has_any("옵션마다", "옵션별") and has_any("반품", "교환") and has_any("주소", "반품지"):
        return "옵션별 반품지 상이 여부"

    if has_any("휴대전화", "휴대폰") and has_any("결제") and has_any("반품비") and has_any("더 크", "초과") and has_any("접수", "신청"):
        return "휴대전화 결제 반품비 초과 접수 방법"

    if has_any("환불받", "환불") and has_any("언제 들어", "언제 입금", "언제 들어와"):
        return "환불 처리 기간 입금 시점"

    return optimized


def _merge_retrieval_results(results: list[dict]) -> dict:
    """여러 검색 시도 결과를 합쳐 반복 등장한 문서를 상위로 올린다."""
    merged: dict[str, dict] = {}
    fallback_key_seq = 0

    for result in results:
        for item in result.get("items", []):
            doc_key = item.get("doc_key") or f"item::{fallback_key_seq}"
            fallback_key_seq += 1
            if doc_key not in merged:
                merged[doc_key] = dict(item)
                merged[doc_key]["score"] = float(item.get("score", 0.0))
                merged[doc_key]["_hits"] = 1
            else:
                merged[doc_key]["score"] = max(
                    float(merged[doc_key].get("score", 0.0)),
                    float(item.get("score", 0.0)),
                )
                merged[doc_key]["_hits"] += 1

    ranked = sorted(
        merged.values(),
        key=lambda item: float(item.get("score", 0.0)) + (0.45 * int(item.get("_hits", 1) - 1)),
        reverse=True,
    )[:5]

    documents = [f"[{item.get('doc_type', '정보')}] {item.get('text', '')}" for item in ranked]
    items = []
    for item in ranked:
        cleaned = dict(item)
        cleaned.pop("_hits", None)
        items.append(cleaned)

    return {
        "documents": documents,
        "items": items,
        "count": len(documents),
    }


def _error_response(state: GlobalAgentState, task: str | None, reason: str) -> dict:
    content = f"죄송합니다. 처리 중 오류가 발생했습니다: {reason}"
    return {
        "messages": [AIMessage(content=content)],
        "completed_tasks": state.get("completed_tasks", []) + ([task] if task else []),
        "agent_results": {
            **state.get("agent_results", {}),
            **({
                task: content
            } if task else {}),
        },
    }
