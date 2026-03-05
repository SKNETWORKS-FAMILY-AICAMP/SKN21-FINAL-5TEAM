"""
generate_json_valid_rate_dialog_dataset.py

[목적]
이커머스 액션 기반 챗봇의 JSON Valid Rate 평가를 위한 Dialog 데이터셋을 생성합니다.
FunctionChat-Bench Dialog 스타일의 JSONL 포맷으로 저장됩니다.
eval_data.jsonl의 각 type별 데이터가 여러 건일 경우 각각에 대해 Dialog를 생성합니다.

[평가 핵심]
1) 챗봇이 tool_calls의 arguments 필드에 유효한(파싱 가능한) JSON 문자열을 생성하는지 평가
2) json.loads(arguments) 성공 여부 및 타입 정확성을 기준으로 JSON 유효성 검증

[데이터 소스]
A. eval_data.jsonl → 주문번호, 사용자 이메일
B. DB 조회 → 사용자 ID, 주문 상세(상품명, 가격, 상태 등)
C. 무신사 FAQ (musinsa_faq_20260203_162139_final.json)
   - 실제 사용자 말투/상황 → 질문 스타일 참조
D. 전자상거래 표준약관 (ecommerce_standard_preprocessed.json)
   - 환불·청약철회·교환 불가 사유 등 정책 조건 반영
E. AI Hub 패션/의류 CSV (패션_validation.csv, 의류_validation.csv)
   - 실제 상품 관련 발화문 → 상품 엔티티 반영

[시나리오 템플릿]
- 주문 취소    : get_user_orders → cancel_order
- 환불 신청    : get_user_orders → check_refund_eligibility → open_address_search → register_return_request
- 교환 신청    : get_user_orders → check_exchange_eligibility → open_address_search → register_exchange_request
- 주문 내역 조회(번호 없음) : get_user_orders → get_order_details
- 주문 내역 조회(번호 있음) : get_order_details
- 자연어 키워드 검색 : search_products_vector
- 필터 기반 추천     : recommend_clothes
- 이미지 검색        : search_by_image
- 중고 판매 + 수거   : register_used_sale → request_pickup
- 리뷰 초안 + 등록   : generate_review_draft → create_review
- 상품권 등록        : register_gift_card
"""

import json
import os
import sys
import pandas as pd
from pathlib import Path

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
_THIS_DIR   = Path(__file__).resolve().parent   # API-Bank/data/
_BENCH_ROOT = _THIS_DIR.parent                  # API-Bank/
sys.path.insert(0, str(_BENCH_ROOT))

from src.paths import PROJECT_ROOT, DATA_DIR

# 프로젝트 루트를 sys.path에 추가 (backend 모듈 import용)
sys.path.insert(0, str(PROJECT_ROOT))

_RAW_DIR    = PROJECT_ROOT / "ecommerce" / "chatbot" / "data" / "raw"
FAQ_PATH    = _RAW_DIR / "musinsa_faq" / "musinsa_faq_20260203_162139_final.json"
TERMS_PATH  = _RAW_DIR / "ecommerce_standard" / "ecommerce_standard_preprocessed.json"
FASHION_CSV = _RAW_DIR / "AI_Hub" / "패션_validation.csv"
CLOTHES_CSV = _RAW_DIR / "AI_Hub" / "의류_validation.csv"
TOOLS_PATH  = DATA_DIR / "tools.json"

EVAL_DATA_PATH = _BENCH_ROOT.parent / "eval_data.jsonl"
OUTPUT_PATH = DATA_DIR / "my_eval_json_valid_rate_dialogs.jsonl"


# ─── 헬퍼 함수 ───────────────────────────────────────────────────────────────
def load_faq_samples(path, categories=None, n=5):
    """무신사 FAQ에서 특정 카테고리의 질문-답변 스타일을 샘플링합니다."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    samples = []
    for item in data:
        payload = item.get("payload", {})
        if categories:
            if payload.get("main_category") in categories or payload.get("sub_category") in categories:
                samples.append({"q": payload.get("question", ""), "a": payload.get("answer", ""), "category": payload.get("main_category", "")})
        else:
            samples.append({"q": payload.get("question", ""), "a": payload.get("answer", ""), "category": payload.get("main_category", "")})
        if len(samples) >= n:
            break
    return samples


def load_terms_clause(path, keyword):
    """전자상거래 표준약관에서 키워드가 포함된 조항 텍스트를 반환합니다."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        if keyword in item.get("text", ""):
            return item["text"]
    return ""


def load_csv_product(csv_path, row_idx=5):
    """AI Hub CSV에서 특정 행의 발화문을 반환합니다."""
    df = pd.read_csv(csv_path, encoding="utf-8")
    utterances = df["발화문"].dropna().tolist()
    if row_idx < len(utterances):
        return utterances[row_idx]
    return utterances[0] if utterances else ""


def tc(name, args_dict):
    """tool_calls 리스트 항목 헬퍼"""
    return [{"name": name, "arguments": json.dumps(args_dict, ensure_ascii=False)}]


def load_eval_data(path):
    """eval_data.jsonl에서 type별 데이터를 리스트로 반환합니다."""
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            type_key = entry["type"]
            if type_key not in data:
                data[type_key] = []
            data[type_key].append(entry["data"])
    return data


# 주문 상태 한국어 레이블 매핑
STATUS_LABELS = {
    "pending": "결제 대기", "paid": "결제완료", "preparing": "상품준비중",
    "shipped": "배송중", "delivered": "배송완료",
    "cancelled": "주문 취소", "refunded": "환불 완료"
}


