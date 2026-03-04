"""
generate_slot_filling_rate_dialog_dataset.py

[목적]
이커머스 액션 기반 챗봇의 Slot Filling Rate 평가를 위한 Dialog 데이터셋 11개를 생성합니다.
FunctionChat-Bench Dialog 스타일의 JSONL 포맷으로 저장됩니다.

[평가 핵심]
1) 첫 사용자 발화에 일부 슬롯을 일부러 비워둠
2) 챗봇이 추가 질문으로 슬롯을 수집
3) 올바른 툴 + 인자로 호출

[데이터 소스별 활용]
A. 무신사 FAQ (musinsa_faq_20260203_162139_final.json)
   - 실제 사용자 말투/상황 → 질문 스타일 참조
B. 전자상거래 표준약관 (ecommerce_standard_preprocessed.json)
   - 환불·청약철회·교환 불가 사유 등 정책 조건 반영
C. AI Hub 패션/의류 CSV (패션_validation.csv, 의류_validation.csv)
   - 실제 상품 관련 발화문 → 상품 엔티티(상품명/옵션) 반영

[11개 시나리오 — 서로 다른 슬롯 누락 패턴]
- Dialog #1: 주문 취소              — 누락: 주문번호, 취소사유
- Dialog #2: 환불 신청              — 누락: 주문번호, 수거배송지 | get_user_orders → check_refund_eligibility → open_address_search → register_return_request
- Dialog #3: 교환 신청              — 누락: 주문번호, 수거배송지 | get_user_orders → check_exchange_eligibility → open_address_search → register_exchange_request
- Dialog #4: 주문 내역 조회 (주문번호 없음) — 누락: 주문번호 | get_user_orders → get_order_details
- Dialog #5: 주문 내역 조회 (주문번호 있음) — 누락 없음  | get_order_details
- Dialog #6: 자연어 키워드 검색      — 누락 없음  | search_products_vector (자연어 직접 검색)
- Dialog #7: 필터 기반 추천          — 누락: 카테고리, 색상, 용도 | recommend_clothes (카테고리·색상·용도 필터)
- Dialog #8: 이미지 검색             — 누락: 이미지 URL | search_by_image (GPT Vision → 유사 상품)
- Dialog #9: 중고 판매 신청 + 수거 신청 — 누락: 상품 상태 | register_used_sale → request_pickup
- Dialog #10: 리뷰 초안 작성 + 리뷰 등록 — 누락: 상품명, 만족도 | generate_review_draft → create_review
- Dialog #11: 상품권 등록              — 누락: 상품권 코드 | register_gift_card
"""

import json
import os
import pandas as pd

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
import sys
from pathlib import Path

# 현재 파일이 위치한 data 디렉토리를 sys.path에 추가하여 paths.py 임포트
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import (
    DATA_DIR, FAQ_PATH, TERMS_PATH, 
    FASHION_CSV, CLOTHES_CSV, TOOLS_PATH, PROJECT_ROOT
)

OUTPUT_PATH = DATA_DIR / "my_eval_slot_filling_rate_dialogs.jsonl"


# ─── 헬퍼 함수 ───────────────────────────────────────────────────────────────
def load_faq_samples(path, categories=None, n=5):
    """무신사 FAQ에서 특정 카테고리의 질문-답변 스타일을 샘플링합니다."""
    with open(path, encoding="utf-8-sig") as f:
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
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    for item in data:
        if keyword in item.get("text", ""):
            return item["text"]
    return ""


def load_csv_product(csv_path, row_idx=5):
    """AI Hub CSV에서 특정 행의 발화문을 반환합니다."""
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    utterances = df["발화문"].dropna().tolist()
    if row_idx < len(utterances):
        return utterances[row_idx]
    return utterances[0] if utterances else ""


def tc(name, args_dict):
    """tool_calls 리스트 항목 헬퍼"""
    return [{"name": name, "arguments": json.dumps(args_dict, ensure_ascii=False)}]


# ─── 소스 데이터 로드 ─────────────────────────────────────────────────────────
print("[1] 소스 데이터 로드 중...")

faq_refund   = load_faq_samples(FAQ_PATH, categories=["취소/교환/반품", "배송"], n=10)
faq_payment  = load_faq_samples(FAQ_PATH, categories=["주문/결제"], n=5)
print(f"  • FAQ 반품/교환 샘플 {len(faq_refund)}건, 결제 샘플 {len(faq_payment)}건")

