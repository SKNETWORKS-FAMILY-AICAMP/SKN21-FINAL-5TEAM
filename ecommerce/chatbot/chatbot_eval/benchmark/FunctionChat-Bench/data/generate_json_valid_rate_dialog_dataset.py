"""
generate_json_valid_rate_dialog_dataset.py

[목적]
이커머스 액션 기반 챗봇의 JSON Valid Rate 평가를 위한 Dialog 데이터셋 10개를 생성합니다.
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

[10개 시나리오 — JSON 유효성 엣지케이스별 분류]
- Dialog #1 : 따옴표 이스케이프  — create_review (content 내 큰따옴표 \" 처리)
- Dialog #2 : 배열 타입 인자     — generate_review_draft (keywords 배열 3개 항목)
- Dialog #3 : 빈 객체 인자       — open_address_search ({} 빈 arguments)
- Dialog #4 : boolean false      — check_refund_eligibility (is_seller_fault=false)
- Dialog #5 : boolean true       — register_return_request (confirmed=true)
- Dialog #6 : null 값 인자       — register_exchange_request (new_option_id=null)
- Dialog #7 : 정수형 인자        — register_used_sale (expected_price=75000)
- Dialog #8 : URL 포함 문자열    — search_by_image (슬래시·콜론·점 포함 URL)
- Dialog #9 : 장문 문자열        — create_review (100자 이상 content)
- Dialog #10: 한글+영문 혼합     — search_products_vector (Unicode 복합 검색어)
"""

import json
import os
import pandas as pd

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
from .paths import DATA_DIR, FAQ_PATH, TERMS_PATH, FASHION_CSV, CLOTHES_CSV, TOOLS_PATH

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


# ─── Dialog #1 ────────────────────────────────────────────────────────────────
# 따옴표 이스케이프 | create_review
# JSON 엣지케이스: content 내 큰따옴표 → \" 이스케이프 처리
# ──────────────────────────────────────────────────────────────────────────────
print("\n[2] Dialog 생성 중...")

U1_1 = 'ORD-20260219-0003 리뷰 남겨줘. 별점 5점에 내용은 착용감이 "최고"예요. 색감도 "사진보다 예뻐요"라고 써줘.'
TC1a = tc("create_review", {
    "order_id": "ORD-20260219-0003",
    "user_id": 1,
    "rating": 5,
    "content": '착용감이 "최고"예요. 색감도 "사진보다 예뻐요"'
})
TR1a = json.dumps({"success": True, "message": "리뷰가 성공적으로 등록되었습니다.", "review_id": 101}, ensure_ascii=False)
A1_2 = "리뷰가 성공적으로 등록되었습니다. 소중한 후기 감사드립니다!"

h1_1 = [
    {"role": "user",      "content": U1_1},
    {"role": "assistant", "content": None, "tool_calls": TC1a},
    {"role": "tool",      "name": "create_review", "content": TR1a},
]

