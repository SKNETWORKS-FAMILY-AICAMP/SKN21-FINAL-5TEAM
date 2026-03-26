from __future__ import annotations

from collections.abc import Iterable

from chatbot.src.schemas.planner import TaskIntent


ORDER_CS_ONLY_PROFILE = "order_cs_only"
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


def normalize_capability_profile(profile: str | None) -> str | None:
    normalized = str(profile or "").strip().lower()
    return normalized or None


def normalize_task_intent_value(task: str | TaskIntent) -> str:
    return task.value if isinstance(task, TaskIntent) else str(task)


def split_tasks_for_profile(
    pending_tasks: Iterable[str | TaskIntent],
    *,
    capability_profile: str | None,
) -> tuple[list[str], list[str]]:
    normalized_profile = normalize_capability_profile(capability_profile)
    normalized_tasks = [normalize_task_intent_value(task) for task in pending_tasks]
    if normalized_profile != ORDER_CS_ONLY_PROFILE:
        return normalized_tasks, []

    allowed: list[str] = []
    disallowed: list[str] = []
    for task in normalized_tasks:
        if task in ORDER_CS_ONLY_ALLOWED_TASKS:
            allowed.append(task)
        else:
            disallowed.append(task)
    return allowed, disallowed