terms_text = load_terms_clause(TERMS_PATH, "청약철회") or load_terms_clause(TERMS_PATH, "반품")
print(f"  • 약관 조항 로드: {len(terms_text)}자")

fashion_utt = load_csv_product(FASHION_CSV, row_idx=2)
clothes_utt = load_csv_product(CLOTHES_CSV, row_idx=10)
print(f"  • 패션 CSV 발화문: {fashion_utt}")
print(f"  • 의류 CSV 발화문: {clothes_utt}")

with open(TOOLS_PATH, encoding="utf-8-sig") as f:
    tools_def = json.load(f)
print(f"  • 툴 정의 {len(tools_def)}개 로드")


# ─── serial_num 카운터 ────────────────────────────────────────────────────────
_serial = 0
def sn():
    global _serial; _serial += 1; return _serial


# ─── Dialog #1 ────────────────────────────────────────────────────────────────
# cancel_order | 누락 슬롯: order_id, reason
# ──────────────────────────────────────────────────────────────────────────────
print("\n[2] Dialog 생성 중...")

U1_1 = "주문 취소할래요."
A1_1 = "취소할 주문번호와 취소 사유를 알려주세요."
U1_2 = "ORD-20260219-0004요. 다른 색으로 다시 주문하려고요."
TC1  = tc("cancel_order", {"order_id": "ORD-20260219-0004", "user_id": 1, "reason": "다른 색으로 다시 주문하려고요"})
TR1  = json.dumps({"status": "success", "message": "주문이 취소되었습니다. 환불은 영업일 기준 3~5일 내 처리됩니다."}, ensure_ascii=False)
A1_3 = "주문이 취소되었습니다. 환불은 영업일 기준 3~5일 내 처리됩니다."

d1 = {
    "dialog_num": 1, "dialog_name": "주문 취소", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U1_1}],
         "ground_truth": {"role": "assistant", "content": A1_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": [{"role": "user", "content": U1_1}, {"role": "assistant", "content": A1_1}, {"role": "user", "content": U1_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC1},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": [{"role": "user", "content": U1_1}, {"role": "assistant", "content": A1_1}, {"role": "user", "content": U1_2},
                   {"role": "assistant", "content": None, "tool_calls": TC1},
                   {"role": "tool", "name": "cancel_order", "content": TR1}],
         "ground_truth": {"role": "assistant", "content": A1_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #2 ────────────────────────────────────────────────────────────────
# 누락 슬롯: 주문번호, 수거배송지
# get_user_orders → check_refund_eligibility → open_address_search → register_return_request
# ──────────────────────────────────────────────────────────────────────────────
U2_1 = "환불 신청하고 싶어요."
TC2a = tc("get_user_orders", {"user_id": 1, "requires_selection": True, "action_context": "refund"})
TR2a = json.dumps({"orders": [{"order_id": "ORD-20260219-0005", "product": "코튼 셔츠 아이보리 S", "status": "DELIVERED", "can_return": True}], "message": "환불 가능한 주문 목록입니다."}, ensure_ascii=False)
A2_2 = "환불 가능한 주문 목록을 가져왔습니다. 환불하실 주문을 선택해주세요."
U2_3 = "ORD-20260219-0005 선택할게요."
TC2b = tc("check_refund_eligibility", {"order_id": "ORD-20260219-0005", "user_id": 1, "reason": "단순변심"})
TR2b = json.dumps({"eligible": True, "final_refund_amount": 49000, "message": "환불 가능합니다. 배송 완료 후 7일 이내이며 상품 상태 양호."}, ensure_ascii=False)
A2_4 = "환불이 가능합니다. 예상 환불액은 49,000원입니다. 반품을 진행하시겠어요?"
U2_5 = "네, 진행할게요."
TC2c = tc("open_address_search", {})
TR2c = json.dumps({"ui_action": "show_address_search", "message": "주소 검색 버튼을 눌러주세요."}, ensure_ascii=False)
A2_6 = "주소 검색 화면을 열었습니다. 수거지 주소를 검색하고 선택해주세요."
U2_7 = "서울 강남구 테헤란로 123 선택했어요."
TC2d = tc("register_return_request", {"order_id": "ORD-20260219-0005", "user_id": 1, "pickup_address": "서울 강남구 테헤란로 123", "confirmed": True})
TR2d = json.dumps({"status": "success", "message": "반품 접수가 완료되었습니다. 수거 예정일: 2026-02-21"}, ensure_ascii=False)
A2_8 = "반품 접수가 완료되었습니다. 수거 예정일은 2026년 2월 21일이며, 수거지는 서울 강남구 테헤란로 123입니다."

h2_1 = [
    {"role": "user",      "content": U2_1},
    {"role": "assistant", "content": None, "tool_calls": TC2a},
    {"role": "tool",      "name": "get_user_orders", "content": TR2a},
]
h2_2 = h2_1 + [
    {"role": "assistant", "content": A2_2},
    {"role": "user",      "content": U2_3},
]
h2_3 = h2_2 + [
    {"role": "assistant", "content": None, "tool_calls": TC2b},
    {"role": "tool",      "name": "check_refund_eligibility", "content": TR2b},
]
h2_4 = h2_3 + [
    {"role": "assistant", "content": A2_4},
    {"role": "user",      "content": U2_5},
]
h2_5 = h2_4 + [
    {"role": "assistant", "content": None, "tool_calls": TC2c},
    {"role": "tool",      "name": "open_address_search", "content": TR2c},
]
h2_6 = h2_5 + [
    {"role": "assistant", "content": A2_6},
    {"role": "user",      "content": U2_7},
]
h2_7 = h2_6 + [
    {"role": "assistant", "content": None, "tool_calls": TC2d},
    {"role": "tool",      "name": "register_return_request", "content": TR2d},
]

d2 = {
    "dialog_num": 2, "dialog_name": "환불 신청", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U2_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h2_1),
         "ground_truth": {"role": "assistant", "content": A2_2},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h2_2),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": list(h2_3),
         "ground_truth": {"role": "assistant", "content": A2_4},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 5, "serial_num": sn(),
         "query": list(h2_4),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2c},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 6, "serial_num": sn(),
         "query": list(h2_5),
         "ground_truth": {"role": "assistant", "content": A2_6},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 7, "serial_num": sn(),
         "query": list(h2_6),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2d},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 8, "serial_num": sn(),
         "query": list(h2_7),
         "ground_truth": {"role": "assistant", "content": A2_8},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #3 ────────────────────────────────────────────────────────────────