def build_item_name(item_dict):
    """enriched order item에서 표시용 상품명을 구성합니다."""
    parts = [item_dict.get("product_name", "상품")]
    if item_dict.get("product_color"):
        parts.append(item_dict["product_color"])
    if item_dict.get("product_size"):
        parts.append(item_dict["product_size"])
    return " ".join(parts)


def extract_order_info(order_detail):
    """enriched order dict에서 Dialog에 필요한 상세 정보를 추출합니다."""
    status = order_detail.get("status", "pending")
    items = order_detail.get("items", [])
    first_item = items[0] if items else {}

    return {
        "order_id": order_detail["order_number"],
        "status": STATUS_LABELS.get(status, status),
        "status_raw": status,
        "item_name": build_item_name(first_item),
        "product_name": first_item.get("product_name", "상품"),
        "product_id": first_item.get("product_id"),
        "product_size": first_item.get("product_size"),
        "product_color": first_item.get("product_color"),
        "qty": first_item.get("quantity", 1),
        "price": int(float(first_item.get("unit_price", 0))),
        "amount": int(float(order_detail.get("total_amount", 0))),
        "is_cancellable": status in ("paid", "preparing"),
        "is_refundable": status in ("shipped", "delivered"),
        "created_at": order_detail.get("created_at", ""),
        "updated_at": order_detail.get("updated_at", ""),
        "items": [{
            "name": build_item_name(it),
            "qty": it.get("quantity", 1),
            "price": int(float(it.get("unit_price", 0)))
        } for it in items]
    }


def _order_summary(info):
    """주문 목록 표시용 간략 정보"""
    return {"order_id": info["order_id"], "status": info["status"],
            "item_name": info["item_name"], "amount": info["amount"]}


# ─── serial_num 카운터 ────────────────────────────────────────────────────────
_serial = 0
def sn():
    global _serial; _serial += 1; return _serial


# ─── Dialog 빌더 함수 ────────────────────────────────────────────────────────
def build_dialog_cancel(dnum, info, user_id, all_infos, tools_def):
    """주문 취소 Dialog 생성"""
    others = [o for o in all_infos if o["order_id"] != info["order_id"]][:1]
    order_list = [_order_summary(info)] + [_order_summary(o) for o in others]

    U1 = "주문 취소하고 싶어요."
    TC_a = tc("get_user_orders", {"user_id": user_id, "requires_selection": True, "action_context": "cancel"})
    TR_a = json.dumps({"ui_action": "show_order_list", "requires_selection": True, "orders": order_list}, ensure_ascii=False)

    U2 = f'{info["order_id"]} 취소해줘. 이유는 사이즈가 "생각보다 크게" 와서요.'
    TC_b = tc("cancel_order", {"order_id": info["order_id"], "user_id": user_id, "reason": '사이즈가 "생각보다 크게" 와서요', "confirmed": True})
    TR_b = json.dumps({"status": "success", "message": "주문이 취소되었습니다. 환불은 3~5 영업일 내 처리됩니다."}, ensure_ascii=False)
    A3 = f'주문 {info["order_id"]}이 취소되었습니다. 환불은 3~5 영업일 내 처리됩니다.'

    h_q2 = [
        {"role": "user", "content": U1},
        {"role": "assistant", "content": None, "tool_calls": TC_a},
        {"role": "tool", "name": "get_user_orders", "content": TR_a},
    ]
    h_q3 = h_q2 + [
        {"role": "user", "content": U2},
        {"role": "assistant", "content": None, "tool_calls": TC_b},
        {"role": "tool", "name": "cancel_order", "content": TR_b},
    ]

    return {
        "dialog_num": dnum, "dialog_name": "주문 취소",
        "tools_count": len(tools_def), "tools": tools_def,
        "turns": [
            {"turn_num": 1, "serial_num": sn(),
             "query": [{"role": "user", "content": U1}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_a},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 2, "serial_num": sn(),
             "query": h_q2 + [{"role": "user", "content": U2}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_b},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 3, "serial_num": sn(),
             "query": list(h_q3),
             "ground_truth": {"role": "assistant", "content": A3},
             "type_of_output": "completion", "acceptable_arguments": None},
        ]
    }


