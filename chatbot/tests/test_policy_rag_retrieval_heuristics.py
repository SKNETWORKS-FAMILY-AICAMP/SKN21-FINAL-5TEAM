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
    _normalize_policy_query,
)
from chatbot.src.tools.retrieval_tools import _build_filter, _score_policy_adjustment
from chatbot.src.infrastructure.site_retrieval import resolve_site_collections


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


def test_resolve_site_collections_uses_site_scoped_aliases() -> None:
    collections = resolve_site_collections("demo-shop")

    assert collections.faq == "site_demo-shop__faq"
    assert collections.policy == "site_demo-shop__policy"
    assert collections.discovery_image == "site_demo-shop__discovery_image"


def test_resolve_site_collections_uses_global_defaults_for_site_c() -> None:
    collections = resolve_site_collections("site-c")

    assert collections.faq == settings.COLLECTION_FAQ
    assert collections.policy == settings.COLLECTION_TERMS
    assert collections.discovery_image == settings.COLLECTION_CLIP_IMAGE


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


def test_build_query_variants_adds_tracking_and_address_change_variants() -> None:
    tracking_variants = _build_query_variants(
        "송장 번호나 배송 흐름은 어디서 볼 수 있어요?",
        "송장 번호 배송 흐름 확인 방법",
    )
    assert "배송 조회 방법 송장 흐름 확인 경로" in tracking_variants

    address_variants = _build_query_variants(
        "배송 준비 단계에서는 받는 주소를 바꿀 수 있나요?",
        "배송 준비 단계 주소 변경 가능 여부",
    )
    assert "배송지 주소 변경 가능 여부 송장 조회 상품준비중" in address_variants


def test_normalize_policy_query_recovers_holdout_paraphrases() -> None:
    assert _normalize_policy_query(
        "사이즈 교환할 때 추가 택배비를 제가 내야 하나요?",
        "사이즈 교환 추가 택배비 부담 여부",
    ) == "교환 배송비 부담 주체 고객 판매자"

    assert _normalize_policy_query(
        "집에서 잠깐 입어본 정도도 반품이 안 되나요?",
        "반품 기준 사용 흔적 여부",
    ) == "시착 후 반품 가능 조건"

    assert _normalize_policy_query(
        "배송 출발 이후에는 주소 변경이 안 되죠?",
        "배송 출발 이후 주소 변경 가능 여부",
    ) == "출고 후 배송지 변경 가능 여부 불가"

    assert _normalize_policy_query(
        "A/S가 필요하면 어디에 먼저 문의하면 되나요?",
        "A/S 필요 문의처 확인 방법",
    ) == "A/S 문의처 정보 브랜드"

    assert _normalize_policy_query(
        "직접 택배 보낼 때 송장 등록은 꼭 해야 하나요?",
        "택배 송장 등록 필요 여부",
    ) == "직접 발송 반송장 입력 필요 여부"

    assert _normalize_policy_query(
        "옵션마다 반품 보내는 주소가 서로 다를 수도 있나요?",
        "옵션별 반품 주소 차이 여부",
    ) == "옵션별 반품지 상이 여부"


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


def test_policy_adjustment_prefers_tracking_guide_over_tracking_issue_doc() -> None:
    query = "송장 번호나 배송 흐름은 어디서 볼 수 있어요?"
    guide_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "일반 배송 조회는 어떻게 하나요? 송장 흐름과 배송 조회 경로를 안내합니다.",
        "meta": {
            "question": "일반 배송 조회는 어떻게 하나요?",
            "main_category": "배송",
            "summary": "송장 흐름과 배송 조회 경로를 안내합니다.",
        },
    }
    issue_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "송장 흐름 확인이 안되고 있어요. 송장 흐름 오류 상황을 안내합니다.",
        "meta": {
            "question": "송장 흐름 확인이 안되고 있어요.",
            "main_category": "배송",
            "summary": "송장 흐름 오류 상황을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, guide_doc, "배송") > _score_policy_adjustment(
        query, issue_doc, "배송"
    )


def test_policy_adjustment_prefers_return_waybill_doc_for_direct_send_query() -> None:
    query = "직접 택배 보낼 때 송장 등록은 꼭 해야 하나요?"
    return_waybill_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "반송장 입력, 수정은 어떻게 하나요? 직접 발송 시 반송장 입력 방법을 안내합니다.",
        "meta": {
            "question": "반송장 입력, 수정은 어떻게 하나요?",
            "main_category": "취소/교환/반품",
            "summary": "직접 발송 시 반송장 입력 방법을 안내합니다.",
        },
    }
    tracking_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "일반 배송 조회는 어떻게 하나요? 배송 조회 경로를 안내합니다.",
        "meta": {
            "question": "일반 배송 조회는 어떻게 하나요?",
            "main_category": "배송",
            "summary": "배송 조회 경로를 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, return_waybill_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, tracking_doc, "취소/교환/반품"
    )