# 교환 신청 | 누락 슬롯: 주문번호, 수거배송지
# get_user_orders → check_exchange_eligibility → open_address_search → register_exchange_request
# ──────────────────────────────────────────────────────────────────────────────
U3_1 = "교환 신청하고 싶어요."
TC3a = tc("get_user_orders", {"user_id": 1, "requires_selection": True, "action_context": "exchange"})
TR3a = json.dumps({"orders": [{"order_id": "ORD-20260219-0006", "product": "슬림핏 데님 팬츠 블루 M", "status": "DELIVERED", "can_exchange": True}], "message": "교환 가능한 주문 목록입니다."}, ensure_ascii=False)
A3_2 = "교환 가능한 주문 목록을 가져왔습니다. 교환하실 주문을 선택해주세요."
U3_3 = "ORD-20260219-0006 선택할게요. 사이즈가 맞지 않아서요."
TC3b = tc("check_exchange_eligibility", {"order_id": "ORD-20260219-0006", "user_id": 1, "reason": "사이즈가 맞지 않아요"})
TR3b = json.dumps({"eligible": True, "type": "post_shipment", "recommended_tool": "register_exchange_request", "exchange_fee": 6000, "message": "교환 가능 여부 확인 완료 (배송 후 교환)\n- 교환 사유: 사이즈가 맞지 않아요\n배송이 시작된 상태입니다. 맞교환으로 진행됩니다.\n왕복 배송비 6,000원이 발생합니다."}, ensure_ascii=False)
A3_4 = "교환이 가능합니다. 왕복 배송비 6,000원이 발생하며 맞교환으로 진행됩니다. 교환을 진행하시겠어요?"
U3_5 = "네, 진행할게요."
TC3c = tc("open_address_search", {})
TR3c = json.dumps({"ui_action": "show_address_search", "message": "주소 검색 버튼을 눌러주세요."}, ensure_ascii=False)
A3_6 = "주소 검색 화면을 열었습니다. 교환 상품 수거지 주소를 검색하고 선택해주세요."
U3_7 = "서울 마포구 홍익로 20 선택했어요."
TC3d = tc("register_exchange_request", {"order_id": "ORD-20260219-0006", "user_id": 1, "reason": "사이즈가 맞지 않아요", "pickup_address": "서울 마포구 홍익로 20", "confirmed": True})
TR3d = json.dumps({"status": "success", "message": "교환 접수가 완료되었습니다. 수거 예정일: 2026-02-21, 새 상품 발송은 수거 확인 후 진행됩니다."}, ensure_ascii=False)
A3_8 = "교환 접수가 완료되었습니다. 수거 예정일은 2026년 2월 21일이며, 수거지는 서울 마포구 홍익로 20입니다. 수거 확인 후 새 상품이 발송됩니다."