def build_dialog_refund(dnum, info, user_id, all_infos, tools_def):
    """환불 신청 Dialog 생성"""
    others = [o for o in all_infos if o["order_id"] != info["order_id"]][:1]
    order_list = [_order_summary(info)] + [_order_summary(o) for o in others]

    U1 = "환불 신청하고 싶어요."
    TC_a = tc("get_user_orders", {"user_id": user_id, "requires_selection": True, "action_context": "refund"})
    TR_a = json.dumps({"ui_action": "show_order_list", "requires_selection": True, "orders": order_list}, ensure_ascii=False)

    U2 = f'{info["order_id"]} 환불할게요. 단순변심이에요.'
    TC_b = tc("check_refund_eligibility", {"order_id": info["order_id"], "user_id": user_id, "reason": "단순변심", "is_seller_fault": False})
    TR_b = json.dumps({"eligible": True, "final_refund_amount": info["amount"], "message": "환불 가능합니다. 수령 후 7일 이내이며 상품 상태 양호."}, ensure_ascii=False)

    TC_c = tc("open_address_search", {})
    TR_c = json.dumps({"ui_action": "show_address_search", "message": "주소 검색 버튼을 눌러주세요."}, ensure_ascii=False)

    U3 = "서울 강남구 테헤란로 152 101호"
    TC_d = tc("register_return_request", {"order_id": info["order_id"], "user_id": user_id, "pickup_address": "서울 강남구 테헤란로 152 101호", "confirmed": True})
    TR_d = json.dumps({"status": "success", "message": "반품 접수가 완료되었습니다. 수거 예정일: 2026-03-07"}, ensure_ascii=False)
    A5 = "반품 접수가 완료되었습니다. 수거 예정일은 2026년 3월 7일이며, 수거지는 서울 강남구 테헤란로 152 101호입니다."

    h_q2 = [
        {"role": "user", "content": U1},
        {"role": "assistant", "content": None, "tool_calls": TC_a},
        {"role": "tool", "name": "get_user_orders", "content": TR_a},
    ]
    h_q3 = h_q2 + [
        {"role": "user", "content": U2},
        {"role": "assistant", "content": None, "tool_calls": TC_b},
        {"role": "tool", "name": "check_refund_eligibility", "content": TR_b},
    ]
    h_q4 = h_q3 + [
        {"role": "assistant", "content": None, "tool_calls": TC_c},
        {"role": "tool", "name": "open_address_search", "content": TR_c},
    ]
    h_q5 = h_q4 + [
        {"role": "user", "content": U3},
        {"role": "assistant", "content": None, "tool_calls": TC_d},
        {"role": "tool", "name": "register_return_request", "content": TR_d},
    ]

    return {
        "dialog_num": dnum, "dialog_name": "환불 신청",
        "tools_count": len(tools_def), "tools": tools_def,
        "turns": [
            {"turn_num": 1, "serial_num": sn(),
             "query": [{"role": "user", "content": U1}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_a},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 2, "serial_num": sn(),
             "query": h_q2 + [{"role": "user", "content": U2}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_b},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 3, "serial_num": sn(),
             "query": list(h_q3),
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_c},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 4, "serial_num": sn(),
             "query": h_q4 + [{"role": "user", "content": U3}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_d},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 5, "serial_num": sn(),
             "query": list(h_q5),
             "ground_truth": {"role": "assistant", "content": A5},
             "type_of_output": "completion", "acceptable_arguments": None},
        ]
    }


def build_dialog_exchange(dnum, info, user_id, all_infos, tools_def):
    """교환 신청 Dialog 생성"""
    others = [o for o in all_infos if o["order_id"] != info["order_id"]][:1]
    order_list = [_order_summary(info)] + [_order_summary(o) for o in others]

    U1 = "교환 신청하고 싶어요."
    TC_a = tc("get_user_orders", {"user_id": user_id, "requires_selection": True, "action_context": "exchange"})
    TR_a = json.dumps({"ui_action": "show_order_list", "requires_selection": True, "orders": order_list}, ensure_ascii=False)

    U2 = f'{info["order_id"]} 교환할게요. 사이즈가 작아서요. 새 옵션은 나중에 선택할게요.'
    TC_b = tc("check_exchange_eligibility", {"order_id": info["order_id"], "user_id": user_id, "reason": "사이즈가 작아요", "new_option_id": None})
    TR_b = json.dumps({"eligible": True, "exchange_shipping_fee": 0, "message": "교환 가능합니다. 수거 후 새 옵션을 선택해주세요."}, ensure_ascii=False)

    TC_c = tc("open_address_search", {})
    TR_c = json.dumps({"ui_action": "show_address_search", "message": "수거지 주소를 검색해주세요."}, ensure_ascii=False)

    U3 = "서울 마포구 홍익로 20 302호"
    TC_d = tc("register_exchange_request", {
        "order_id": info["order_id"], "user_id": user_id, "reason": "사이즈가 작아요",
        "pickup_address": "서울 마포구 홍익로 20 302호", "new_option_id": None, "confirmed": True
    })
    TR_d = json.dumps({"status": "success", "message": "교환 접수가 완료되었습니다. 수거 예정일: 2026-03-08"}, ensure_ascii=False)
    A5 = "교환 접수가 완료되었습니다. 수거 예정일은 2026년 3월 8일이며, 새 옵션은 수거 후 선택하실 수 있습니다."

    h_q2 = [
        {"role": "user", "content": U1},
        {"role": "assistant", "content": None, "tool_calls": TC_a},
        {"role": "tool", "name": "get_user_orders", "content": TR_a},
    ]
    h_q3 = h_q2 + [
        {"role": "user", "content": U2},
        {"role": "assistant", "content": None, "tool_calls": TC_b},
        {"role": "tool", "name": "check_exchange_eligibility", "content": TR_b},
    ]
    h_q4 = h_q3 + [
        {"role": "assistant", "content": None, "tool_calls": TC_c},
        {"role": "tool", "name": "open_address_search", "content": TR_c},
    ]
    h_q5 = h_q4 + [
        {"role": "user", "content": U3},
        {"role": "assistant", "content": None, "tool_calls": TC_d},
        {"role": "tool", "name": "register_exchange_request", "content": TR_d},
    ]

    return {
        "dialog_num": dnum, "dialog_name": "교환 신청",
        "tools_count": len(tools_def), "tools": tools_def,
        "turns": [
            {"turn_num": 1, "serial_num": sn(),
             "query": [{"role": "user", "content": U1}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_a},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 2, "serial_num": sn(),
             "query": h_q2 + [{"role": "user", "content": U2}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_b},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 3, "serial_num": sn(),
             "query": list(h_q3),
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_c},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 4, "serial_num": sn(),
             "query": h_q4 + [{"role": "user", "content": U3}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_d},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 5, "serial_num": sn(),
             "query": list(h_q5),
             "ground_truth": {"role": "assistant", "content": A5},
             "type_of_output": "completion", "acceptable_arguments": None},
        ]
    }