def test_policy_adjustment_prefers_cost_doc_for_overseas_return_fee_query() -> None:
    query = "해외 배송 주문은 반품하면 비용이 더 드나요?"
    cost_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환/반품 비용은 무료인가요? 반품 배송비와 추가 비용 기준을 안내합니다.",
        "meta": {
            "question": "교환/반품 비용은 무료인가요?",
            "main_category": "취소/교환/반품",
            "summary": "반품 배송비와 추가 비용 기준을 안내합니다.",
        },
    }
    difficult_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환(반품)이 어려운 경우가 있나요? 제한되는 상황을 안내합니다.",
        "meta": {
            "question": "교환(반품)이 어려운 경우가 있나요?",
            "main_category": "취소/교환/반품",
            "summary": "제한되는 상황을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, cost_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, difficult_doc, "취소/교환/반품"
    )


def test_policy_adjustment_prefers_partner_brand_as_doc_over_progress_doc() -> None:
    query = "제휴 브랜드에서 산 상품도 A/S 접수가 가능한가요?"
    partner_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "제휴 브랜드 상품은 A/S가 가능한가요? 제휴 브랜드 A/S 가능 여부를 안내합니다.",
        "meta": {
            "question": "제휴 브랜드 상품은 A/S가 가능한가요?",
            "main_category": "상품/AS 문의",
            "summary": "제휴 브랜드 A/S 가능 여부를 안내합니다.",
        },
    }
    progress_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "프리미엄 관 상품 A/S 진행 상황은 어떻게 확인할 수 있나요?",
        "meta": {
            "question": "프리미엄 관 상품 A/S 진행 상황은 어떻게 확인할 수 있나요?",
            "main_category": "상품/AS 문의",
            "summary": "A/S 진행 상황 확인 방법을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, partner_doc, "상품/AS 문의") > _score_policy_adjustment(
        query, progress_doc, "상품/AS 문의"
    )


def test_policy_adjustment_prefers_defect_doc_for_compensation_query() -> None:
    query = "제품이 불량이면 어떤 보상 기준이 적용돼요?"
    defect_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "상품을 받았는데 불량 같아요 어떻게 하나요? 불량 상품 교환/환불 절차를 안내합니다.",
        "meta": {
            "question": "상품을 받았는데 불량 같아요 어떻게 하나요?",
            "main_category": "상품/AS 문의",
            "summary": "불량 상품 교환/환불 절차를 안내합니다.",
        },
    }
    fee_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환/반품 비용은 무료인가요? 교환 배송비와 반품 배송비 부담 기준을 안내합니다.",
        "meta": {
            "question": "교환/반품 비용은 무료인가요?",
            "main_category": "취소/교환/반품",
            "summary": "교환 배송비와 반품 배송비 부담 기준을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, defect_doc, "상품/AS 문의") > _score_policy_adjustment(
        query, fee_doc, "상품/AS 문의"
    )


def test_policy_adjustment_prefers_exchange_doc_for_exchange_fee_payment_method_query() -> None:
    query = "교환 배송비 결제는 카드 말고 다른 방법도 되나요?"
    exchange_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "상품을 받았는데 교환하고 싶어요. 교환 접수 경로와 교환 배송비 결제 방법을 안내합니다.",
        "meta": {
            "question": "상품을 받았는데 교환하고 싶어요.",
            "main_category": "취소/교환/반품",
            "summary": "교환 접수 경로와 교환 배송비 결제 방법을 안내합니다.",
        },
    }
    fee_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환/반품 비용은 무료인가요? 교환 배송비와 반품 배송비 부담 기준을 안내합니다.",
        "meta": {
            "question": "교환/반품 비용은 무료인가요?",
            "main_category": "취소/교환/반품",
            "summary": "교환 배송비와 반품 배송비 부담 기준을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, exchange_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, fee_doc, "취소/교환/반품"
    )


def test_policy_adjustment_prefers_return_doc_for_auto_pickup_schedule_query() -> None:
    query = "자동 회수로 접수하면 기사님이 며칠 안에 오나요?"
    return_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "상품을 받았는데 반품하고 싶어요. 자동 회수 접수 후 기사 방문 일정을 안내합니다.",
        "meta": {
            "question": "상품을 받았는데 반품하고 싶어요.",
            "main_category": "취소/교환/반품",
            "summary": "자동 회수 접수 후 기사 방문 일정을 안내합니다.",
        },
    }
    receipt_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "반품접수는 어떻게 하나요? 반품 접수 절차를 안내합니다.",
        "meta": {
            "question": "반품접수는 어떻게 하나요?",
            "main_category": "취소/교환/반품",
            "summary": "반품 접수 절차를 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, return_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, receipt_doc, "취소/교환/반품"
    )


