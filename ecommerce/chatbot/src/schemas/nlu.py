from typing import Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field

class IntentType(str, Enum):
    INFO_SEARCH = "info_search"
    EXECUTION = "execution"

class ActionType(str, Enum):
    REFUND = "refund"
    TRACKING = "tracking"
    ORDER_DETAIL = "order_detail"
    ORDER_LIST = "order_list"
    COURIER_CONTACT = "courier_contact"
    PAYMENT_UPDATE = "payment_update"
    GIFT_CARD = "gift_card"
    REVIEW_SEARCH = "review_search"
    REVIEW_CREATE = "review_create"
    ADDRESS_CHANGE = "address_change"

    @property
    def description(self) -> str:
        descriptions = {
            "refund": "환불/취소 요청",
            "tracking": "배송 조회/조회 요청",
            "order_detail": "주문 상세 조회/내역 확인",
            "order_list": "주문 목록 조회 (주문번호 없을 때)",
            "courier_contact": "택배사 연락처 문의",
            "payment_update": "결제 수단 변경",
            "gift_card": "상품권 등록",
            "review_search": "리뷰 조회",
            "review_create": "리뷰 작성",
            "address_change": "주소지 변경",
        }
        return descriptions.get(self.value, "")

class CategoryType(str, Enum):
    DELIVERY = "배송"
    RETURN_EXCHANGE = "취소/반품/교환"
    ORDER_PAYMENT = "주문/결제"
    MEMBER_INFO = "회원 정보"
    PRODUCT_AS = "상품/AS 문의"
    TERMS = "약관"

    @property
    def description(self) -> str:
        descriptions = {
            "배송": "배송 일정, 택배사, 송장, 도착 등",
            "취소/반품/교환": "환불, 취소, 교환, 반품, 작아요, 커요 등",
            "주문/결제": "결제수단, 입금확인, 영수증, 상품권 등",
            "회원 정보": "비밀번호, 아이디찾기, 탈퇴 등",
            "상품/AS 문의": "제품 상세, 사이즈, AS, 수선, 리뷰 등",
            "약관": "법적 책임, 이용규정 등"
        }
        return descriptions.get(self.value, "")

class NLUResult(BaseModel):
    """
    Result from Natural Language Understanding (NLU) process.
    """
    intent: Optional[IntentType] = Field(None, description="Detected intent of the user. None if no new intent detected.")
    slots: Dict[str, Any] = Field(default_factory=dict, description="Extracted slots from the user message.")
