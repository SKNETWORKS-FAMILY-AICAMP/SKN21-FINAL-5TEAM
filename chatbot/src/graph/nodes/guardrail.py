"""
Guardrail 노드.

역할:
  - 사용자 입력을 prismdata/guardrail-ko-11class 모델로 분류.
  - 서비스와 무관하거나 유해한 입력을 조기에 차단.
  - 모델은 서버 시작 시 1회 로드 (load_guardrail_model 호출) → 요청마다 재로드 없음.

모델 정보:
  - prismdata/guardrail-ko-11class
  - 한국어 텍스트 분류 (11개 클래스)
  - 서비스 관련 클래스로 판별되면 통과, 그 외 → END

서버 시작 시 호출:
  from chatbot.src.graph.nodes.guardrail import load_guardrail_model
  load_guardrail_model()
"""

import logging
from transformers import pipeline, Pipeline
from langchain_core.messages import AIMessage, HumanMessage

from chatbot.src.graph.state import GlobalAgentState

logger = logging.getLogger(__name__)

# ── 모델 싱글톤 ───────────────────────────────────────────

_GUARDRAIL_PIPELINE: Pipeline | None = None

# 허용 레이블: 정상 발화만 허용
_SAFE_LABEL: str = "safe"

# 분류 신뢰도 임계값 (이 값 미만이면 통과로 처리 — 모호한 입력은 허용)
_CONFIDENCE_THRESHOLD: float = 0.9


# ── 모델 로더 (서버 시작 시 1회 호출) ──────────────────────

def load_guardrail_model() -> None:
    """
    서버 시작 시 호출되는 모델 로더.
    prismdata/guardrail-ko-11class 를 메모리에 로드하고 싱글톤으로 캐싱.
    이후 모든 요청은 이 캐싱된 파이프라인을 재사용.
    """
    global _GUARDRAIL_PIPELINE

    if _GUARDRAIL_PIPELINE is not None:
        logger.info("[Guardrail] 모델이 이미 로드되어 있습니다.")
        return

    try:
        logger.info("[Guardrail] prismdata/guardrail-ko-11class 모델 로딩 중...")
        _GUARDRAIL_PIPELINE = pipeline(
            task="text-classification",
            model="prismdata/guardrail-ko-11class",
            top_k=1,          # 가장 높은 확률 클래스 1개만 반환
            truncation=True,
            max_length=512,
        )
        logger.info("[Guardrail] 모델 로딩 완료.")
    except Exception as e:
        logger.error(f"[Guardrail] 모델 로딩 실패: {e}. Guardrail을 비활성화하고 진행합니다.")
        _GUARDRAIL_PIPELINE = None


def is_guardrail_loaded() -> bool:
    return _GUARDRAIL_PIPELINE is not None


# ── 노드 함수 ─────────────────────────────────────────────

def guardrail_node(state: GlobalAgentState) -> dict:
    """
    입력 필터링 노드.
    모델이 로드되지 않은 경우 통과 처리 (fail-open 정책).
    """
    # 모델 미로드 → 통과 (서비스 가용성 우선)
    if _GUARDRAIL_PIPELINE is None:
        logger.warning("[Guardrail] 모델 미로드 상태 — 입력을 통과 처리합니다.")
        return {"guardrail_passed": True}

    user_text = _get_last_user_message(state["messages"])
    if not user_text:
        return {"guardrail_passed": True}

    try:
        results = _GUARDRAIL_PIPELINE(user_text)
        # pipeline top_k=1 반환 형식: [[{"label": ..., "score": ...}]]
        top = results[0][0] if isinstance(results[0], list) else results[0]
        label: str = top["label"].lower()
        score: float = top["score"]

        logger.debug(f"[Guardrail] label={label}, score={score:.3f}, text='{user_text[:50]}'")

        # 신뢰도가 임계값 미만이면 모호한 입력 → 차단 (안전 우선)
        if score < _CONFIDENCE_THRESHOLD:
            blocked_msg = AIMessage(
                content="죄송합니다. 해당 내용은 서비스 정책에 따라 답변이 어렵습니다. 쇼핑 관련 문의 사항이 있으시면 말씀해 주세요."
            )
            return {
                "guardrail_passed": False,
                "messages": [blocked_msg],
            }

        # SAFE(정상 발화) 외 모든 클래스 차단
        if label != _SAFE_LABEL:
            blocked_msg = AIMessage(
                content="죄송합니다. 해당 내용은 서비스 정책에 따라 답변이 어렵습니다. 쇼핑 관련 문의 사항이 있으시면 말씀해 주세요."
            )
            return {
                "guardrail_passed": False,
                "messages": [blocked_msg],
            }

        return {"guardrail_passed": True}

    except Exception as e:
        logger.error(f"[Guardrail] 분류 중 오류 발생: {e} — 통과 처리합니다.")
        return {"guardrail_passed": True}


# ── 라우팅 조건 함수 ──────────────────────────────────────

def route_after_guardrail(state: GlobalAgentState) -> str:
    """
    guardrail_passed 플래그에 따라 분기.
    - True  → "planner"  (정상 처리 경로)
    - False → "end"      (차단 메시지 반환 후 종료)
    """
    if state.get("guardrail_passed", True):
        return "planner"
    return "end"


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _get_last_user_message(messages: list) -> str | None:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = getattr(msg, "content", "")
            return str(content).strip() if content else None
    return None