h3_1 = [
    {"role": "user",      "content": U3_1},
    {"role": "assistant", "content": None, "tool_calls": TC3a},
    {"role": "tool",      "name": "get_user_orders", "content": TR3a},
]
h3_2 = h3_1 + [
    {"role": "assistant", "content": A3_2},
    {"role": "user",      "content": U3_3},
]
h3_3 = h3_2 + [
    {"role": "assistant", "content": None, "tool_calls": TC3b},
    {"role": "tool",      "name": "check_exchange_eligibility", "content": TR3b},
]
h3_4 = h3_3 + [
    {"role": "assistant", "content": A3_4},
    {"role": "user",      "content": U3_5},
]
h3_5 = h3_4 + [
    {"role": "assistant", "content": None, "tool_calls": TC3c},
    {"role": "tool",      "name": "open_address_search", "content": TR3c},
]
h3_6 = h3_5 + [
    {"role": "assistant", "content": A3_6},
    {"role": "user",      "content": U3_7},
]
h3_7 = h3_6 + [
    {"role": "assistant", "content": None, "tool_calls": TC3d},
    {"role": "tool",      "name": "register_exchange_request", "content": TR3d},
]

d3 = {
    "dialog_num": 3, "dialog_name": "교환 신청", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U3_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h3_1),
         "ground_truth": {"role": "assistant", "content": A3_2},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h3_2),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": list(h3_3),
         "ground_truth": {"role": "assistant", "content": A3_4},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 5, "serial_num": sn(),
         "query": list(h3_4),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3c},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 6, "serial_num": sn(),
         "query": list(h3_5),
         "ground_truth": {"role": "assistant", "content": A3_6},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 7, "serial_num": sn(),
         "query": list(h3_6),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3d},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 8, "serial_num": sn(),
         "query": list(h3_7),
         "ground_truth": {"role": "assistant", "content": A3_8},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #4 ────────────────────────────────────────────────────────────────
# 주문 내역 조회 (주문번호 없음) | 누락 슬롯: 주문번호
# get_user_orders → get_order_details
# ──────────────────────────────────────────────────────────────────────────────
U4_1 = "주문 내역 조회하고 싶어요."
TC4a = tc("get_user_orders", {"user_id": 1, "requires_selection": False, "action_context": None})
TR4a = json.dumps({"orders": [{"order_id": "ORD-20260219-0003", "product": "오버핏 후드집업 그레이 L", "status": "DELIVERED", "total_amount": 59000, "created_at": "2026-02-19"}, {"order_id": "ORD-20260210-0001", "product": "크루넥 니트 베이지 M", "status": "SHIPPED", "total_amount": 45000, "created_at": "2026-02-10"}], "message": "최근 주문 목록입니다."}, ensure_ascii=False)
A4_2 = "최근 주문 목록을 가져왔습니다. 상세 내역이 궁금한 주문을 선택해주세요."
U4_3 = "ORD-20260219-0003 상세 내역 보고 싶어요."
TC4b = tc("get_order_details", {"order_id": "ORD-20260219-0003", "user_id": 1})
TR4b = json.dumps({"order_id": "ORD-20260219-0003", "status": "DELIVERED", "total_amount": 59000, "items": [{"product_id": 12, "quantity": 1, "subtotal": 59000}], "created_at": "2026-02-19 10:22:00", "delivered_at": "2026-02-21 14:05:00", "can_cancel": False, "can_return": True, "can_exchange": True}, ensure_ascii=False)
A4_4 = "ORD-20260219-0003 주문 상세 내역입니다.\n- 상품: 오버핏 후드집업 그레이 L\n- 결제금액: 59,000원\n- 주문일: 2026년 2월 19일\n- 배송완료일: 2026년 2월 21일\n반품 및 교환이 가능한 상태입니다."