def build_dialog_order_list(dnum, user_id, all_infos, tools_def):
    """주문 내역 조회 (주문번호 없음) Dialog 생성"""
    d_orders = all_infos[:3] if len(all_infos) >= 3 else all_infos
    target = d_orders[0] if d_orders else all_infos[0]

    U1 = "내 주문 내역 보고 싶어요."
    TC_a = tc("get_user_orders", {"user_id": user_id, "requires_selection": True})
    TR_a = json.dumps({"ui_action": "show_order_list", "requires_selection": True,
                        "orders": [_order_summary(o) for o in d_orders]}, ensure_ascii=False)

    U2 = f'{target["order_id"]} 상세 보여줘.'
    TC_b = tc("get_order_details", {"order_id": target["order_id"], "user_id": user_id})
    TR_b = json.dumps({"order_id": target["order_id"], "status": target["status"], "items": target["items"],
                        "total_amount": target["amount"], "is_cancellable": target["is_cancellable"],
                        "is_refundable": target["is_refundable"], "created_at": target["created_at"]}, ensure_ascii=False)

    fi = target["items"][0] if target["items"] else {"name": "상품", "qty": 1, "price": 0}
    extra = "취소가 가능합니다." if target["is_cancellable"] else ("환불 신청이 가능합니다." if target["is_refundable"] else "")
    A3 = f'{target["order_id"]} 주문 내역입니다. {fi["name"]} {fi["qty"]}개, {target["amount"]:,}원이며 현재 {target["status"]} 상태입니다. {extra}'.strip()

    h_q2 = [
        {"role": "user", "content": U1},
        {"role": "assistant", "content": None, "tool_calls": TC_a},
        {"role": "tool", "name": "get_user_orders", "content": TR_a},
    ]
    h_q3 = h_q2 + [
        {"role": "user", "content": U2},
        {"role": "assistant", "content": None, "tool_calls": TC_b},
        {"role": "tool", "name": "get_order_details", "content": TR_b},
    ]

    return {
        "dialog_num": dnum, "dialog_name": "주문 내역 조회",
        "tools_count": len(tools_def), "tools": tools_def,
        "turns": [
            {"turn_num": 1, "serial_num": sn(),
             "query": [{"role": "user", "content": U1}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_a},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 2, "serial_num": sn(),
             "query": h_q2 + [{"role": "user", "content": U2}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_b},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 3, "serial_num": sn(),
             "query": list(h_q3),
             "ground_truth": {"role": "assistant", "content": A3},
             "type_of_output": "completion", "acceptable_arguments": None},
        ]
    }


def build_dialog_order_detail(dnum, info, user_id, tools_def):
    """주문 상세 조회 (주문번호 있음) Dialog 생성 — 환불 주문번호 고정"""
    U1 = f'{info["order_id"]} 주문 상세 내역 알려줘.'
    TC_a = tc("get_order_details", {"order_id": info["order_id"], "user_id": user_id})
    TR_a = json.dumps({"order_id": info["order_id"], "status": info["status"], "items": info["items"],
                        "total_amount": info["amount"], "is_cancellable": info["is_cancellable"],
                        "is_refundable": info["is_refundable"], "created_at": info["created_at"]}, ensure_ascii=False)

    fi = info["items"][0] if info["items"] else {"name": "상품", "qty": 1, "price": 0}
    extra = "취소가 가능합니다." if info["is_cancellable"] else ("환불 신청이 가능합니다." if info["is_refundable"] else "")
    A2 = f'{info["order_id"]} 주문 내역입니다. {fi["name"]} {fi["qty"]}개, {info["amount"]:,}원이며 현재 {info["status"]} 상태입니다. {extra}'.strip()

    h_q2 = [
        {"role": "user", "content": U1},
        {"role": "assistant", "content": None, "tool_calls": TC_a},
        {"role": "tool", "name": "get_order_details", "content": TR_a},
    ]

    return {
        "dialog_num": dnum, "dialog_name": "주문 상세 조회",
        "tools_count": len(tools_def), "tools": tools_def,
        "turns": [
            {"turn_num": 1, "serial_num": sn(),
             "query": [{"role": "user", "content": U1}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_a},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 2, "serial_num": sn(),
             "query": list(h_q2),
             "ground_truth": {"role": "assistant", "content": A2},
             "type_of_output": "completion", "acceptable_arguments": None},
        ]
    }


