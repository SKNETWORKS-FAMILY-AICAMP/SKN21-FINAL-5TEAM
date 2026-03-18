import os
import sys
from pathlib import Path

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chatbot.src.core.config import settings
from chatbot.src.graph.nodes.policy_rag_subagent import (
    _build_retrieval_attempts,
    _build_query_variants,
    _infer_policy_categories,
    _infer_policy_category,
)
from chatbot.src.tools.retrieval_tools import _build_filter, _score_policy_adjustment


def test_infer_policy_category_prefers_return_policy_for_shipping_fee_queries() -> None:
    assert (
        _infer_policy_category(
            "환불할 때 반품비는 누가 내는 거예요?",
            "환불 시 반품비 부담 주체",
        )
        == "취소/교환/반품"
    )


def test_infer_policy_category_detects_as_queries() -> None:
    assert (
        _infer_policy_category(
            "AS는 어디로 문의해야 하나요?",
            "구매한 상품 A/S 필요 문의 방법",
        )
        == "상품/AS 문의"
    )


def test_build_filter_is_faq_only() -> None:
    faq_filter = _build_filter("배송", settings.COLLECTION_FAQ)

    assert faq_filter is not None
    assert _build_filter("배송", settings.COLLECTION_TERMS) is None


def test_build_retrieval_attempts_omits_none_category() -> None:
    attempts = _build_retrieval_attempts(
        query_variants=["배송 소요 기간", "배송은 보통 며칠 정도 걸리나요?"],
        inferred_categories=[],
    )

    assert attempts == [
        {"query": "배송 소요 기간"},
        {"query": "배송은 보통 며칠 정도 걸리나요?"},
    ]


def test_build_query_variants_adds_payment_cancel_and_bank_refund_variants() -> None:
    variants = _build_query_variants(
        "무통장입금 주문 취소하면 환불은 어떻게 돼요?",
        "무통장입금 주문 취소 환불 절차 방법",
    )

    assert "무통장입금 주문 취소 환불 금액 입금 시점" in variants


def test_infer_policy_categories_prioritizes_payment_for_payment_cancel_query() -> None:
    categories = _infer_policy_categories(
        "결제 후 며칠 안에 취소 가능해요?",
        "주문 취소 가능 여부 상품준비중 취소 방법",
    )

    assert categories[:2] == ["주문/결제", "취소/교환/반품"]


def test_policy_adjustment_penalizes_used_doc_for_general_policy_queries() -> None:
    query = "여러 개 샀는데 하나만 반품할 수 있어요?"
    general_passage = {
        "text": "상품을 여러 개 구매했는데, 일부 수량 부분 교환/반품하고 싶어요.",
        "meta": {
            "question": "상품을 여러 개 구매했는데, 일부 수량 부분 교환/반품하고 싶어요.",
            "main_category": "취소/교환/반품",
            "summary": "일부 수량도 교환/반품 가능합니다.",
        },
    }
    used_passage = {
        "text": "저희 서비스 유즈드USED 상품과 일반 상품 합반품 가능한가요?",
        "meta": {
            "question": "저희 서비스 유즈드USED 상품과 일반 상품 합반품 가능한가요?",
            "main_category": "서비스",
            "summary": "USED 상품과 일반 상품은 합반품이 불가합니다.",
        },
    }

    general_score = _score_policy_adjustment(query, general_passage, "취소/교환/반품")
    used_score = _score_policy_adjustment(query, used_passage, "취소/교환/반품")

    assert general_score > used_score


def test_policy_adjustment_penalizes_partial_doc_when_query_is_general_exchange() -> None:
    query = "색상만 바꾸고 싶은데 교환 신청은 어떻게 해요?"
    general_exchange = {
        "collection": settings.COLLECTION_FAQ,
        "text": "상품을 받았는데 교환하고 싶어요. 교환 접수 경로를 안내합니다.",
        "meta": {
            "question": "상품을 받았는데 교환하고 싶어요.",
            "main_category": "취소/교환/반품",
            "summary": "교환 접수 경로와 교환 배송비를 안내합니다.",
        },
    }
    partial_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "상품을 여러 개 구매했는데, 일부 수량 부분 교환/반품하고 싶어요.",
        "meta": {
            "question": "상품을 여러 개 구매했는데, 일부 수량 부분 교환/반품하고 싶어요.",
            "main_category": "취소/교환/반품",
            "summary": "여러 개 주문한 경우 일부 수량만 교환/반품할 수 있습니다.",
        },
    }

    general_score = _score_policy_adjustment(query, general_exchange, "취소/교환/반품")
    partial_score = _score_policy_adjustment(query, partial_doc, "취소/교환/반품")

    assert general_score > partial_score


def test_policy_adjustment_does_not_penalize_used_doc_when_query_mentions_used() -> None:
    query = "유즈드 상품은 언제부터 판매가 가능한가요?"
    used_passage = {
        "text": "저희 서비스 유즈드상품 발송 후 언제 부터 판매가 가능한가요?",
        "meta": {
            "question": "저희 서비스 유즈드상품 발송 후 언제 부터 판매가 가능한가요?",
            "main_category": "서비스",
            "summary": "검수 완료 후 판매가를 확정하면 판매가 시작됩니다.",
        },
    }

    assert _score_policy_adjustment(query, used_passage, None) > 0