h4_1 = [
    {"role": "user",      "content": U4_1},
    {"role": "assistant", "content": None, "tool_calls": TC4a},
    {"role": "tool",      "name": "get_user_orders", "content": TR4a},
]
h4_2 = h4_1 + [
    {"role": "assistant", "content": A4_2},
    {"role": "user",      "content": U4_3},
]
h4_3 = h4_2 + [
    {"role": "assistant", "content": None, "tool_calls": TC4b},
    {"role": "tool",      "name": "get_order_details", "content": TR4b},
]

d4 = {
    "dialog_num": 4, "dialog_name": "주문 내역 조회 (주문번호 없음)", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U4_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC4a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h4_1),
         "ground_truth": {"role": "assistant", "content": A4_2},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h4_2),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC4b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": list(h4_3),
         "ground_truth": {"role": "assistant", "content": A4_4},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #5 ────────────────────────────────────────────────────────────────
# 주문 내역 조회 (주문번호 있음) | 누락 슬롯: 없음
# get_order_details (직접 호출)
# ──────────────────────────────────────────────────────────────────────────────
U5_1 = "ORD-20260210-0001 주문 상태 확인하고 싶어요."
TC5a = tc("get_order_details", {"order_id": "ORD-20260210-0001", "user_id": 1})
TR5a = json.dumps({"order_id": "ORD-20260210-0001", "status": "SHIPPED", "total_amount": 45000, "items": [{"product_id": 8, "quantity": 1, "subtotal": 45000}], "created_at": "2026-02-10 09:15:00", "delivered_at": None, "can_cancel": False, "can_return": False, "can_exchange": False}, ensure_ascii=False)
A5_2 = "ORD-20260210-0001 주문 상태입니다.\n- 상품: 크루넥 니트 베이지 M\n- 결제금액: 45,000원\n- 주문일: 2026년 2월 10일\n- 현재 상태: 배송중\n배송이 진행 중이므로 취소, 반품, 교환은 아직 불가합니다."

h5_1 = [
    {"role": "user",      "content": U5_1},
    {"role": "assistant", "content": None, "tool_calls": TC5a},
    {"role": "tool",      "name": "get_order_details", "content": TR5a},
]