def build_dialog_review(dnum, info, user_id, tools_def):
    """리뷰 초안 작성 + 리뷰 등록 Dialog 생성"""
    product_name = info["item_name"]
    order_id = info["order_id"]
    product_id = str(info["product_id"]) if info["product_id"] else "1"

    U1 = "리뷰 써줘."
    A_bot = "어떤 상품의 리뷰를 작성해드릴까요? 상품명과 만족도(높음/보통/낮음)를 알려주세요."

    U2 = f'{product_name}이고, 만족도는 높음이야. 착용감, 색감, 가성비 키워드로 써줘.'
    TC_a = tc("generate_review_draft", {"product_name": product_name, "satisfaction": "높음", "keywords": ["착용감", "색감", "가성비"]})
    TR_a = json.dumps({
        "success": True,
        "drafts": {
            "short": "착용감, 색감, 가성비 모두 만족!",
            "emotional": f"이 가격에 이 퀄리티라니, 정말 만족스러운 {info['product_name']}이에요.",
            "detailed": "착용감 좋음. 색감 선명. 가성비 우수. 재구매 의사 있음."
        },
        "message": "리뷰 초안이 생성되었습니다."
    }, ensure_ascii=False)

    LONG_REVIEW = (
        "배송이 정말 빠르게 왔고 포장도 꼼꼼했어요. "
        "옷의 소재가 사진보다 훨씬 좋아서 깜짝 놀랐습니다. "
        "착용감이 부드럽고 핏이 예뻐서 여러 번 입고 싶은 옷이에요. "
        "색감도 선명하고 세탁 후에도 변색이 없어서 매우 만족합니다. "
        "다음에도 이 브랜드 제품을 구매할 의사가 있습니다. 강력 추천드려요!"
    )

    U3 = "detailed 버전으로 등록해줘."
    TC_b = tc("create_review", {"order_id": order_id, "product_id": product_id, "user_id": user_id, "rating": 5, "content": LONG_REVIEW})
    TR_b = json.dumps({"success": True, "message": "리뷰가 성공적으로 등록되었습니다.", "review_id": 301}, ensure_ascii=False)
    A4 = "리뷰가 성공적으로 등록되었습니다. 소중한 후기 감사드립니다!"

    h_q2 = [{"role": "user", "content": U1}, {"role": "assistant", "content": A_bot}]
    h_q3 = h_q2 + [
        {"role": "user", "content": U2},
        {"role": "assistant", "content": None, "tool_calls": TC_a},
        {"role": "tool", "name": "generate_review_draft", "content": TR_a},
    ]
    h_q4 = h_q3 + [
        {"role": "user", "content": U3},
        {"role": "assistant", "content": None, "tool_calls": TC_b},
        {"role": "tool", "name": "create_review", "content": TR_b},
    ]

    return {
        "dialog_num": dnum, "dialog_name": "리뷰 작성",
        "tools_count": len(tools_def), "tools": tools_def,
        "turns": [
            {"turn_num": 1, "serial_num": sn(),
             "query": [{"role": "user", "content": U1}],
             "ground_truth": {"role": "assistant", "content": A_bot},
             "type_of_output": "completion", "acceptable_arguments": None},
            {"turn_num": 2, "serial_num": sn(),
             "query": h_q2 + [{"role": "user", "content": U2}],
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_a},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 3, "serial_num": sn(),
             "query": list(h_q3),
             "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC_b},
             "type_of_output": "call", "acceptable_arguments": None},
            {"turn_num": 4, "serial_num": sn(),
             "query": list(h_q4),
             "ground_truth": {"role": "assistant", "content": A4},
             "type_of_output": "completion", "acceptable_arguments": None},
        ]
    }


# ─── 소스 데이터 로드 ─────────────────────────────────────────────────────────
print("[1] 소스 데이터 로드 중...")

faq_review  = load_faq_samples(FAQ_PATH, categories=["상품/AS 문의"], n=5)
faq_refund  = load_faq_samples(FAQ_PATH, categories=["취소/교환/반품"], n=5)
print(f"  • FAQ 리뷰 샘플 {len(faq_review)}건, 반품 샘플 {len(faq_refund)}건")

terms_text = load_terms_clause(TERMS_PATH, "청약철회") or load_terms_clause(TERMS_PATH, "반품")
print(f"  • 약관 조항 로드: {len(terms_text)}자")

fashion_utt = load_csv_product(FASHION_CSV, row_idx=3)
clothes_utt = load_csv_product(CLOTHES_CSV, row_idx=7)
print(f"  • 패션 CSV 발화문: {fashion_utt}")
print(f"  • 의류 CSV 발화문: {clothes_utt}")

with open(TOOLS_PATH, encoding="utf-8") as f:
    tools_def = json.load(f)
print(f"  • 툴 정의 {len(tools_def)}개 로드")


# ─── eval_data.jsonl + DB 조회 ───────────────────────────────────────────────
print("\n[1.5] eval_data.jsonl 및 DB 데이터 로드 중...")

eval_data = load_eval_data(EVAL_DATA_PATH)
print(f"  • eval_data 로드: {list(eval_data.keys())}")

# 모든 eval_data 항목에서 고유 이메일 수집
all_emails = set()
for type_key in eval_data:
    for entry in eval_data[type_key]:
        email = entry.get("user_email")
        if email:
            all_emails.add(email)

from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.router.users.crud import get_user_by_email
from ecommerce.platform.backend.app.router.orders.crud import (
    get_order_by_order_number,
    get_orders_by_user_id,
    enrich_order_with_product_names,
)
# User/Order 모델의 relationship 참조를 해결하기 위해 관련 모델 전부 import
import ecommerce.platform.backend.app.router.shipping.models  # noqa: F401
import ecommerce.platform.backend.app.router.carts.models  # noqa: F401
import ecommerce.platform.backend.app.router.orders.models  # noqa: F401
import ecommerce.platform.backend.app.router.products.models  # noqa: F401
import ecommerce.platform.backend.app.router.points.models  # noqa: F401
import ecommerce.platform.backend.app.router.reviews.models  # noqa: F401
import ecommerce.platform.backend.app.router.user_history.models  # noqa: F401
import ecommerce.platform.backend.app.router.payments.models  # noqa: F401