def test_policy_adjustment_prefers_fee_doc_for_non_contracted_courier_extra_fee_query() -> None:
    query = "계약된 택배사가 아닌 곳으로 반품 접수하면 추가금이 발생하나요?"
    fee_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환/반품 비용은 무료인가요? 계약 택배사 외 반품 접수 시 추가 비용을 안내합니다.",
        "meta": {
            "question": "교환/반품 비용은 무료인가요?",
            "main_category": "취소/교환/반품",
            "summary": "계약 택배사 외 반품 접수 시 추가 비용을 안내합니다.",
        },
    }
    contact_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "택배사 연락처를 알고 싶어요. 택배사 연락처를 안내합니다.",
        "meta": {
            "question": "택배사 연락처를 알고 싶어요.",
            "main_category": "배송",
            "summary": "택배사 연락처를 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, fee_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, contact_doc, "취소/교환/반품"
    )


def test_policy_adjustment_prefers_payment_method_doc_over_discount_doc() -> None:
    query = "결제할 때 어떤 수단을 사용할 수 있나요?"
    payment_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "결제수단결제 방법에는 어떤 것들이 있나요? 카드, 무통장입금, 계좌이체를 안내합니다.",
        "meta": {
            "question": "결제수단결제 방법에는 어떤 것들이 있나요?",
            "main_category": "구매/결제",
            "summary": "카드, 무통장입금, 계좌이체를 안내합니다.",
        },
    }
    discount_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "구매 시 사용할 수 있는 할인 혜택은 어떤 게 있나요? 쿠폰과 적립금을 안내합니다.",
        "meta": {
            "question": "구매 시 사용할 수 있는 할인 혜택은 어떤 게 있나요?",
            "main_category": "구매/결제",
            "summary": "쿠폰과 적립금을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, payment_doc, "주문/결제") > _score_policy_adjustment(
        query, discount_doc, "주문/결제"
    )


def test_policy_adjustment_prefers_island_shipping_fee_doc_over_shipping_option_doc() -> None:
    query = "산간 지역이면 배송비가 더 붙어요?"
    fee_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "교환/반품 비용은 무료인가요? 제주/도서산간지역의 경우 비용이 추가되어 배송비가 안내됩니다.",
        "meta": {
            "question": "교환/반품 비용은 무료인가요?",
            "main_category": "취소/교환/반품",
            "summary": "제주/도서산간지역의 경우 비용이 추가되어 배송비가 안내됩니다.",
        },
    }
    option_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "일반 배송동일한 상품인데 옵션별로 배송 방법이 다를 수 있나요?",
        "meta": {
            "question": "일반 배송동일한 상품인데 옵션별로 배송 방법이 다를 수 있나요?",
            "main_category": "배송",
            "summary": "옵션별 배송 방법 차이를 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, fee_doc, "배송") > _score_policy_adjustment(
        query, option_doc, "배송"
    )


def test_policy_adjustment_prefers_refund_timing_doc_after_return_completion() -> None:
    query = "반품 완료되면 환불금은 언제 들어오나요?"
    refund_doc = {
        "collection": settings.COLLECTION_FAQ,
        "text": "상품은 보냈는데 언제 환불 되나요? 반품 완료 후 환불 일정을 안내합니다.",
        "meta": {
            "question": "상품은 보냈는데 언제 환불 되나요?",
            "main_category": "취소/교환/반품",
            "summary": "반품 완료 후 환불 일정을 안내합니다.",
        },
    }
    return_period_doc = {
        "collection": settings.COLLECTION_TERMS,
        "text": "[제15조] 청약철회 기간을 안내합니다.",
        "meta": {
            "article_no": "15",
            "paragraph": "1",
            "summary": "청약철회 기간을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, refund_doc, "취소/교환/반품") > _score_policy_adjustment(
        query, return_period_doc, "취소/교환/반품"
    )


def test_policy_adjustment_prefers_delivery_delay_compensation_clause() -> None:
    query = "약속한 배송일보다 늦어지면 보상 규정이 있어요?"
    delay_clause = {
        "collection": settings.COLLECTION_TERMS,
        "text": "[제13조 재화 등의 공급] (2항 배송정보명시) 약정 배송기간 초과 시 손해를 배상하여야 합니다.",
        "meta": {
            "article_no": "13",
            "paragraph": "2",
            "summary": "약정 배송기간 초과 시 손해를 배상합니다.",
        },
    }
    general_clause = {
        "collection": settings.COLLECTION_TERMS,
        "text": "[제13조 재화 등의 공급] (1항) 재화 공급 일반 규정을 안내합니다.",
        "meta": {
            "article_no": "13",
            "paragraph": "1",
            "summary": "재화 공급 일반 규정을 안내합니다.",
        },
    }

    assert _score_policy_adjustment(query, delay_clause, "배송") > _score_policy_adjustment(
        query, general_clause, "배송"
    )