d5 = {
    "dialog_num": 5, "dialog_name": "주문 내역 조회 (주문번호 있음)", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U5_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC5a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h5_1),
         "ground_truth": {"role": "assistant", "content": A5_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #6 ────────────────────────────────────────────────────────────────
# 자연어 키워드 검색 | 누락 슬롯: 없음
# search_products_vector (직접 호출)
# ──────────────────────────────────────────────────────────────────────────────
U6_1 = "여름에 입을 시원한 파란색 반팔티 찾아줘."
TC6a = tc("search_products_vector", {"query": "여름에 입을 시원한 파란색 반팔티", "limit": 5})
TR6a = json.dumps({"message": "찾아본 상품 3개 목록입니다.", "ui_action": "show_product_list", "ui_data": [{"id": 15001, "name": "Puma Men Blue Casual T-shirt", "price": 30000, "category": "Topwear", "color": "Blue", "season": "Summer"}, {"id": 15002, "name": "Nike Men Sky Blue Sports Tee", "price": 30000, "category": "Topwear", "color": "Blue", "season": "Summer"}, {"id": 15003, "name": "Adidas Men Light Blue Short Sleeve", "price": 30000, "category": "Topwear", "color": "Blue", "season": "Summer"}], "requires_selection": False}, ensure_ascii=False)
A6_2 = "여름에 어울리는 파란색 반팔티 3개를 찾았습니다. 마음에 드시는 상품이 있으신가요?"

h6_1 = [
    {"role": "user",      "content": U6_1},
    {"role": "assistant", "content": None, "tool_calls": TC6a},
    {"role": "tool",      "name": "search_products_vector", "content": TR6a},
]

d6 = {
    "dialog_num": 6, "dialog_name": "자연어 키워드 검색", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U6_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC6a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h6_1),
         "ground_truth": {"role": "assistant", "content": A6_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #7 ────────────────────────────────────────────────────────────────
# 필터 기반 추천 | 누락 슬롯: category, color, usage
# recommend_clothes (카테고리·색상·용도 슬롯 수집 후 호출)
# ──────────────────────────────────────────────────────────────────────────────
U7_1 = "옷 추천해줘."
A7_1 = "어떤 종류의 옷을 원하세요? 상의/하의/아우터 등 카테고리와 원하시는 색상, 그리고 캐주얼/스포츠/포멀 등 용도를 알려주세요."
U7_2 = "검정 하의로 캐주얼하게 입을 거예요."
TC7a = tc("recommend_clothes", {"category": "Bottomwear", "color": "Black", "usage": "Casual", "user_id": 1})
TR7a = json.dumps({"success": True, "message": "조건에 맞는 옷 3개를 추천해드릴게요!", "ui_action": "show_product_list", "ui_data": [{"id": 22001, "name": "Levis Men Black Slim Fit Jeans", "price": 30000, "category": "Apparel > Bottomwear > Jeans", "color": "Black", "season": "Fall", "usage": "Casual"}, {"id": 22002, "name": "Roadster Men Black Regular Trousers", "price": 30000, "category": "Apparel > Bottomwear > Trousers", "color": "Black", "season": "Fall", "usage": "Casual"}, {"id": 22003, "name": "Tokyo Talkies Women Black Joggers", "price": 30000, "category": "Apparel > Bottomwear > Joggers", "color": "Black", "season": "Summer", "usage": "Casual"}]}, ensure_ascii=False)
A7_3 = "캐주얼하게 입기 좋은 검정 하의 3가지를 추천해드렸습니다. 마음에 드시는 상품이 있으신가요?"

h7_1 = [
    {"role": "user",      "content": U7_1},
    {"role": "assistant", "content": A7_1},
    {"role": "user",      "content": U7_2},
]
h7_2 = h7_1 + [
    {"role": "assistant", "content": None, "tool_calls": TC7a},
    {"role": "tool",      "name": "recommend_clothes", "content": TR7a},
]

d7 = {
    "dialog_num": 7, "dialog_name": "필터 기반 추천", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U7_1}],
         "ground_truth": {"role": "assistant", "content": A7_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h7_1),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC7a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h7_2),
         "ground_truth": {"role": "assistant", "content": A7_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #8 ────────────────────────────────────────────────────────────────
# 이미지 검색 | 누락 슬롯: image_url
# search_by_image (이미지 URL 수집 후 GPT-4o Vision 분석 → 유사 상품)
# ──────────────────────────────────────────────────────────────────────────────
U8_1 = "이 사진이랑 비슷한 옷 찾아줘."
A8_1 = "찾으시려는 옷의 이미지 URL을 알려주세요."
U8_2 = "https://img.musinsa.com/sample/oversized_jacket.jpg"
TC8a = tc("search_by_image", {"image_url": "https://img.musinsa.com/sample/oversized_jacket.jpg"})
TR8a = json.dumps({"success": True, "message": "조건에 맞는 옷 3개를 추천해드릴게요!", "ui_action": "show_product_list", "ui_data": [{"id": 44001, "name": "Spykar Men Black Oversized Jacket", "price": 30000, "category": "Apparel > Topwear > Jackets", "color": "Black", "season": "Fall", "usage": "Casual"}, {"id": 44002, "name": "HRX Men Grey Oversized Bomber", "price": 30000, "category": "Apparel > Topwear > Jackets", "color": "Grey", "season": "Winter", "usage": "Casual"}, {"id": 44003, "name": "Roadster Men Khaki Loose Jacket", "price": 30000, "category": "Apparel > Topwear > Jackets", "color": "Khaki", "season": "Fall", "usage": "Casual"}]}, ensure_ascii=False)
A8_3 = "이미지 속 오버핏 자켓과 유사한 상품 3개를 찾았습니다. 마음에 드시는 상품이 있으신가요?"

h8_1 = [
    {"role": "user",      "content": U8_1},
    {"role": "assistant", "content": A8_1},
    {"role": "user",      "content": U8_2},
]
h8_2 = h8_1 + [
    {"role": "assistant", "content": None, "tool_calls": TC8a},
    {"role": "tool",      "name": "search_by_image", "content": TR8a},
]

d8 = {
    "dialog_num": 8, "dialog_name": "이미지 검색", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U8_1}],
         "ground_truth": {"role": "assistant", "content": A8_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h8_1),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC8a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h8_2),
         "ground_truth": {"role": "assistant", "content": A8_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #9 ────────────────────────────────────────────────────────────────
# 중고 판매 신청 + 수거 신청 | 누락 슬롯: condition(상품 상태)
# register_used_sale → request_pickup
# ──────────────────────────────────────────────────────────────────────────────
U9_1 = "나이키 운동화 중고로 팔고 싶어요."
A9_1 = "판매 신청을 도와드리겠습니다. 상품 상태(최상/상/중/하)와 희망 판매가를 알려주세요."
U9_2 = "상태는 '상'이고 희망가는 50,000원이에요."
TC9a = tc("register_used_sale", {"category": "신발", "item_name": "나이키 운동화", "condition": "상", "expected_price": 50000, "user_id": 1})
TR9a = json.dumps({"success": True, "tracking_id": "USED-A1B2C3D4", "message": "'나이키 운동화' 상품의 중고 판매가 접수되었습니다. (희망가: 50000)", "next_steps": "검수 센터로 상품을 보내주시거나 수거 신청(request_pickup)을 진행해주세요."}, ensure_ascii=False)
A9_3 = "중고 판매 신청이 완료되었습니다. 접수 번호는 USED-A1B2C3D4입니다. 수거 신청을 진행하시겠어요?"
U9_4 = "네, 3월 10일에 서울 강남구 테헤란로 456으로 수거 신청할게요."
TC9b = tc("request_pickup", {"sale_id": "USED-A1B2C3D4", "pickup_date": "2026-03-10", "pickup_address": "서울 강남구 테헤란로 456", "user_id": 1})
TR9b = json.dumps({"success": True, "message": "수거 신청 완료: 2026-03-10에 '서울 강남구 테헤란로 456'(으)로 방문 예정입니다.", "sale_id": "USED-A1B2C3D4", "status": "수거 대기중"}, ensure_ascii=False)
A9_5 = "수거 신청이 완료되었습니다. 2026년 3월 10일에 서울 강남구 테헤란로 456으로 방문 예정입니다."

h9_1 = [
    {"role": "user",      "content": U9_1},
    {"role": "assistant", "content": A9_1},
    {"role": "user",      "content": U9_2},
]
h9_2 = h9_1 + [
    {"role": "assistant", "content": None, "tool_calls": TC9a},
    {"role": "tool",      "name": "register_used_sale", "content": TR9a},
]
h9_3 = h9_2 + [
    {"role": "assistant", "content": A9_3},
    {"role": "user",      "content": U9_4},
]
h9_4 = h9_3 + [
    {"role": "assistant", "content": None, "tool_calls": TC9b},
    {"role": "tool",      "name": "request_pickup", "content": TR9b},
]

d9 = {
    "dialog_num": 9, "dialog_name": "중고 판매 신청 + 수거 신청", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U9_1}],
         "ground_truth": {"role": "assistant", "content": A9_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h9_1),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC9a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h9_2),
         "ground_truth": {"role": "assistant", "content": A9_3},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": list(h9_3),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC9b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 5, "serial_num": sn(),
         "query": list(h9_4),
         "ground_truth": {"role": "assistant", "content": A9_5},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #10 ───────────────────────────────────────────────────────────────