db = SessionLocal()
try:
    # 각 이메일로 사용자 조회 및 캐시
    user_cache = {}  # email -> user_id
    user_order_cache = {}  # user_id -> all_order_infos
    for email in sorted(all_emails):
        user = get_user_by_email(db, email)
        if not user:
            print(f"  ✗ 사용자를 찾을 수 없습니다: {email}")
            sys.exit(1)
        user_cache[email] = user.id
        print(f"  • 사용자 조회 완료: {email} → user_id={user.id}")

        # 사용자별 전체 주문목록 조회
        orders_list, orders_total = get_orders_by_user_id(db, user.id, limit=10)
        order_details = [enrich_order_with_product_names(db, o) for o in orders_list]
        order_infos = [extract_order_info(d) for d in order_details]
        user_order_cache[user.id] = order_infos
        print(f"  • 사용자 {email} 주문 {orders_total}건 중 {len(order_infos)}건 로드")

    # eval_data의 모든 주문을 type별로 조회 (각 주문의 user_email로 user_id 결정)
    cancel_infos = []
    for entry in eval_data.get("주문취소", []):
        uid = user_cache[entry["user_email"]]
        obj = get_order_by_order_number(db, entry["order_number"])
        if not obj:
            print(f"  ✗ 주문취소 주문을 찾을 수 없습니다: {entry['order_number']}")
            sys.exit(1)
        info = extract_order_info(enrich_order_with_product_names(db, obj))
        info["user_id"] = uid
        info["user_email"] = entry["user_email"]
        cancel_infos.append(info)
        print(f"  • 주문취소: {info['order_id']} ({info['status']}) - {info['item_name']} {info['amount']}원 (user_id={uid})")

    refund_infos = []
    for entry in eval_data.get("환불", []):
        uid = user_cache[entry["user_email"]]
        obj = get_order_by_order_number(db, entry["order_number"])
        if not obj:
            print(f"  ✗ 환불 주문을 찾을 수 없습니다: {entry['order_number']}")
            sys.exit(1)
        info = extract_order_info(enrich_order_with_product_names(db, obj))
        info["user_id"] = uid
        info["user_email"] = entry["user_email"]
        refund_infos.append(info)
        print(f"  • 환불: {info['order_id']} ({info['status']}) - {info['item_name']} {info['amount']}원 (user_id={uid})")

    exchange_infos = []
    for entry in eval_data.get("교환", []):
        uid = user_cache[entry["user_email"]]
        obj = get_order_by_order_number(db, entry["order_number"])
        if not obj:
            print(f"  ✗ 교환 주문을 찾을 수 없습니다: {entry['order_number']}")
            sys.exit(1)
        info = extract_order_info(enrich_order_with_product_names(db, obj))
        info["user_id"] = uid
        info["user_email"] = entry["user_email"]
        exchange_infos.append(info)
        print(f"  • 교환: {info['order_id']} ({info['status']}) - {info['item_name']} {info['amount']}원 (user_id={uid})")

    # user_id → email 역매핑
    user_id_to_email = {v: k for k, v in user_cache.items()}

    # 기본 사용자 (주문 내역 조회, 상품권 등록 등 공통 Dialog용)
    default_user_id = list(user_cache.values())[0]
    default_user_email = user_id_to_email[default_user_id]
    default_order_infos = user_order_cache[default_user_id]
    print(f"  • 기본 사용자: user_id={default_user_id}, email={default_user_email}")

finally:
    db.close()


# ─── Dialog 생성 ──────────────────────────────────────────────────────────────
print("\n[2] Dialog 생성 중...")

dialogs = []
_dnum = 0

# 주문 취소 — eval_data 건수만큼 생성
for info in cancel_infos:
    _dnum += 1
    uid = info["user_id"]
    d = build_dialog_cancel(_dnum, info, uid, user_order_cache[uid], tools_def)
    d["user_id"] = uid
    d["user_email"] = info["user_email"]
    dialogs.append(d)
    print(f"  • Dialog #{_dnum} 주문 취소 ({info['order_id']}, user_id={uid})")

# 환불 신청 — eval_data 건수만큼 생성
for info in refund_infos:
    _dnum += 1
    uid = info["user_id"]
    d = build_dialog_refund(_dnum, info, uid, user_order_cache[uid], tools_def)
    d["user_id"] = uid
    d["user_email"] = info["user_email"]
    dialogs.append(d)
    print(f"  • Dialog #{_dnum} 환불 신청 ({info['order_id']}, user_id={uid})")

# 교환 신청 — eval_data 건수만큼 생성
for info in exchange_infos:
    _dnum += 1
    uid = info["user_id"]
    d = build_dialog_exchange(_dnum, info, uid, user_order_cache[uid], tools_def)
    d["user_id"] = uid
    d["user_email"] = info["user_email"]
    dialogs.append(d)
    print(f"  • Dialog #{_dnum} 교환 신청 ({info['order_id']}, user_id={uid})")

# 주문 내역 조회 (주문번호 없음) — 1개
_dnum += 1
d = build_dialog_order_list(_dnum, default_user_id, default_order_infos, tools_def)
d["user_id"] = default_user_id
d["user_email"] = default_user_email
dialogs.append(d)
print(f"  • Dialog #{_dnum} 주문 내역 조회 (user_id={default_user_id})")

# 주문 상세 조회 (주문번호 있음) — 환불 주문번호 고정, 건수만큼 생성
for info in refund_infos:
    _dnum += 1
    uid = info["user_id"]
    d = build_dialog_order_detail(_dnum, info, uid, tools_def)
    d["user_id"] = uid
    d["user_email"] = info["user_email"]
    dialogs.append(d)
    print(f"  • Dialog #{_dnum} 주문 상세 조회 ({info['order_id']}, user_id={uid})")