d1 = {
    "dialog_num": 1, "dialog_name": "따옴표 이스케이프 — 리뷰 등록",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "quote_escape",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U1_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC1a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h1_1),
         "ground_truth": {"role": "assistant", "content": A1_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #2 ────────────────────────────────────────────────────────────────
# 배열 타입 인자 | generate_review_draft
# JSON 엣지케이스: keywords 배열 → ["착용감", "색감", "가성비"]
# ──────────────────────────────────────────────────────────────────────────────
U2_1 = "오버핏 후드집업 리뷰 초안 만들어줘. 만족도는 높음이고 키워드는 착용감, 색감, 가성비야."
TC2a = tc("generate_review_draft", {
    "product_name": "오버핏 후드집업 그레이 L",
    "satisfaction": "높음",
    "keywords": ["착용감", "색감", "가성비"]
})
TR2a = json.dumps({
    "success": True,
    "drafts": {
        "short": "착용감, 색감, 가성비 모두 만족!",
        "emotional": "이 가격에 이 퀄리티라니, 정말 만족스러운 후드집업이에요.",
        "detailed": "착용감 좋음. 색감 선명. 가성비 우수. 재구매 의사 있음."
    },
    "message": "리뷰 초안이 생성되었습니다."
}, ensure_ascii=False)
A2_2 = (
    "리뷰 초안 3가지를 생성했습니다.\n"
    "1. 짧은: 착용감, 색감, 가성비 모두 만족!\n"
    "2. 감성적: 이 가격에 이 퀄리티라니, 정말 만족스러운 후드집업이에요.\n"
    "3. 무뚝뚝: 착용감 좋음. 색감 선명. 가성비 우수. 재구매 의사 있음.\n"
    "마음에 드시는 버전을 선택해주세요."
)

h2_1 = [
    {"role": "user",      "content": U2_1},
    {"role": "assistant", "content": None, "tool_calls": TC2a},
    {"role": "tool",      "name": "generate_review_draft", "content": TR2a},
]

d2 = {
    "dialog_num": 2, "dialog_name": "배열 타입 인자 — 리뷰 초안",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "array_argument",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U2_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC2a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h2_1),
         "ground_truth": {"role": "assistant", "content": A2_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #3 ────────────────────────────────────────────────────────────────
# 빈 객체 인자 ({}) | open_address_search
# JSON 엣지케이스: arguments = {} (인자가 없는 빈 객체)
# ──────────────────────────────────────────────────────────────────────────────
U3_1 = "반품할게요. 저장된 수거 주소가 없어서 새로 입력할게요."
TC3a = tc("open_address_search", {})
TR3a = json.dumps({"ui_action": "show_address_search", "message": "주소 검색 버튼을 눌러주세요."}, ensure_ascii=False)
A3_2 = "주소 검색 화면을 열었습니다. 수거지 주소를 검색하고 선택해주세요."

h3_1 = [
    {"role": "user",      "content": U3_1},
    {"role": "assistant", "content": None, "tool_calls": TC3a},
    {"role": "tool",      "name": "open_address_search", "content": TR3a},
]

d3 = {
    "dialog_num": 3, "dialog_name": "빈 객체 인자 — 주소 검색",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "empty_object",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U3_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC3a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h3_1),
         "ground_truth": {"role": "assistant", "content": A3_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #4 ────────────────────────────────────────────────────────────────
# boolean false | check_refund_eligibility
# JSON 엣지케이스: is_seller_fault=False (boolean false 직렬화 → false)
# ──────────────────────────────────────────────────────────────────────────────
U4_1 = "ORD-20260219-0001 환불 가능한지 확인해줘. 단순변심이야. 제품 하자는 아니야."
TC4a = tc("check_refund_eligibility", {
    "order_id": "ORD-20260219-0001",
    "user_id": 1,
    "reason": "단순변심",
    "is_seller_fault": False
})
TR4a = json.dumps({
    "eligible": True,
    "final_refund_amount": 59000,
    "message": "환불 가능합니다. 수령 후 7일 이내이며 상품 상태 양호."
}, ensure_ascii=False)
A4_2 = "환불이 가능합니다. 예상 환불액은 59,000원입니다. 반품 신청을 진행하시겠어요?"

h4_1 = [
    {"role": "user",      "content": U4_1},
    {"role": "assistant", "content": None, "tool_calls": TC4a},
    {"role": "tool",      "name": "check_refund_eligibility", "content": TR4a},
]

d4 = {
    "dialog_num": 4, "dialog_name": "boolean false — 환불 자격 확인",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "boolean_false",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U4_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC4a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h4_1),
         "ground_truth": {"role": "assistant", "content": A4_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #5 ────────────────────────────────────────────────────────────────
# boolean true | register_return_request
# JSON 엣지케이스: confirmed=True (boolean true 직렬화 → true)
# ──────────────────────────────────────────────────────────────────────────────
U5_1 = "ORD-20260219-0005 반품 신청할게요. 수거지는 서울 송파구 올림픽로 300이에요. 확인했어요."
TC5a = tc("register_return_request", {
    "order_id": "ORD-20260219-0005",
    "user_id": 1,
    "pickup_address": "서울 송파구 올림픽로 300",
    "confirmed": True
})
TR5a = json.dumps({"status": "success", "message": "반품 접수가 완료되었습니다. 수거 예정일: 2026-03-08"}, ensure_ascii=False)
A5_2 = "반품 접수가 완료되었습니다. 수거 예정일은 2026년 3월 8일이며, 수거지는 서울 송파구 올림픽로 300입니다."

h5_1 = [
    {"role": "user",      "content": U5_1},
    {"role": "assistant", "content": None, "tool_calls": TC5a},
    {"role": "tool",      "name": "register_return_request", "content": TR5a},
]

d5 = {
    "dialog_num": 5, "dialog_name": "boolean true — 반품 신청",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "boolean_true",
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
# null 값 인자 | register_exchange_request
# JSON 엣지케이스: new_option_id=None → null (JSON null 직렬화)
# ──────────────────────────────────────────────────────────────────────────────
U6_1 = "ORD-20260219-0006 교환 신청할게요. 사이즈가 작아요. 수거지는 서울 마포구 홍익로 20이고, 새 옵션은 나중에 선택할게요."
TC6a = tc("register_exchange_request", {
    "order_id": "ORD-20260219-0006",
    "user_id": 1,
    "reason": "사이즈가 작아요",
    "pickup_address": "서울 마포구 홍익로 20",
    "confirmed": True,
    "new_option_id": None
})
TR6a = json.dumps({"status": "success", "message": "교환 접수가 완료되었습니다. 수거 예정일: 2026-03-09"}, ensure_ascii=False)
A6_2 = "교환 접수가 완료되었습니다. 수거 예정일은 2026년 3월 9일이며, 새 옵션은 수거 후 선택 가능합니다."

h6_1 = [
    {"role": "user",      "content": U6_1},
    {"role": "assistant", "content": None, "tool_calls": TC6a},
    {"role": "tool",      "name": "register_exchange_request", "content": TR6a},
]

d6 = {
    "dialog_num": 6, "dialog_name": "null 값 인자 — 교환 신청",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "null_value",
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
# 정수형 인자 | register_used_sale
# JSON 엣지케이스: expected_price=75000 (integer 타입 — 문자열 아닌 숫자)
# ──────────────────────────────────────────────────────────────────────────────
U7_1 = "나이키 에어맥스 중고로 팔고 싶어요. 상태는 '상'이고 희망가는 75,000원이에요."
TC7a = tc("register_used_sale", {
    "category": "신발",
    "item_name": "나이키 에어맥스",
    "condition": "상",
    "expected_price": 75000,
    "user_id": 1
})
TR7a = json.dumps({
    "success": True,
    "tracking_id": "USED-N1K3A1R2",
    "message": "'나이키 에어맥스' 중고 판매가 접수되었습니다. (희망가: 75000)",
    "next_steps": "검수 센터로 상품을 보내주시거나 수거 신청(request_pickup)을 진행해주세요."
}, ensure_ascii=False)
A7_2 = "중고 판매 신청이 완료되었습니다. 접수 번호는 USED-N1K3A1R2입니다. 수거 신청을 진행하시겠어요?"

h7_1 = [
    {"role": "user",      "content": U7_1},
    {"role": "assistant", "content": None, "tool_calls": TC7a},
    {"role": "tool",      "name": "register_used_sale", "content": TR7a},
]

d7 = {
    "dialog_num": 7, "dialog_name": "정수형 인자 — 중고 판매 신청",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "integer_argument",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U7_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC7a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h7_1),
         "ground_truth": {"role": "assistant", "content": A7_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #8 ────────────────────────────────────────────────────────────────
# URL 포함 문자열 | search_by_image
# JSON 엣지케이스: image_url — 슬래시(/)·콜론(:)·점(.)·하이픈(-) 등 특수문자 포함 URL
# ──────────────────────────────────────────────────────────────────────────────
U8_1 = "이 이미지랑 비슷한 옷 찾아줘. https://img.musinsa.com/sample/winter_coat_2026.jpg"
TC8a = tc("search_by_image", {
    "image_url": "https://img.musinsa.com/sample/winter_coat_2026.jpg"
})
TR8a = json.dumps({
    "success": True,
    "message": "유사 상품 3개를 찾았습니다.",
    "ui_action": "show_product_list",
    "ui_data": [
        {"id": 55001, "name": "Wool Blend Coat Camel M", "price": 89000},
        {"id": 55002, "name": "Oversized Trench Coat Beige L", "price": 95000},
        {"id": 55003, "name": "Double Breasted Coat Navy M", "price": 102000}
    ]
}, ensure_ascii=False)
A8_2 = "이미지 속 코트와 유사한 상품 3개를 찾았습니다. 마음에 드시는 상품이 있으신가요?"

h8_1 = [
    {"role": "user",      "content": U8_1},
    {"role": "assistant", "content": None, "tool_calls": TC8a},
    {"role": "tool",      "name": "search_by_image", "content": TR8a},
]

d8 = {
    "dialog_num": 8, "dialog_name": "URL 포함 문자열 — 이미지 검색",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "url_string",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U8_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC8a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h8_1),
         "ground_truth": {"role": "assistant", "content": A8_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #9 ────────────────────────────────────────────────────────────────
# 장문 문자열 | create_review
# JSON 엣지케이스: content 필드에 100자 이상의 긴 문자열 (줄바꿈 없는 단일 문자열)
# ──────────────────────────────────────────────────────────────────────────────
LONG_REVIEW = (
    "배송이 정말 빠르게 왔고 포장도 꼼꼼했어요. "
    "옷의 소재가 사진보다 훨씬 좋아서 깜짝 놀랐습니다. "
    "착용감이 부드럽고 핏이 예뻐서 여러 번 입고 싶은 옷이에요. "
    "색감도 선명하고 세탁 후에도 변색이 없어서 매우 만족합니다. "
    "다음에도 이 브랜드 제품을 구매할 의사가 있습니다. 강력 추천드려요!"
)

U9_1 = f"ORD-20260219-0003 리뷰 남겨줘. 별점 5점에 내용은 다음과 같아: {LONG_REVIEW}"
TC9a = tc("create_review", {
    "order_id": "ORD-20260219-0003",
    "user_id": 1,
    "rating": 5,
    "content": LONG_REVIEW
})
TR9a = json.dumps({"success": True, "message": "리뷰가 성공적으로 등록되었습니다.", "review_id": 202}, ensure_ascii=False)
A9_2 = "리뷰가 성공적으로 등록되었습니다. 소중한 후기 감사드립니다!"

h9_1 = [
    {"role": "user",      "content": U9_1},
    {"role": "assistant", "content": None, "tool_calls": TC9a},
    {"role": "tool",      "name": "create_review", "content": TR9a},
]

d9 = {
    "dialog_num": 9, "dialog_name": "장문 문자열 — 리뷰 등록",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "long_string",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U9_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC9a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h9_1),
         "ground_truth": {"role": "assistant", "content": A9_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── Dialog #10 ───────────────────────────────────────────────────────────────
# 한글+영문 혼합 Unicode | search_products_vector
# JSON 엣지케이스: query 필드에 한글+영문 혼합 Unicode (ensure_ascii=False 직렬화 검증)
# ──────────────────────────────────────────────────────────────────────────────
U10_1 = "파란색 blue 청바지 denim jeans 찾아줘."
TC10a = tc("search_products_vector", {
    "query": "파란색 blue 청바지 denim jeans",
    "limit": 5
})
TR10a = json.dumps({
    "message": "검색 결과 3개입니다.",
    "ui_action": "show_product_list",
    "ui_data": [
        {"id": 33001, "name": "Levi's Men Blue Denim Jeans", "price": 59000},
        {"id": 33002, "name": "청바지 슬림핏 인디고 M", "price": 49000},
        {"id": 33003, "name": "Calvin Klein Blue Jeans Regular", "price": 75000}
    ],
    "requires_selection": False
}, ensure_ascii=False)
A10_2 = "파란색 청바지(denim jeans) 3개를 찾았습니다. 마음에 드시는 상품이 있으신가요?"

h10_1 = [
    {"role": "user",      "content": U10_1},
    {"role": "assistant", "content": None, "tool_calls": TC10a},
    {"role": "tool",      "name": "search_products_vector", "content": TR10a},
]

d10 = {
    "dialog_num": 10, "dialog_name": "한글+영문 혼합 Unicode — 벡터 검색",
    "tools_count": len(tools_def), "tools": tools_def,
    "json_edge_case": "unicode_mixed",
    "turns": [
        {"turn_num": 1, "serial_num": sn(),
         "query": [{"role": "user", "content": U10_1}],
         "ground_truth": {"role": "assistant", "content": None, "tool_calls": TC10a},
         "type_of_output": "call", "acceptable_arguments": None},
        {"turn_num": 2, "serial_num": sn(),
         "query": list(h10_1),
         "ground_truth": {"role": "assistant", "content": A10_2},
         "type_of_output": "completion", "acceptable_arguments": None},
    ]
}


# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
dialogs = [d1, d2, d3, d4, d5, d6, d7, d8, d9, d10]

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