# 리뷰 초안 작성 + 리뷰 등록 | 누락 슬롯: product_name(상품명), satisfaction(만족도)
# generate_review_draft → create_review
# ──────────────────────────────────────────────────────────────────────────────
U10_1 = "리뷰 쓰는 거 도와줘요."
A10_1 = "리뷰 초안 작성을 도와드리겠습니다. 어떤 상품에 대한 리뷰인지, 그리고 만족도(높음/보통/낮음)를 알려주세요."
U10_2 = "ORD-20260219-0003에서 구매한 오버핏 후드집업이요. 만족도는 높음이고, 착용감이랑 색감이 좋았어요."
TC10a = tc("generate_review_draft", {"product_name": "오버핏 후드집업 그레이 L", "satisfaction": "높음", "keywords": ["착용감", "색감"]})
TR10a = json.dumps({"success": True, "drafts": {"short": "착용감과 색감이 마음에 쏙 드는 후드집업!", "emotional": "오랜만에 산 옷인데 착용감이 정말 부드럽고, 색감이 사진보다 훨씬 예뻐서 기분이 너무 좋아요.", "detailed": "착용감 좋음. 색감 사진과 동일. 재구매 의사 있음."}, "message": "리뷰 초안이 생성되었습니다. 마음에 드는 버전을 선택해주세요."}, ensure_ascii=False)
A10_3 = "리뷰 초안 3가지를 생성했습니다.\n1. 짧은: 착용감과 색감이 마음에 쏙 드는 후드집업!\n2. 감성적: 오랜만에 산 옷인데 착용감이 정말 부드럽고, 색감이 사진보다 훨씬 예뻐서 기분이 너무 좋아요.\n3. 무뚝뚝: 착용감 좋음. 색감 사진과 동일. 재구매 의사 있음.\n어떤 버전으로 등록하시겠어요? 별점(1~5)도 함께 알려주세요."
U10_4 = "감성적인 버전으로 할게요. 별점은 5점이요."
TC10b = tc("create_review", {"order_id": "ORD-20260219-0003", "rating": 5, "content": "오랜만에 산 옷인데 착용감이 정말 부드럽고, 색감이 사진보다 훨씬 예뻐서 기분이 너무 좋아요.", "user_id": 1})
TR10b = json.dumps({"success": True, "message": "리뷰가 성공적으로 등록되었습니다.", "review_id": 42}, ensure_ascii=False)
A10_5 = "리뷰가 성공적으로 등록되었습니다. 소중한 후기 감사드립니다!"