# ─── 고정 Dialog: 키워드 검색 (#6) ───────────────────────────────────────────
_dnum += 1
U6_1 = "파란색 청바지 추천해줘. denim slim fit으로."
TC6a = tc("search_products_vector", {"query": "파란색 청바지 denim slim fit", "limit": 5})
TR6a = json.dumps({
    "message": "검색 결과 3개입니다.", "ui_action": "show_product_list",
    "ui_data": [
        {"id": 33001, "name": "Levi's Men Blue Denim Jeans Slim", "price": 59000},
        {"id": 33002, "name": "청바지 슬림핏 인디고 M", "price": 49000},
        {"id": 33003, "name": "Calvin Klein Blue Jeans Slim Regular", "price": 75000}
    ], "requires_selection": False
}, ensure_ascii=False)
A6_2 = "파란색 슬림핏 청바지(denim) 3개를 찾았습니다. 마음에 드시는 상품이 있으신가요?"
h6_q2 = [{"role": "user", "content": U6_1}, {"role": "assistant", "content": None, "tool_calls": TC6a}, {"role": "tool", "name": "search_products_vector", "content": TR6a}]
dialogs.append({
    "dialog_num": _dnum, "dialog_name": "키워드 검색",
    "user_id": default_user_id, "user_email": default_user_email,
    "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(), "query": [{"role": "user", "content": U6_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC6a}, "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(), "query": list(h6_q2),
         "ground_truth": {"role": "assistant", "content": A6_2}, "type_of_output": "completion", "acceptable_arguments": None},
    ]
})
print(f"  • Dialog #{_dnum} 키워드 검색")


# ─── 고정 Dialog: 상품 추천 (#7) ─────────────────────────────────────────────
_dnum += 1
U7_1 = "옷 추천해줘."
A7_bot = "어떤 종류의 옷을 찾으시나요? 카테고리(예: 아우터, 상의), 원하시는 색상, 용도(계절/상황)를 알려주시면 딱 맞는 상품을 추천해드릴게요."
U7_2 = "아우터요. 색상은 네이비랑 블랙 둘 다 괜찮고, 겨울에 입을 거예요."
TC7a = tc("recommend_clothes", {"category": "아우터", "colors": ["네이비", "블랙"], "purpose": "겨울", "limit": 5})
TR7a = json.dumps({
    "message": "추천 상품 3개입니다.", "ui_action": "show_product_list",
    "ui_data": [
        {"id": 44001, "name": "울 블렌드 코트 네이비 M", "price": 89000},
        {"id": 44002, "name": "오버사이즈 패딩 점퍼 블랙 L", "price": 119000},
        {"id": 44003, "name": "더블 브레스티드 코트 네이비 S", "price": 102000}
    ]
}, ensure_ascii=False)
A7_3 = "네이비·블랙 겨울 아우터 3개를 추천드립니다. 울 블렌드 코트, 오버사이즈 패딩, 더블 브레스티드 코트가 있어요. 마음에 드시는 상품이 있으신가요?"
h7_q2 = [{"role": "user", "content": U7_1}, {"role": "assistant", "content": A7_bot}]
h7_q3 = h7_q2 + [{"role": "user", "content": U7_2}, {"role": "assistant", "content": None, "tool_calls": TC7a}, {"role": "tool", "name": "recommend_clothes", "content": TR7a}]
dialogs.append({
    "dialog_num": _dnum, "dialog_name": "상품 추천",
    "user_id": default_user_id, "user_email": default_user_email,
    "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(), "query": [{"role": "user", "content": U7_1}],
         "ground_truth": {"role": "assistant", "content": A7_bot}, "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(), "query": h7_q2 + [{"role": "user", "content": U7_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC7a}, "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(), "query": list(h7_q3),
         "ground_truth": {"role": "assistant", "content": A7_3}, "type_of_output": "completion", "acceptable_arguments": None},
    ]
})
print(f"  • Dialog #{_dnum} 상품 추천")


# ─── 고정 Dialog: 이미지 검색 (#8) ───────────────────────────────────────────
_dnum += 1
U8_1 = "이 이미지랑 비슷한 옷 찾아줘."
A8_bot = "이미지 URL을 알려주시면 유사한 상품을 찾아드릴게요."
U8_2 = "https://img.musinsa.com/sample/winter_coat_2026-beige.jpg 이 이미지야."
TC8a = tc("search_by_image", {"image_url": "https://img.musinsa.com/sample/winter_coat_2026-beige.jpg"})
TR8a = json.dumps({
    "success": True, "message": "유사 상품 3개를 찾았습니다.", "ui_action": "show_product_list",
    "ui_data": [
        {"id": 55001, "name": "Wool Blend Coat Camel M", "price": 89000},
        {"id": 55002, "name": "Oversized Trench Coat Beige L", "price": 95000},
        {"id": 55003, "name": "Double Breasted Coat Off-White M", "price": 102000}
    ]
}, ensure_ascii=False)
A8_3 = "이미지 속 코트와 유사한 상품 3개를 찾았습니다. 마음에 드시는 상품이 있으신가요?"
h8_q2 = [{"role": "user", "content": U8_1}, {"role": "assistant", "content": A8_bot}]
h8_q3 = h8_q2 + [{"role": "user", "content": U8_2}, {"role": "assistant", "content": None, "tool_calls": TC8a}, {"role": "tool", "name": "search_by_image", "content": TR8a}]
dialogs.append({
    "dialog_num": _dnum, "dialog_name": "이미지 검색",
    "user_id": default_user_id, "user_email": default_user_email,
    "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(), "query": [{"role": "user", "content": U8_1}],
         "ground_truth": {"role": "assistant", "content": A8_bot}, "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(), "query": h8_q2 + [{"role": "user", "content": U8_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC8a}, "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(), "query": list(h8_q3),
         "ground_truth": {"role": "assistant", "content": A8_3}, "type_of_output": "completion", "acceptable_arguments": None},
    ]
})
print(f"  • Dialog #{_dnum} 이미지 검색")


