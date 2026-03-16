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
    optimized_query = str(transform_response.content).strip()

    retrieval_result = search_knowledge_base.invoke({"query": optimized_query})
    documents: list[str] = retrieval_result.get("documents", [])
    used_fallback = False

    if not documents:
        retrieval_result = search_knowledge_base.invoke({"query": user_query})
        documents = retrieval_result.get("documents", [])
        used_fallback = True

    context = "\n\n".join(documents) if documents else "관련 정책 문서를 찾을 수 없습니다."

    answer_response = llm.invoke([
        SystemMessage(content=POLICY_RAG_ANSWER_PROMPT.format(context=context)),
        *messages,
    ])
    answer_content = str(answer_response.content)

    return {
        "user_query": user_query,
        "optimized_query": optimized_query,
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
