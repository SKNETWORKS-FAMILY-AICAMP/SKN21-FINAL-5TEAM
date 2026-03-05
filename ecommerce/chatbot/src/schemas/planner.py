from enum import Enum
from pydantic import BaseModel, Field
from typing import List


class TaskIntent(str, Enum):
    # 1. Refund SubAgent (주문 CS)
    # 취소 / 반품 / 교환의 구체적 분기는 DB 조회 후 RefundSubAgent 내부 Python 로직이 결정.
    # LLM은 "주문에 문제가 생겼다"는 도메인 의도까지만 분류.
    ORDER_CS = "ORDER_CS"

    # 2. Discovery SubAgent (상품 탐색)
    SEARCH_SIMILAR_TEXT = "SEARCH_SIMILAR_TEXT"
    SEARCH_SIMILAR_IMAGE = "SEARCH_SIMILAR_IMAGE"

    # 3. Policy RAG SubAgent (정책/약관 조회)
    POLICY_RAG = "POLICY_RAG"

    # 4. FormAction SubAgent (폼 기반 UGC 액션: 중고상품, 리뷰, 상품권)
    REGISTER_USED_ITEM = "REGISTER_USED_ITEM"
    WRITE_REVIEW = "WRITE_REVIEW"
    REGISTER_GIFT_CARD = "REGISTER_GIFT_CARD"

    # 일반 대화 (서비스 무관)
    GENERAL_CHAT = "GENERAL_CHAT"


class PlannerOutput(BaseModel):
    pending_tasks: List[TaskIntent] = Field(
        min_length=1,  # 빈 배열 반환 시 ValidationError → planner_node에서 GENERAL_CHAT으로 fallback
        default=[TaskIntent.GENERAL_CHAT],
        description="사용자의 질문에서 도출된 실행해야 할 작업(의도)들의 순서 있는 목록입니다."
    )