# ─── 고정 Dialog: 중고 판매 신청 (#9) ────────────────────────────────────────
_dnum += 1
U9_1 = "나이키 에어맥스 270 중고로 팔고 싶어요. 희망가는 50,000원이에요."
A9_bot = "상품 상태를 알려주시겠어요? (S급 / A급 / B급)"
U9_2 = "A급이에요."
TC9a = tc("register_used_sale", {"item_name": "나이키 에어맥스 270", "category": "신발", "condition": "A급", "expected_price": 50000})
TR9a = json.dumps({"success": True, "tracking_id": "USED-NK270A1", "message": "'나이키 에어맥스 270' 중고 판매가 접수되었습니다. (희망가: 50000원)", "next_steps": "수거 신청(request_pickup)을 진행해주세요."}, ensure_ascii=False)
TC9b = tc("request_pickup", {"tracking_id": "USED-NK270A1", "pickup_address": "서울 서초구 반포대로 45 201호"})
TR9b = json.dumps({"status": "success", "message": "수거 신청이 완료되었습니다. 수거 예정일: 2026-03-06"}, ensure_ascii=False)
A9_4 = "중고 판매 신청이 완료되었습니다. 접수 번호는 USED-NK270A1이며, 수거 예정일은 2026년 3월 6일입니다."
h9_q2 = [{"role": "user", "content": U9_1}, {"role": "assistant", "content": A9_bot}]
h9_q3 = h9_q2 + [{"role": "user", "content": U9_2}, {"role": "assistant", "content": None, "tool_calls": TC9a}, {"role": "tool", "name": "register_used_sale", "content": TR9a}]
h9_q4 = h9_q3 + [{"role": "assistant", "content": None, "tool_calls": TC9b}, {"role": "tool", "name": "request_pickup", "content": TR9b}]
dialogs.append({
    "dialog_num": _dnum, "dialog_name": "중고 판매 신청",
    "user_id": default_user_id, "user_email": default_user_email,
    "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(), "query": [{"role": "user", "content": U9_1}],
         "ground_truth": {"role": "assistant", "content": A9_bot}, "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(), "query": h9_q2 + [{"role": "user", "content": U9_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC9a}, "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(), "query": list(h9_q3),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC9b}, "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(), "query": list(h9_q4),
         "ground_truth": {"role": "assistant", "content": A9_4}, "type_of_output": "completion", "acceptable_arguments": None},
    ]
})
print(f"  • Dialog #{_dnum} 중고 판매 신청")


# ─── 리뷰 작성 — 첫 번째 주문 사용 (#10) ────────────────────────────────────
_dnum += 1
_review_info = cancel_infos[0] if cancel_infos else default_order_infos[0]
_review_uid = _review_info.get("user_id", default_user_id)
_review_email = _review_info.get("user_email", default_user_email)
d = build_dialog_review(_dnum, _review_info, _review_uid, tools_def)
d["user_id"] = _review_uid
d["user_email"] = _review_email
dialogs.append(d)
print(f"  • Dialog #{_dnum} 리뷰 작성 ({_review_info['order_id']}, user_id={_review_uid})")


# ─── 고정 Dialog: 상품권 등록 (#11) ──────────────────────────────────────────
_dnum += 1
U11_1 = "상품권 등록하고 싶어요."
A11_bot = "상품권 코드를 입력해주세요."
U11_2 = "MUSINSA-GIFT-2026-ZXYW 이거야."
TC11a = tc("register_gift_card", {"code": "MUSINSA-GIFT-2026-ZXYW", "user_id": default_user_id})
TR11a = json.dumps({"success": True, "amount": 10000, "message": "상품권이 성공적으로 등록되었습니다. 충전 금액: 10,000원"}, ensure_ascii=False)
A11_3 = "상품권이 성공적으로 등록되었습니다. 10,000원이 충전되었습니다."
h11_q2 = [{"role": "user", "content": U11_1}, {"role": "assistant", "content": A11_bot}]
h11_q3 = h11_q2 + [{"role": "user", "content": U11_2}, {"role": "assistant", "content": None, "tool_calls": TC11a}, {"role": "tool", "name": "register_gift_card", "content": TR11a}]
dialogs.append({
    "dialog_num": _dnum, "dialog_name": "상품권 등록",
    "user_id": default_user_id, "user_email": default_user_email,
    "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(), "query": [{"role": "user", "content": U11_1}],
         "ground_truth": {"role": "assistant", "content": A11_bot}, "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(), "query": h11_q2 + [{"role": "user", "content": U11_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC11a}, "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(), "query": list(h11_q3),
         "ground_truth": {"role": "assistant", "content": A11_3}, "type_of_output": "completion", "acceptable_arguments": None},
    ]
})
print(f"  • Dialog #{_dnum} 상품권 등록")


# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
print(f"\n[3] JSONL 저장 → {OUTPUT_PATH}")
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
if OUTPUT_PATH.exists():
    OUTPUT_PATH.unlink()
    print(f"  • 기존 데이터 초기화 완료: {OUTPUT_PATH.name}")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for d in dialogs:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print(f"  ✓ {len(dialogs)}개 다이얼로그, 총 {_serial}개 턴 저장 완료.")

print(f"\n출력 파일: {OUTPUT_PATH}")
