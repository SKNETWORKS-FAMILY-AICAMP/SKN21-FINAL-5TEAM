"""
generate_slot_filling_rate_dialog_dataset.py

[목적]
이커머스 액션 기반 챗봇의 Slot Filling Rate 평가를 위한 Dialog 데이터셋 5개를 생성합니다.
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

[5개 시나리오 — 서로 다른 슬롯 누락 패턴]
- Dialog #1: 교환 가능 여부 확인   — 누락: 주문번호
- Dialog #2: 반품 신청 (주소 플로우) — 누락: 주문번호, 수거주소
- Dialog #3: 결제수단 변경          — 누락: 주문번호, 결제수단
- Dialog #4: 주문 취소              — 누락: 주문번호, 취소사유
- Dialog #5: 환불 규정 문의         — 누락: 상황 정보(배송일, 상태)
"""

import json
import os
import pandas as pd

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
from .paths import DATA_DIR, FAQ_PATH, TERMS_PATH, FASHION_CSV, CLOTHES_CSV, TOOLS_PATH
import os

OUTPUT_PATH    = DATA_DIR / "my_eval_slot_filling_rate_dialog_5.jsonl"


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
    return [{
        "id": "random_id", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args_dict, ensure_ascii=False)}
    }]


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

with open(TOOLS_PATH, encoding="utf-8") as f:
    tools_def = json.load(f)
print(f"  • 툴 정의 {len(tools_def)}개 로드")


# ─── serial_num 카운터 ────────────────────────────────────────────────────────
_serial = 0
def sn():
    global _serial; _serial += 1; return _serial


# ─── Dialog #1 ────────────────────────────────────────────────────────────────
# check_exchange_eligibility | 누락 슬롯: order_id
# [FAQ] 교환 질문 말투  [CSV] 의류 사이즈 변경 패턴
# ──────────────────────────────────────────────────────────────────────────────
print("\n[2] 5개 Dialog 생성 중...")

U1_1 = "오버핏 후드 집업 블랙 M 사이즈가 작아서 L로 교환 가능한지 확인해주세요."
A1_1 = "교환 가능 여부를 확인하려면 주문번호가 필요합니다. 주문번호를 알려주시겠어요?"
U1_2 = "ORD-20260219-0001이요."
TC1  = tc("check_exchange_eligibility", {"order_id": "ORD-20260219-0001", "user_id": 1, "reason": "사이즈가 작아서 교환"})
TR1  = json.dumps({"eligible": True, "message": "교환 가능합니다. 배송 완료 후 7일 이내이며 상품 상태 양호."}, ensure_ascii=False)
A1_3 = "교환이 가능합니다. 배송 완료 후 7일 이내이며 상품 상태가 양호합니다. 교환을 진행하시겠어요?"

d1 = {
    "dialog_num": 1, "tools_count": len(tools_def), "tools": tools_def,
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
                   {"role": "tool", "tool_call_id": "random_id", "name": "check_exchange_eligibility", "content": TR1}],
         "ground_truth": {"role": "assistant", "content": A1_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}

# ─── Dialog #2 ────────────────────────────────────────────────────────────────
# open_address_search → register_return_request | 누락: order_id, 수거주소
# [FAQ] 반품 말투  [CSV] 패션 원단 하자  [TERMS] 청약철회
# ──────────────────────────────────────────────────────────────────────────────
U2_1 = "받아보니 원단이 생각보다 너무 얇아서 반품하고 싶어요."
A2_1 = "반품 신청을 도와드릴게요. 주문번호와 반품하실 상품명을 알려주세요."
U2_2 = "주문번호 ORD-20260219-0002이고, '코튼 셔츠 아이보리 S'예요."
A2_2 = "수거지 주소가 필요합니다. 등록된 주소가 있으신가요, 아니면 새로 입력하시겠어요?"
U2_3 = "등록된 주소 없어요. 새로 입력할게요."
TC2a = tc("open_address_search", {})
TR2a = json.dumps({"status": "success", "message": "주소 검색 UI가 열렸습니다."}, ensure_ascii=False)
A2_4 = "주소 검색 화면을 열었습니다. 도로명 또는 건물명으로 수거지 주소를 검색하고 선택해주세요."
U2_5 = "서울 강남구 테헤란로 123 선택했어요."
TC2b = tc("register_return_request", {"order_id": "ORD-20260219-0002", "user_id": 1, "pickup_address": "서울 강남구 테헤란로 123", "confirmed": True})
TR2b = json.dumps({"status": "success", "message": "반품 신청이 완료되었습니다. 수거 예정일: 2026-02-21"}, ensure_ascii=False)
A2_6 = "반품 신청이 완료되었습니다. 수거 예정일은 2026년 2월 21일이며, 수거지는 서울 강남구 테헤란로 123입니다."