def test_policy_adjustment_prefers_shipping_fee_doc_for_exchange_cost_query() -> None:
    query = "교환할 때 택배비 누가 부담해요?"
    cost_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환/반품 비용은 무료인가요? 교환 배송비와 반품 배송비 부담 기준을 안내합니다.",
        "meta": {
            "question": "교환/반품 비용은 무료인가요?",
            "main_category": "취소/교환/반품",
            "summary": "교환 배송비와 반품 배송비 부담 기준을 안내합니다.",
        },
    }
    difficult_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환(반품)이 어려운 경우가 있나요? 제한되는 상황을 안내합니다.",
        "meta": {
            "question": "교환(반품)이 어려운 경우가 있나요?",
            "main_category": "취소/교환/반품",
            "summary": "교환/반품 제한 상황을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, cost_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, difficult_doc, "취소/교환/반품"
    )


def test_policy_adjustment_prefers_tracking_doc_for_delivery_tracking_query() -> None:
    query = "주문한 상품이 아직 안 왔는데 어디까지 왔는지 확인 가능해요?"
    tracking_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "일반 배송 조회는 어떻게 하나요? 송장 흐름과 배송 조회 경로를 안내합니다.",
        "meta": {
            "question": "일반 배송 조회는 어떻게 하나요?",
            "main_category": "배송",
            "summary": "송장 흐름과 배송 조회 경로를 안내합니다.",
        },
    }
    missing_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "배송 완료 상품을 받지 못했어요. 수령 문제 대응 절차를 안내합니다.",
        "meta": {
            "question": "배송 완료 상품을 받지 못했어요.",
            "main_category": "배송",
            "summary": "수령 문제 대응 절차를 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, tracking_doc, "배송") > _score_policy_adjustment(
        query, missing_doc, "배송"
    )


def test_policy_adjustment_prefers_generic_payment_methods_doc_for_payment_methods_query() -> None:
    query = "결제수단은 어떤 것들 쓸 수 있어요?"
    generic_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "결제수단결제 방법에는 어떤 것들이 있나요? 결제 방법 종류를 안내합니다.",
        "meta": {
            "question": "결제수단결제 방법에는 어떤 것들이 있나요?",
            "main_category": "구매/결제",
            "summary": "결제 방법 종류를 안내합니다.",
        },
    }
    bank_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "결제수단가상 계좌로 결제하는 방법을 알려주세요.",
        "meta": {
            "question": "결제수단가상 계좌로 결제하는 방법을 알려주세요.",
            "main_category": "구매/결제",
            "summary": "가상 계좌 결제 절차를 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, generic_doc, "주문/결제") > _score_policy_adjustment(
        query, bank_doc, "주문/결제"
    )


def test_policy_adjustment_prefers_difficult_return_doc_for_opened_item_query() -> None:
    query = "개봉한 것도 돌려보낼 수 있어요?"
    difficult_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환(반품)이 어려운 경우가 있나요? 개봉 후 제품 가치가 감소하는 경우 반품이 어렵습니다.",
        "meta": {
            "question": "교환(반품)이 어려운 경우가 있나요?",
            "main_category": "취소/교환/반품",
            "summary": "개봉 후 제품 가치가 감소하면 교환/반품이 어렵습니다.",
        },
    }
    refund_progress_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "상품은 보냈는데 언제 환불 되나요? 반품 완료 후 환불 일정을 안내합니다.",
        "meta": {
            "question": "상품은 보냈는데 언제 환불 되나요?",
            "main_category": "취소/교환/반품",
            "summary": "반품 완료 후 환불 일정을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, difficult_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, refund_progress_doc, "취소/교환/반품"
    )


def test_policy_adjustment_prefers_refund_timing_doc_for_bank_transfer_cancel_query() -> None:
    query = "무통장입금 주문 취소하면 환불은 어떻게 돼요?"
    refund_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "주문 취소환불 금액은 언제 입금되나요? 결제수단별 환불 시점을 안내합니다.",
        "meta": {
            "question": "주문 취소환불 금액은 언제 입금되나요?",
            "main_category": "구매/결제",
            "summary": "결제수단별 환불 시점을 안내합니다.",
        },
    }
    payment_methods_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "결제수단결제 방법에는 어떤 것들이 있나요? 결제 방법 종류를 안내합니다.",
        "meta": {
            "question": "결제수단결제 방법에는 어떤 것들이 있나요?",
            "main_category": "구매/결제",
            "summary": "결제 방법 종류를 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, refund_doc, "주문/결제") > _score_policy_adjustment(
        query, payment_methods_doc, "주문/결제"
    )


def test_policy_adjustment_prefers_return_doc_for_gift_return_query() -> None:
    query = "사은품도 같이 반품해야 되나요?"
    return_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "상품을 받았는데 반품하고 싶어요. 받은 사은품이 있다면 같이 포장해서 반품해 주세요.",
        "meta": {
            "question": "상품을 받았는데 반품하고 싶어요.",
            "main_category": "취소/교환/반품",
            "summary": "받은 사은품이 있다면 같이 포장해서 반품해 주세요.",
        },
    }
    difficult_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환(반품)이 어려운 경우가 있나요? 교환/반품 제한 상황을 안내합니다.",
        "meta": {
            "question": "교환(반품)이 어려운 경우가 있나요?",
            "main_category": "취소/교환/반품",
            "summary": "교환/반품 제한 상황을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, return_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, difficult_doc, "취소/교환/반품"
    )
