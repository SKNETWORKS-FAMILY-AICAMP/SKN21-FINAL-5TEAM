from __future__ import annotations

from collections.abc import Iterable

from chatbot.src.schemas.planner import TaskIntent


ORDER_CS_ONLY_PROFILE = "order_cs_only"
ORDER_CS_PLUS_RETRIEVAL_PROFILE = "order_cs_plus_retrieval"
FULL_CAPABILITY_PROFILE = "full"

ORDER_CS_ONLY_ALLOWED_TASKS = frozenset(
    {
        TaskIntent.ORDER_CS.value,
        TaskIntent.POLICY_RAG.value,
        TaskIntent.GENERAL_CHAT.value,
    }
)

ORDER_CS_ONLY_UNSUPPORTED_MESSAGE = (
    "이 챗봇은 주문 조회, 배송 조회, 취소, 환불, 교환과 관련된 안내만 지원합니다. "
    "상품 추천, 리뷰 작성, 중고 등록, 상품권 등록은 지원하지 않습니다."
)

RETRIEVAL_UNSUPPORTED_MESSAGE = (
    "이 챗봇은 현재 활성화된 검색 지식 범위 내에서만 답변합니다. "
    "이미지 검색 또는 정책 검색이 아직 준비되지 않았을 수 있습니다."
)


def normalize_capability_profile(profile: str | None) -> str | None:
    normalized = str(profile or "").strip().lower()
    return normalized or None


def normalize_task_intent_value(task: str | TaskIntent) -> str:
    return task.value if isinstance(task, TaskIntent) else str(task)


def split_tasks_for_profile(
    pending_tasks: Iterable[str | TaskIntent],
    *,
    capability_profile: str | None,
    enabled_retrieval_corpora: Iterable[str] | None = None,
) -> tuple[list[str], list[str]]:
    normalized_profile = normalize_capability_profile(capability_profile)
    normalized_tasks = [normalize_task_intent_value(task) for task in pending_tasks]
    enabled_corpora = {str(item).strip() for item in (enabled_retrieval_corpora or []) if str(item).strip()}
    if normalized_profile == FULL_CAPABILITY_PROFILE or normalized_profile not in {
        ORDER_CS_ONLY_PROFILE,
        ORDER_CS_PLUS_RETRIEVAL_PROFILE,
    }:
        return normalized_tasks, []

    allowed: list[str] = []
    disallowed: list[str] = []
    for task in normalized_tasks:
        if normalized_profile == ORDER_CS_ONLY_PROFILE:
            is_allowed = task in ORDER_CS_ONLY_ALLOWED_TASKS
        else:
            is_allowed = _task_allowed_for_retrieval_profile(task, enabled_corpora)
        if is_allowed:
            allowed.append(task)
        else:
            disallowed.append(task)
    return allowed, disallowed


def _task_allowed_for_retrieval_profile(task: str, enabled_corpora: set[str]) -> bool:
    if task == TaskIntent.ORDER_CS.value or task == TaskIntent.GENERAL_CHAT.value:
        return True
    if task == TaskIntent.POLICY_RAG.value:
        return bool(enabled_corpora & {"faq", "policy"})
    if task == TaskIntent.SEARCH_SIMILAR_TEXT.value:
        return "discovery_image" in enabled_corpora
    if task == TaskIntent.SEARCH_SIMILAR_IMAGE.value:
        return "discovery_image" in enabled_corpora
    return False