# 대화 기록 빌드 헬퍼
h2 = [
    {"role": "user", "content": U2_1},
    {"role": "assistant", "content": A2_1},
    {"role": "user", "content": U2_2},
    {"role": "assistant", "content": A2_2},
    {"role": "user", "content": U2_3},
]
h2_after_addr = h2 + [
    {"role": "assistant", "content": None, "tool_calls": TC2a},
    {"role": "tool", "tool_call_id": "random_id", "name": "open_address_search", "content": TR2a},
]
h2_after_comp = h2_after_addr + [
    {"role": "assistant", "content": A2_4},
    {"role": "user", "content": U2_5},
]
h2_after_ret = h2_after_comp + [
    {"role": "assistant", "content": None, "tool_calls": TC2b},
    {"role": "tool", "tool_call_id": "random_id", "name": "register_return_request", "content": TR2b},
]

d2 = {
    "dialog_num": 2, "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U2_1}],
         "ground_truth": {"role": "assistant", "content": A2_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": [{"role": "user", "content": U2_1}, {"role": "assistant", "content": A2_1}, {"role": "user", "content": U2_2}],
         "ground_truth": {"role": "assistant", "content": A2_2},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": list(h2),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 4, "serial_num": sn(),
         "query": list(h2_after_addr),
         "ground_truth": {"role": "assistant", "content": A2_4},
         "type_of_output": "completion", "acceptable_arguments": None},
        {"turn_num": 5, "serial_num": sn(),
         "query": list(h2_after_comp),
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2b},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 6, "serial_num": sn(),
         "query": list(h2_after_ret),
         "ground_truth": {"role": "assistant", "content": A2_6},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}

# ─── Dialog #3 ────────────────────────────────────────────────────────────────
# update_payment_method | 누락: order_id, payment_method
# [FAQ] 결제 관련 질문 말투
# ──────────────────────────────────────────────────────────────────────────────
U3_1 = "결제수단을 바꾸고 싶어요."
A3_1 = "어떤 주문의 결제수단을 어떤 방식으로 변경할까요? 주문번호와 변경할 결제수단(카드/계좌이체 등)을 알려주세요."
U3_2 = "ORD-20260219-0003이고, 카드로 변경해주세요."
TC3  = tc("update_payment_method", {"order_id": "ORD-20260219-0003", "user_id": 1, "payment_method": "카드"})
TR3  = json.dumps({"status": "success", "message": "결제수단이 카드로 변경되었습니다."}, ensure_ascii=False)
A3_3 = "결제수단이 카드로 변경되었습니다."