h10_1 = [
    {"role": "user",      "content": U10_1},
    {"role": "assistant", "content": A10_1},
    {"role": "user",      "content": U10_2},
]
h10_2 = h10_1 + [
    {"role": "assistant", "content": None, "tool_calls": TC10a},
    {"role": "tool",      "name": "generate_review_draft", "content": TR10a},
]
h10_3 = h10_2 + [
    {"role": "assistant", "content": A10_3},
    {"role": "user",      "content": U10_4},
]
h10_4 = h10_3 + [
    {"role": "assistant", "content": None, "tool_calls": TC10b},
    {"role": "tool",      "name": "create_review", "content": TR10b},
]

d10 = {
    "dialog_num": 10, "dialog_name": "리뷰 초안 작성 + 리뷰 등록", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U10_1}],
         "ground_truth": {"role": "assistant", "content": A10_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h10_1),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC10a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h10_2),
         "ground_truth": {"role": "assistant", "content": A10_3},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": list(h10_3),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC10b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 5, "serial_num": sn(),
         "query": list(h10_4),
         "ground_truth": {"role": "assistant", "content": A10_5},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #11 ───────────────────────────────────────────────────────────────
# 상품권 등록 | 누락 슬롯: code(상품권 코드)
# register_gift_card (단일 툴)
# ──────────────────────────────────────────────────────────────────────────────
U11_1 = "상품권 등록하고 싶어요."
A11_1 = "상품권 코드를 입력해주세요."
U11_2 = "코드는 GIFT-ABCD-1234예요."
TC11a = tc("register_gift_card", {"code": "GIFT-ABCD-1234", "user_id": 1})
TR11a = json.dumps({"success": True, "message": "상품권이 성공적으로 등록되었습니다.", "balance": 30000, "expires_at": "2026-12-31"}, ensure_ascii=False)
A11_3 = "상품권(GIFT-ABCD-1234)이 성공적으로 등록되었습니다. 잔액 30,000원이 계정에 추가되었으며, 유효기간은 2026년 12월 31일까지입니다."

d11 = {
    "dialog_num": 11, "dialog_name": "상품권 등록", "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U11_1}],
         "ground_truth": {"role": "assistant", "content": A11_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": [{"role": "user", "content": U11_1}, {"role": "assistant", "content": A11_1}, {"role": "user", "content": U11_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC11a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": [{"role": "user", "content": U11_1}, {"role": "assistant", "content": A11_1}, {"role": "user", "content": U11_2},
                   {"role": "assistant", "content": None, "tool_calls": TC11a},
                   {"role": "tool", "name": "register_gift_card", "content": TR11a}],
         "ground_truth": {"role": "assistant", "content": A11_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
dialogs = [d1, d2, d3, d4, d5, d6, d7, d8, d9, d10, d11]

print(f"\n[3] JSONL 저장 → {OUTPUT_PATH}")
with open(OUTPUT_PATH, "w", encoding="utf-8-sig") as f:
    for d in dialogs:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print(f"  ✓ {len(dialogs)}개 다이얼로그, 총 {_serial}개 턴 저장 완료.")


print(f"\n출력 파일: {OUTPUT_PATH}")
