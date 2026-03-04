"""
generate_json_valid_rate_dialog_dataset.py

[목적]
이커머스 액션 기반 챗봇의 JSON Valid Rate 평가를 위한 Dialog 데이터셋 11개를 생성합니다.
FunctionChat-Bench Dialog 스타일의 JSONL 포맷으로 저장됩니다.

[평가 핵심]
1) 챗봇이 tool_calls의 arguments 필드에 유효한(파싱 가능한) JSON 문자열을 생성하는지 평가
2) 따옴표 이스케이프, 배열, null, boolean, 숫자형, URL, 장문, Unicode 등 직렬화 엣지케이스를 포함
3) json.loads(arguments) 성공 여부 및 타입 정확성을 기준으로 JSON 유효성 검증

[데이터 소스별 활용]
A. 무신사 FAQ (musinsa_faq_20260203_162139_final.json)
   - 실제 사용자 말투/상황 → 질문 스타일 참조
B. 전자상거래 표준약관 (ecommerce_standard_preprocessed.json)
   - 환불·청약철회·교환 불가 사유 등 정책 조건 반영
C. AI Hub 패션/의류 CSV (패션_validation.csv, 의류_validation.csv)
   - 실제 상품 관련 발화문 → 상품 엔티티 반영

[11개 시나리오 — JSON 유효성 엣지케이스별 분류]
- Dialog #1 : 주문 취소              | quote_escape
              get_user_orders → cancel_order
- Dialog #2 : 환불 신청              | empty_object
              get_user_orders → check_refund_eligibility → open_address_search → register_return_request
- Dialog #3 : 교환 신청              | null_value
              get_user_orders → check_exchange_eligibility → open_address_search → register_exchange_request
- Dialog #4 : 주문 내역 조회 (주문번호 없음) | boolean_true
              get_user_orders → get_order_details
- Dialog #5 : 주문 내역 조회 (주문번호 있음) | integer_argument
              get_order_details
- Dialog #6 : 자연어 키워드 검색      | unicode_mixed
              search_products_vector
- Dialog #7 : 필터 기반 추천          | array_argument
              recommend_clothes
- Dialog #8 : 이미지 검색             | url_string
              search_by_image
- Dialog #9 : 중고 판매 신청 + 수거 신청 | integer_argument
              register_used_sale → request_pickup
- Dialog #10: 리뷰 초안 작성 + 리뷰 등록 | long_string
              generate_review_draft → create_review
- Dialog #11: 상품권 등록              | special_chars
              register_gift_card
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

_RAW_DIR    = PROJECT_ROOT / "ecommerce" / "chatbot" / "data" / "raw"
FAQ_PATH    = _RAW_DIR / "musinsa_faq" / "musinsa_faq_20260203_162139_final.json"
TERMS_PATH  = _RAW_DIR / "ecommerce_standard" / "ecommerce_standard_preprocessed.json"
FASHION_CSV = _RAW_DIR / "AI_Hub" / "패션_validation.csv"
CLOTHES_CSV = _RAW_DIR / "AI_Hub" / "의류_validation.csv"
TOOLS_PATH  = DATA_DIR / "tools.json"

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


# ─── serial_num 카운터 ────────────────────────────────────────────────────────
_serial = 0
def sn():
    global _serial; _serial += 1; return _serial


print("\n[2] Dialog 생성 중...")

# ─── Dialog #1 ────────────────────────────────────────────────────────────────
# 따옴표 이스케이프 | 주문 취소
# JSON 엣지케이스: cancel_order reason 필드에 큰따옴표 \" 포함
# 흐름: get_user_orders(requires_selection=True) → cancel_order
# ──────────────────────────────────────────────────────────────────────────────
U1_1 = "주문 취소하고 싶어요."
TC1a = tc("get_user_orders", {
    "user_id": 1,
    "requires_selection": True,
    "action_context": "cancel"
})
TR1a = json.dumps({
    "ui_action": "show_order_list",
    "requires_selection": True,
    "orders": [
        {"order_id": "ORD-20260219-0001", "status": "상품준비중", "item_name": "오버핏 후드집업 그레이 L", "amount": 59000},
        {"order_id": "ORD-20260219-0002", "status": "결제완료",   "item_name": "슬림핏 청바지 인디고 M",  "amount": 49000}
    ]
}, ensure_ascii=False)

U1_2 = 'ORD-20260219-0001 취소해줘. 이유는 사이즈가 "생각보다 크게" 와서요.'
TC1b = tc("cancel_order", {
    "order_id": "ORD-20260219-0001",
    "user_id": 1,
    "reason": '사이즈가 "생각보다 크게" 와서요',
    "confirmed": True
})
TR1b = json.dumps({"status": "success", "message": "주문이 취소되었습니다. 환불은 3~5 영업일 내 처리됩니다."}, ensure_ascii=False)
A1_3 = "주문 ORD-20260219-0001이 취소되었습니다. 환불은 3~5 영업일 내 처리됩니다."

h1_q2 = [
    {"role": "user",      "content": U1_1},
    {"role": "assistant", "content": None, "tool_calls": TC1a},
    {"role": "tool",      "name": "get_user_orders", "content": TR1a},
]
h1_q3 = h1_q2 + [
    {"role": "user",      "content": U1_2},
    {"role": "assistant", "content": None, "tool_calls": TC1b},
    {"role": "tool",      "name": "cancel_order",    "content": TR1b},
]

d1 = {
    "dialog_num": 1, "dialog_name": "주문 취소",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "quote_escape",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U1_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC1a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h1_q2 + [{"role": "user", "content": U1_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC1b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h1_q3),
         "ground_truth": {"role": "assistant", "content": A1_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #2 ────────────────────────────────────────────────────────────────
# 빈 객체 인자 ({}) | 환불 신청
# JSON 엣지케이스: open_address_search arguments = {} (빈 객체)
# 흐름: get_user_orders → check_refund_eligibility → open_address_search → register_return_request
# ──────────────────────────────────────────────────────────────────────────────
U2_1 = "환불 신청하고 싶어요."
TC2a = tc("get_user_orders", {
    "user_id": 1,
    "requires_selection": True,
    "action_context": "refund"
})
TR2a = json.dumps({
    "ui_action": "show_order_list",
    "requires_selection": True,
    "orders": [
        {"order_id": "ORD-20260219-0003", "status": "배송완료", "item_name": "크롭 니트 화이트 S",   "amount": 39000},
        {"order_id": "ORD-20260219-0004", "status": "배송중",   "item_name": "와이드 팬츠 블랙 M",   "amount": 55000}
    ]
}, ensure_ascii=False)

U2_2 = "ORD-20260219-0003 환불할게요. 단순변심이에요."
TC2b = tc("check_refund_eligibility", {
    "order_id": "ORD-20260219-0003",
    "user_id": 1,
    "reason": "단순변심",
    "is_seller_fault": False
})
TR2b = json.dumps({
    "eligible": True,
    "final_refund_amount": 39000,
    "message": "환불 가능합니다. 수령 후 7일 이내이며 상품 상태 양호."
}, ensure_ascii=False)

TC2c = tc("open_address_search", {})   # ← 빈 객체 엣지케이스
TR2c = json.dumps({"ui_action": "show_address_search", "message": "주소 검색 버튼을 눌러주세요."}, ensure_ascii=False)

U2_3 = "서울 강남구 테헤란로 152 101호"
TC2d = tc("register_return_request", {
    "order_id": "ORD-20260219-0003",
    "user_id": 1,
    "pickup_address": "서울 강남구 테헤란로 152 101호",
    "confirmed": True
})
TR2d = json.dumps({"status": "success", "message": "반품 접수가 완료되었습니다. 수거 예정일: 2026-03-07"}, ensure_ascii=False)
A2_5 = "반품 접수가 완료되었습니다. 수거 예정일은 2026년 3월 7일이며, 수거지는 서울 강남구 테헤란로 152 101호입니다."

h2_q2 = [
    {"role": "user",      "content": U2_1},
    {"role": "assistant", "content": None, "tool_calls": TC2a},
    {"role": "tool",      "name": "get_user_orders", "content": TR2a},
]
h2_q3 = h2_q2 + [
    {"role": "user",      "content": U2_2},
    {"role": "assistant", "content": None, "tool_calls": TC2b},
    {"role": "tool",      "name": "check_refund_eligibility", "content": TR2b},
]
h2_q4 = h2_q3 + [
    {"role": "assistant", "content": None, "tool_calls": TC2c},
    {"role": "tool",      "name": "open_address_search", "content": TR2c},
]
h2_q5 = h2_q4 + [
    {"role": "user",      "content": U2_3},
    {"role": "assistant", "content": None, "tool_calls": TC2d},
    {"role": "tool",      "name": "register_return_request", "content": TR2d},
]

d2 = {
    "dialog_num": 2, "dialog_name": "환불 신청",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "empty_object",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U2_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h2_q2 + [{"role": "user", "content": U2_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h2_q3),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2c},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": h2_q4 + [{"role": "user", "content": U2_3}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2d},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 5, "serial_num": sn(),
         "query": list(h2_q5),
         "ground_truth": {"role": "assistant", "content": A2_5},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #3 ────────────────────────────────────────────────────────────────
# null 값 인자 | 교환 신청
# JSON 엣지케이스: check_exchange_eligibility 및 register_exchange_request의 new_option_id=null
# 흐름: get_user_orders → check_exchange_eligibility → open_address_search → register_exchange_request
# ──────────────────────────────────────────────────────────────────────────────
U3_1 = "교환 신청하고 싶어요."
TC3a = tc("get_user_orders", {
    "user_id": 1,
    "requires_selection": True,
    "action_context": "exchange"
})
TR3a = json.dumps({
    "ui_action": "show_order_list",
    "requires_selection": True,
    "orders": [
        {"order_id": "ORD-20260219-0005", "status": "배송완료", "item_name": "라운드넥 티셔츠 블랙 M", "amount": 29000},
        {"order_id": "ORD-20260219-0006", "status": "배송완료", "item_name": "카고 팬츠 카키 L",        "amount": 65000}
    ]
}, ensure_ascii=False)

U3_2 = "ORD-20260219-0005 교환할게요. 사이즈가 작아서요. 새 옵션은 나중에 선택할게요."
TC3b = tc("check_exchange_eligibility", {
    "order_id": "ORD-20260219-0005",
    "user_id": 1,
    "reason": "사이즈가 작아요",
    "new_option_id": None        # ← null 값 엣지케이스
})
TR3b = json.dumps({
    "eligible": True,
    "exchange_shipping_fee": 0,
    "message": "교환 가능합니다. 수거 후 새 옵션을 선택해주세요."
}, ensure_ascii=False)

TC3c = tc("open_address_search", {})
TR3c = json.dumps({"ui_action": "show_address_search", "message": "수거지 주소를 검색해주세요."}, ensure_ascii=False)

U3_3 = "서울 마포구 홍익로 20 302호"
TC3d = tc("register_exchange_request", {
    "order_id": "ORD-20260219-0005",
    "user_id": 1,
    "reason": "사이즈가 작아요",
    "pickup_address": "서울 마포구 홍익로 20 302호",
    "new_option_id": None,       # ← null 값 엣지케이스
    "confirmed": True
})
TR3d = json.dumps({"status": "success", "message": "교환 접수가 완료되었습니다. 수거 예정일: 2026-03-08"}, ensure_ascii=False)
A3_5 = "교환 접수가 완료되었습니다. 수거 예정일은 2026년 3월 8일이며, 새 옵션은 수거 후 선택하실 수 있습니다."

h3_q2 = [
    {"role": "user",      "content": U3_1},
    {"role": "assistant", "content": None, "tool_calls": TC3a},
    {"role": "tool",      "name": "get_user_orders", "content": TR3a},
]
h3_q3 = h3_q2 + [
    {"role": "user",      "content": U3_2},
    {"role": "assistant", "content": None, "tool_calls": TC3b},
    {"role": "tool",      "name": "check_exchange_eligibility", "content": TR3b},
]
h3_q4 = h3_q3 + [
    {"role": "assistant", "content": None, "tool_calls": TC3c},
    {"role": "tool",      "name": "open_address_search", "content": TR3c},
]
h3_q5 = h3_q4 + [
    {"role": "user",      "content": U3_3},
    {"role": "assistant", "content": None, "tool_calls": TC3d},
    {"role": "tool",      "name": "register_exchange_request", "content": TR3d},
]

d3 = {
    "dialog_num": 3, "dialog_name": "교환 신청",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "null_value",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U3_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h3_q2 + [{"role": "user", "content": U3_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h3_q3),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3c},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": h3_q4 + [{"role": "user", "content": U3_3}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3d},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 5, "serial_num": sn(),
         "query": list(h3_q5),
         "ground_truth": {"role": "assistant", "content": A3_5},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #4 ────────────────────────────────────────────────────────────────
# boolean true | 주문 내역 조회 (주문번호 없음)
# JSON 엣지케이스: get_user_orders의 requires_selection=true (boolean true)
# 흐름: get_user_orders(requires_selection=True) → get_order_details
# ──────────────────────────────────────────────────────────────────────────────
U4_1 = "내 주문 내역 보고 싶어요."
TC4a = tc("get_user_orders", {
    "user_id": 1,
    "requires_selection": True   # ← boolean true 엣지케이스
})
TR4a = json.dumps({
    "ui_action": "show_order_list",
    "requires_selection": True,
    "orders": [
        {"order_id": "ORD-20260219-0007", "status": "배송완료", "item_name": "후드 집업 네이비 L",    "amount": 49000},
        {"order_id": "ORD-20260219-0008", "status": "배송중",   "item_name": "맨투맨 오트밀 M",       "amount": 35000},
        {"order_id": "ORD-20260219-0009", "status": "결제완료", "item_name": "슬랙스 차콜 32",        "amount": 58000}
    ]
}, ensure_ascii=False)

U4_2 = "ORD-20260219-0007 상세 보여줘."
TC4b = tc("get_order_details", {
    "order_id": "ORD-20260219-0007",
    "user_id": 1
})
TR4b = json.dumps({
    "order_id": "ORD-20260219-0007",
    "status": "배송완료",
    "items": [{"name": "후드 집업 네이비 L", "qty": 1, "price": 49000}],
    "total_amount": 49000,
    "is_cancellable": False,
    "is_refundable": True,
    "delivered_at": "2026-02-21"
}, ensure_ascii=False)
A4_3 = "ORD-20260219-0007 주문 내역입니다. 후드 집업 네이비 L 1개, 49,000원이며 2026-02-21 배송 완료되었습니다. 환불 신청이 가능합니다."

h4_q2 = [
    {"role": "user",      "content": U4_1},
    {"role": "assistant", "content": None, "tool_calls": TC4a},
    {"role": "tool",      "name": "get_user_orders", "content": TR4a},
]
h4_q3 = h4_q2 + [
    {"role": "user",      "content": U4_2},
    {"role": "assistant", "content": None, "tool_calls": TC4b},
    {"role": "tool",      "name": "get_order_details", "content": TR4b},
]

d4 = {
    "dialog_num": 4, "dialog_name": "주문 내역 조회",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "boolean_true",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U4_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC4a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h4_q2 + [{"role": "user", "content": U4_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC4b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h4_q3),
         "ground_truth": {"role": "assistant", "content": A4_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #5 ────────────────────────────────────────────────────────────────
# 정수형 인자 | 주문 내역 조회 (주문번호 있음)
# JSON 엣지케이스: get_order_details의 user_id=1 (integer 타입)
# 흐름: get_order_details
# ──────────────────────────────────────────────────────────────────────────────
U5_1 = "ORD-20260219-0001 주문 상세 내역 알려줘."
TC5a = tc("get_order_details", {
    "order_id": "ORD-20260219-0001",
    "user_id": 1           # ← integer 타입 엣지케이스
})
TR5a = json.dumps({
    "order_id": "ORD-20260219-0001",
    "status": "상품준비중",
    "items": [{"name": "오버핏 후드집업 그레이 L", "qty": 1, "price": 59000}],
    "total_amount": 59000,
    "is_cancellable": True,
    "is_refundable": False,
    "ordered_at": "2026-02-19"
}, ensure_ascii=False)
A5_2 = "ORD-20260219-0001 주문 내역입니다. 오버핏 후드집업 그레이 L 1개, 59,000원이며 현재 상품준비중 상태입니다. 취소가 가능합니다."

h5_q2 = [
    {"role": "user",      "content": U5_1},
    {"role": "assistant", "content": None, "tool_calls": TC5a},
    {"role": "tool",      "name": "get_order_details", "content": TR5a},
]

d5 = {
    "dialog_num": 5, "dialog_name": "주문 상세 조회",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "integer_argument",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U5_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC5a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h5_q2),
         "ground_truth": {"role": "assistant", "content": A5_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #6 ────────────────────────────────────────────────────────────────
# 한글+영문 혼합 Unicode | 자연어 키워드 검색
# JSON 엣지케이스: search_products_vector query에 한글+영문 혼합 Unicode
# 흐름: search_products_vector
# ──────────────────────────────────────────────────────────────────────────────
U6_1 = "파란색 청바지 추천해줘. denim slim fit으로."
TC6a = tc("search_products_vector", {
    "query": "파란색 청바지 denim slim fit",   # ← unicode_mixed 엣지케이스
    "limit": 5
})
TR6a = json.dumps({
    "message": "검색 결과 3개입니다.",
    "ui_action": "show_product_list",
    "ui_data": [
        {"id": 33001, "name": "Levi's Men Blue Denim Jeans Slim",    "price": 59000},
        {"id": 33002, "name": "청바지 슬림핏 인디고 M",               "price": 49000},
        {"id": 33003, "name": "Calvin Klein Blue Jeans Slim Regular", "price": 75000}
    ],
    "requires_selection": False
}, ensure_ascii=False)
A6_2 = "파란색 슬림핏 청바지(denim) 3개를 찾았습니다. 마음에 드시는 상품이 있으신가요?"

h6_q2 = [
    {"role": "user",      "content": U6_1},
    {"role": "assistant", "content": None, "tool_calls": TC6a},
    {"role": "tool",      "name": "search_products_vector", "content": TR6a},
]

d6 = {
    "dialog_num": 6, "dialog_name": "키워드 검색",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "unicode_mixed",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U6_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC6a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h6_q2),
         "ground_truth": {"role": "assistant", "content": A6_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #7 ────────────────────────────────────────────────────────────────
# 배열 타입 인자 | 필터 기반 추천
# JSON 엣지케이스: recommend_clothes의 colors 필드 — 배열 ["네이비", "블랙"]
# 흐름: (봇 정보 요청) → recommend_clothes
# ──────────────────────────────────────────────────────────────────────────────
U7_1 = "옷 추천해줘."
A7_bot = "어떤 종류의 옷을 찾으시나요? 카테고리(예: 아우터, 상의), 원하시는 색상, 용도(계절/상황)를 알려주시면 딱 맞는 상품을 추천해드릴게요."

U7_2 = "아우터요. 색상은 네이비랑 블랙 둘 다 괜찮고, 겨울에 입을 거예요."
TC7a = tc("recommend_clothes", {
    "category": "아우터",
    "colors": ["네이비", "블랙"],   # ← 배열 타입 엣지케이스
    "purpose": "겨울",
    "limit": 5
})
TR7a = json.dumps({
    "message": "추천 상품 3개입니다.",
    "ui_action": "show_product_list",
    "ui_data": [
        {"id": 44001, "name": "울 블렌드 코트 네이비 M",         "price": 89000},
        {"id": 44002, "name": "오버사이즈 패딩 점퍼 블랙 L",     "price": 119000},
        {"id": 44003, "name": "더블 브레스티드 코트 네이비 S",   "price": 102000}
    ]
}, ensure_ascii=False)
A7_3 = "네이비·블랙 겨울 아우터 3개를 추천드립니다. 울 블렌드 코트, 오버사이즈 패딩, 더블 브레스티드 코트가 있어요. 마음에 드시는 상품이 있으신가요?"

h7_q2 = [
    {"role": "user",      "content": U7_1},
    {"role": "assistant", "content": A7_bot},
]
h7_q3 = h7_q2 + [
    {"role": "user",      "content": U7_2},
    {"role": "assistant", "content": None, "tool_calls": TC7a},
    {"role": "tool",      "name": "recommend_clothes", "content": TR7a},
]

d7 = {
    "dialog_num": 7, "dialog_name": "상품 추천",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "array_argument",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U7_1}],
         "ground_truth": {"role": "assistant", "content": A7_bot},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h7_q2 + [{"role": "user", "content": U7_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC7a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h7_q3),
         "ground_truth": {"role": "assistant", "content": A7_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #8 ────────────────────────────────────────────────────────────────
# URL 포함 문자열 | 이미지 검색
# JSON 엣지케이스: search_by_image의 image_url — 슬래시·콜론·점·하이픈 포함 URL
# 흐름: (봇 URL 요청) → search_by_image
# ──────────────────────────────────────────────────────────────────────────────
U8_1 = "이 이미지랑 비슷한 옷 찾아줘."
A8_bot = "이미지 URL을 알려주시면 유사한 상품을 찾아드릴게요."

U8_2 = "https://img.musinsa.com/sample/winter_coat_2026-beige.jpg 이 이미지야."
TC8a = tc("search_by_image", {
    "image_url": "https://img.musinsa.com/sample/winter_coat_2026-beige.jpg"  # ← URL 문자열 엣지케이스
})
TR8a = json.dumps({
    "success": True,
    "message": "유사 상품 3개를 찾았습니다.",
    "ui_action": "show_product_list",
    "ui_data": [
        {"id": 55001, "name": "Wool Blend Coat Camel M",           "price": 89000},
        {"id": 55002, "name": "Oversized Trench Coat Beige L",     "price": 95000},
        {"id": 55003, "name": "Double Breasted Coat Off-White M",  "price": 102000}
    ]
}, ensure_ascii=False)
A8_3 = "이미지 속 코트와 유사한 상품 3개를 찾았습니다. 마음에 드시는 상품이 있으신가요?"

h8_q2 = [
    {"role": "user",      "content": U8_1},
    {"role": "assistant", "content": A8_bot},
]
h8_q3 = h8_q2 + [
    {"role": "user",      "content": U8_2},
    {"role": "assistant", "content": None, "tool_calls": TC8a},
    {"role": "tool",      "name": "search_by_image", "content": TR8a},
]

d8 = {
    "dialog_num": 8, "dialog_name": "이미지 검색",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "url_string",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U8_1}],
         "ground_truth": {"role": "assistant", "content": A8_bot},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h8_q2 + [{"role": "user", "content": U8_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC8a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h8_q3),
         "ground_truth": {"role": "assistant", "content": A8_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #9 ────────────────────────────────────────────────────────────────
# 정수형 인자 (가격) | 중고 판매 신청 + 수거 신청
# JSON 엣지케이스: register_used_sale의 expected_price=50000 (integer)
# 흐름: (봇 상태 요청) → register_used_sale → request_pickup
# ──────────────────────────────────────────────────────────────────────────────
U9_1 = "나이키 에어맥스 270 중고로 팔고 싶어요. 희망가는 50,000원이에요."
A9_bot = "상품 상태를 알려주시겠어요? (S급 / A급 / B급)"

U9_2 = "A급이에요."
TC9a = tc("register_used_sale", {
    "item_name": "나이키 에어맥스 270",
    "category": "신발",
    "condition": "A급",
    "expected_price": 50000,     # ← integer 타입 엣지케이스
    "user_id": 1
})
TR9a = json.dumps({
    "success": True,
    "tracking_id": "USED-NK270A1",
    "message": "'나이키 에어맥스 270' 중고 판매가 접수되었습니다. (희망가: 50000원)",
    "next_steps": "수거 신청(request_pickup)을 진행해주세요."
}, ensure_ascii=False)

TC9b = tc("request_pickup", {
    "tracking_id": "USED-NK270A1",
    "user_id": 1,
    "pickup_address": "서울 서초구 반포대로 45 201호"
})
TR9b = json.dumps({"status": "success", "message": "수거 신청이 완료되었습니다. 수거 예정일: 2026-03-06"}, ensure_ascii=False)
A9_4 = "중고 판매 신청이 완료되었습니다. 접수 번호는 USED-NK270A1이며, 수거 예정일은 2026년 3월 6일입니다."

h9_q2 = [
    {"role": "user",      "content": U9_1},
    {"role": "assistant", "content": A9_bot},
]
h9_q3 = h9_q2 + [
    {"role": "user",      "content": U9_2},
    {"role": "assistant", "content": None, "tool_calls": TC9a},
    {"role": "tool",      "name": "register_used_sale", "content": TR9a},
]
h9_q4 = h9_q3 + [
    {"role": "assistant", "content": None, "tool_calls": TC9b},
    {"role": "tool",      "name": "request_pickup", "content": TR9b},
]

d9 = {
    "dialog_num": 9, "dialog_name": "중고 판매 신청",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "integer_argument",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U9_1}],
         "ground_truth": {"role": "assistant", "content": A9_bot},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h9_q2 + [{"role": "user", "content": U9_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC9a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h9_q3),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC9b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": list(h9_q4),
         "ground_truth": {"role": "assistant", "content": A9_4},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #10 ───────────────────────────────────────────────────────────────
# 장문 문자열 | 리뷰 초안 작성 + 리뷰 등록
# JSON 엣지케이스: create_review의 content 필드 — 100자 이상 장문 문자열
# 흐름: (봇 정보 요청) → generate_review_draft → create_review
# ──────────────────────────────────────────────────────────────────────────────
U10_1 = "리뷰 써줘."
A10_bot = "어떤 상품의 리뷰를 작성해드릴까요? 상품명과 만족도(높음/보통/낮음)를 알려주세요."

U10_2 = "오버핏 후드집업 그레이 L이고, 만족도는 높음이야. 착용감, 색감, 가성비 키워드로 써줘."
TC10a = tc("generate_review_draft", {
    "product_name": "오버핏 후드집업 그레이 L",
    "satisfaction": "높음",
    "keywords": ["착용감", "색감", "가성비"]
})
TR10a = json.dumps({
    "success": True,
    "drafts": {
        "short":    "착용감, 색감, 가성비 모두 만족!",
        "emotional": "이 가격에 이 퀄리티라니, 정말 만족스러운 후드집업이에요.",
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

U10_3 = "detailed 버전으로 등록해줘."
TC10b = tc("create_review", {
    "order_id": "ORD-20260219-0001",
    "user_id": 1,
    "rating": 5,
    "content": LONG_REVIEW      # ← 장문 문자열 엣지케이스
})
TR10b = json.dumps({"success": True, "message": "리뷰가 성공적으로 등록되었습니다.", "review_id": 301}, ensure_ascii=False)
A10_4 = "리뷰가 성공적으로 등록되었습니다. 소중한 후기 감사드립니다!"

h10_q2 = [
    {"role": "user",      "content": U10_1},
    {"role": "assistant", "content": A10_bot},
]
h10_q3 = h10_q2 + [
    {"role": "user",      "content": U10_2},
    {"role": "assistant", "content": None, "tool_calls": TC10a},
    {"role": "tool",      "name": "generate_review_draft", "content": TR10a},
]
h10_q4 = h10_q3 + [
    {"role": "user",      "content": U10_3},
    {"role": "assistant", "content": None, "tool_calls": TC10b},
    {"role": "tool",      "name": "create_review", "content": TR10b},
]

d10 = {
    "dialog_num": 10, "dialog_name": "리뷰 작성",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "long_string",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U10_1}],
         "ground_truth": {"role": "assistant", "content": A10_bot},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h10_q2 + [{"role": "user", "content": U10_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC10a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h10_q3),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC10b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": list(h10_q4),
         "ground_truth": {"role": "assistant", "content": A10_4},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #11 ───────────────────────────────────────────────────────────────
# 특수문자 포함 문자열 | 상품권 등록
# JSON 엣지케이스: register_gift_card의 code 필드 — 하이픈(-) 포함 영숫자 혼합 코드
# 흐름: (봇 코드 요청) → register_gift_card
# ──────────────────────────────────────────────────────────────────────────────
U11_1 = "상품권 등록하고 싶어요."
A11_bot = "상품권 코드를 입력해주세요."

U11_2 = "MUSINSA-GIFT-2026-ZXYW 이거야."
TC11a = tc("register_gift_card", {
    "code": "MUSINSA-GIFT-2026-ZXYW",   # ← 특수문자(하이픈) 포함 문자열 엣지케이스
    "user_id": 1
})
TR11a = json.dumps({
    "success": True,
    "amount": 10000,
    "message": "상품권이 성공적으로 등록되었습니다. 충전 금액: 10,000원"
}, ensure_ascii=False)
A11_3 = "상품권이 성공적으로 등록되었습니다. 10,000원이 충전되었습니다."

h11_q2 = [
    {"role": "user",      "content": U11_1},
    {"role": "assistant", "content": A11_bot},
]
h11_q3 = h11_q2 + [
    {"role": "user",      "content": U11_2},
    {"role": "assistant", "content": None, "tool_calls": TC11a},
    {"role": "tool",      "name": "register_gift_card", "content": TR11a},
]

d11 = {
    "dialog_num": 11, "dialog_name": "상품권 등록",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "special_chars",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U11_1}],
         "ground_truth": {"role": "assistant", "content": A11_bot},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": h11_q2 + [{"role": "user", "content": U11_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC11a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h11_q3),
         "ground_truth": {"role": "assistant", "content": A11_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
dialogs = [d1, d2, d3, d4, d5, d6, d7, d8, d9, d10, d11]

print(f"\n[3] JSONL 저장 → {OUTPUT_PATH}")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for d in dialogs:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print(f"  ✓ {len(dialogs)}개 다이얼로그, 총 {_serial}개 턴 저장 완료.")

edge_case_dist = {}
for d in dialogs:
    ec = d["json_edge_case"]
    edge_case_dist[ec] = edge_case_dist.get(ec, 0) + 1
print("  • JSON 엣지케이스 분포:")
for ec, cnt in edge_case_dist.items():
    print(f"      {ec}: {cnt}개")

print(f"\n출력 파일: {OUTPUT_PATH}")