d3 = {
    "dialog_num": 3, "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U3_1}],
         "ground_truth": {"role": "assistant", "content": A3_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": [{"role": "user", "content": U3_1}, {"role": "assistant", "content": A3_1}, {"role": "user", "content": U3_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": [{"role": "user", "content": U3_1}, {"role": "assistant", "content": A3_1}, {"role": "user", "content": U3_2},
                   {"role": "assistant", "content": None, "tool_calls": TC3},
                   {"role": "tool", "tool_call_id": "random_id", "name": "update_payment_method", "content": TR3}],
         "ground_truth": {"role": "assistant", "content": A3_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}

# ─── Dialog #4 ────────────────────────────────────────────────────────────────
# cancel_order | 누락: order_id, reason
# [CSV] 의류 색상 변경 관련 발화 패턴 참조
# ──────────────────────────────────────────────────────────────────────────────
U4_1 = "주문 취소할래요."
A4_1 = "취소할 주문번호와 취소 사유를 알려주세요."
U4_2 = "ORD-20260219-0004요. 다른 색으로 다시 주문하려고요."
TC4  = tc("cancel_order", {"order_id": "ORD-20260219-0004", "user_id": 1, "reason": "다른 색으로 다시 주문하려고요"})
TR4  = json.dumps({"status": "success", "message": "주문이 취소되었습니다. 환불은 영업일 기준 3~5일 내 처리됩니다."}, ensure_ascii=False)
A4_3 = "주문이 취소되었습니다. 환불은 영업일 기준 3~5일 내 처리됩니다."

d4 = {
    "dialog_num": 4, "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U4_1}],
         "ground_truth": {"role": "assistant", "content": A4_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": [{"role": "user", "content": U4_1}, {"role": "assistant", "content": A4_1}, {"role": "user", "content": U4_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC4},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": [{"role": "user", "content": U4_1}, {"role": "assistant", "content": A4_1}, {"role": "user", "content": U4_2},
                   {"role": "assistant", "content": None, "tool_calls": TC4},
                   {"role": "tool", "tool_call_id": "random_id", "name": "cancel_order", "content": TR4}],
         "ground_truth": {"role": "assistant", "content": A4_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}

# ─── Dialog #5 ────────────────────────────────────────────────────────────────
# search_knowledge_base | 누락: 상황 정보 (배송 완료일, 상품 상태)
# [FAQ] 환불/청약철회 질문 말투  [TERMS] 청약철회 7일 조건
# ──────────────────────────────────────────────────────────────────────────────
U5_1 = "단순변심 환불 언제까지 돼요? 택도 안 뜯었는데요."
A5_1 = "환불(청약철회) 가능 기간은 배송 완료 시점과 상품 상태에 따라 달라요. 배송 완료일이 언제인지, 사용 또는 훼손 여부(라벨/포장 포함)를 확인해도 될까요?"
U5_2 = "어제 배송완료됐고, 라벨도 그대로고 포장만 열어봤어요."
TC5  = tc("search_knowledge_base", {"query": "단순변심 환불 가능 기간 배송완료 다음날 라벨 미훼손 포장 개봉", "category": "취소/반품/교환"})
TR5  = json.dumps({"results": [{"text": "전자상거래법에 따라 배송 완료 후 7일 이내 청약철회 가능. 라벨 미훼손·미사용 조건 충족 시 단순변심 반품 가능."}]}, ensure_ascii=False)
A5_3 = "전자상거래법에 따라 배송 완료 후 7일 이내에 청약철회가 가능합니다. 라벨이 그대로이고 사용하지 않으셨다면 단순변심 반품이 가능해요. 주문번호를 알려주시면 환불 가능 여부를 바로 확인해드릴까요?"

d5 = {
    "dialog_num": 5, "tools_count": len(tools_def), "tools": tools_def,
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U5_1}],
         "ground_truth": {"role": "assistant", "content": A5_1},
         "type_of_output": "slot", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": [{"role": "user", "content": U5_1}, {"role": "assistant", "content": A5_1}, {"role": "user", "content": U5_2}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC5},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 3, "serial_num": sn(),
         "query": [{"role": "user", "content": U5_1}, {"role": "assistant", "content": A5_1}, {"role": "user", "content": U5_2},
                   {"role": "assistant", "content": None, "tool_calls": TC5},
                   {"role": "tool", "tool_call_id": "random_id", "name": "search_knowledge_base", "content": TR5}],
         "ground_truth": {"role": "assistant", "content": A5_3},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}

# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
dialogs = [d1, d2, d3, d4, d5]

print(f"\n[3] JSONL 저장 → {OUTPUT_PATH}")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for d in dialogs:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print(f"  ✓ {len(dialogs)}개 다이얼로그, 총 {_serial}개 턴 저장 완료.")

# ─── 요약 출력 ────────────────────────────────────────────────────────────────
print("\n[4] 생성된 데이터셋 요약")
print(f"{'#':<3} {'turns':<6} {'누락 슬롯 패턴':<25} {'목표 툴'}")
print("-" * 80)
summary = [
    (1, 3, "주문번호",              "check_exchange_eligibility"),
    (2, 6, "주문번호 + 수거주소",    "open_address_search → register_return_request"),
    (3, 3, "주문번호 + 결제수단",    "update_payment_method"),
    (4, 3, "주문번호 + 취소사유",    "cancel_order"),
    (5, 3, "상황정보(배송일/상태)",  "search_knowledge_base"),
]
for num, turns, pattern, tool in summary:
    print(f"{num:<3} {turns:<6} {pattern:<25} {tool}")

print(f"\n출력 파일: {OUTPUT_PATH}")
