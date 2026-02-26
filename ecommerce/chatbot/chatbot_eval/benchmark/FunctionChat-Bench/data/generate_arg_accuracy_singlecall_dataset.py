"""
generate_arg_accuracy_singlecall_dataset.py

[목적]
이커머스 액션 기반 챗봇의 Argument Accuracy 평가를 위한 데이터셋 5개를 생성합니다.
FunctionChat-Bench 스타일의 JSONL 포맷으로 저장됩니다.

[데이터 소스별 활용]
A. 무신사 FAQ (musinsa_faq_20260203_162139_final.json)
   - 실제 사용자 말투/상황 → 질문 스타일 참조
B. 전자상거래 표준약관 (ecommerce_standard_preprocessed.json)
   - 환불·청약철회·교환 불가 사유 등 정책 조건 → eligibility 판단 인자 구성
C. AI Hub 패션/의류 CSV (패션_validation.csv, 의류_validation.csv)
   - 실제 상품 관련 발화문 → 상품 엔티티(상품명/옵션) 질문에 녹이기

[난이도 스펙트럼]
- 쉬움  (1개): ECOM_ARG_004 — update_payment_method (인자 명확)
- 중간  (2개): ECOM_ARG_002 — register_exchange_request (옵션 변경)
               ECOM_ARG_005 — create_review (rating/content 추출)
- 어려움(2개): ECOM_ARG_001 — check_refund_eligibility (약관 경계 조건 포함)
               ECOM_ARG_003 — register_return_request (UI 플로우 포함, 주소 미제공)
"""

import json
import os
import pandas as pd

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
from .paths import DATA_DIR, FAQ_PATH, TERMS_PATH, FASHION_CSV, CLOTHES_CSV, TOOLS_PATH
import os

OUTPUT_PATH    = DATA_DIR / "my_eval_arg_accuracy_singlecall_5.jsonl"

# ─── 소스 데이터 로드 및 참조 정보 추출 ──────────────────────────────────────

def load_faq_samples(path, categories=None, n=5):
    """무신사 FAQ에서 특정 카테고리의 질문-답변 스타일을 샘플링합니다."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    samples = []
    for item in data:
        payload = item.get("payload", {})
        if categories:
            if payload.get("main_category") in categories or payload.get("sub_category") in categories:
                samples.append({
                    "q": payload.get("question", ""),
                    "a": payload.get("answer", ""),
                    "category": payload.get("main_category", ""),
                })
        else:
            samples.append({
                "q": payload.get("question", ""),
                "a": payload.get("answer", ""),
                "category": payload.get("main_category", ""),
            })
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


# ─── 소스 참조 정보 수집 ──────────────────────────────────────────────────────
print("[1] 소스 데이터 로드 중...")

# A. 무신사 FAQ — 반품/교환/환불 카테고리 질문 스타일 참조
faq_refund_samples   = load_faq_samples(FAQ_PATH, categories=["취소/교환/반품", "배송"], n=10)
faq_review_samples   = load_faq_samples(FAQ_PATH, categories=["상품/AS 문의"], n=5)
faq_payment_samples  = load_faq_samples(FAQ_PATH, categories=["주문/결제"], n=5)

refund_styles = [s["q"] for s in faq_refund_samples][:3]
print(f"  • 무신사 FAQ 반품/교환 질문 스타일 예시: {refund_styles}")

# B. 전자상거래 표준약관 — 청약철회 관련 조항 참조
# 약관에서 반품/청약철회 관련 조항 검색 (실제 데이터에 '청약철회' 키워드가 있는 조항 탐색)
terms_text = load_terms_clause(TERMS_PATH, "청약철회") or load_terms_clause(TERMS_PATH, "반품") or load_terms_clause(TERMS_PATH, "취소")
terms_excerpt = terms_text[200:400] if len(terms_text) > 400 else terms_text
print(f"  • 약관 청약철회 조항 발췌: {terms_excerpt[:100]} ...")

# C. AI Hub CSV — 실제 발화문 참조
fashion_utt = load_csv_product(FASHION_CSV, row_idx=2)
clothes_utt = load_csv_product(CLOTHES_CSV, row_idx=10)
print(f"  • 패션 CSV 발화문 샘플: {fashion_utt}")
print(f"  • 의류 CSV 발화문 샘플: {clothes_utt}")

# ─── tools.json 로드 ──────────────────────────────────────────────────────────
with open(TOOLS_PATH, encoding="utf-8") as f:
    tools_def = json.load(f)

def get_tool_def(name):
    for t in tools_def:
        if t["function"]["name"] == name:
            return t
    return None

# ─── 5개 샘플 정의 ────────────────────────────────────────────────────────────
#
# 더미 ID 규칙 (FunctionChat-Bench Argument Accuracy용)
#   order_id   : ORD-20260219-000X  (오늘 날짜 대신 2026-02-19 고정)
#   product_id : P-000123 형태
#   user_id    : 1 (고정)
#
# 데이터 소스 활용 표시:
#   [FAQ]   : 무신사 FAQ의 질문 스타일/말투 반영
#   [TERMS] : 전자상거래 표준약관의 정책 조건 문구 반영
#   [CSV]   : AI Hub 패션/의류 CSV의 상품 엔티티(발화 컨텍스트) 반영
#
print("\n[2] 5개 샘플 생성 중...")

samples = [
    # ──────────────────────────────────────────────────────────────────────────
    # ECOM_ARG_001 | 어려움 | check_refund_eligibility
    # [FAQ]   무신사 FAQ 반품/환불 질문 말투 참조
    # [TERMS] 전자상거래표준약관 제17조(청약철회) — "수령한 날로부터 7일",
    #         "재화 등의 내용이 표시·광고 내용과 다른 경우" 조건 반영
    # ──────────────────────────────────────────────────────────────────────────
    {
        "function_num": 1,
        "function_name": "check_refund_eligibility",
        "query": [
            {
                "serial_num": 1,
                "content": (
                    "ORD-20260219-0001 주문 환불 가능한지 확인해줘. "
                    "그저께(2026-02-17) 받았는데 사이즈가 너무 작아서 단순변심으로 환불하고 싶어. "
                    "택 안 뜯었고 아직 입지도 않았어. "
                    "약관에 수령 후 7일 안에 청약철회 가능하다고 했는데 지금도 되는 거 맞지?"
                )
            }
        ],
        # [TERMS] 약관 제17조 조건: 단순변심, 수령 후 7일 이내, 미사용·미훼손
        "ground_truth": [
            {
                "serial_num": 1,
                "content": json.dumps(
                    {
                        "name": "check_refund_eligibility",
                        "arguments": {
                            "order_id": "ORD-20260219-0001",
                            "user_id": 1,
                            "reason": "단순변심",
                            "is_seller_fault": False
                        }
                    },
                    ensure_ascii=False
                )
            }
        ],
        "tools": [{"type": "exact", "content": tools_def}],
        "function_info": {
            "required_parameters_count": 4,
            "optional_parameters_count": 0,
            "parameter_type": ["string", "int", "string", "bool"],
            "extraction_type": "조건추출",
            "difficulty": "hard",
            "data_sources": ["FAQ(반품/환불 말투)", "TERMS(청약철회 7일 조건)"]
        },
        "acceptable_arguments": [{"serial_num": 1, "content": None}],
        "scenario_meta": {
            "scenario_id": "ECOM_ARG_001",
            "risk_type": "policy_boundary",
            "session_state": "logged_in",
            "expected_result": "allow",
            "note": "약관 기준 수령 후 7일 이내 + 미사용 → eligibility 충족 경계. reason 인자 추출 정확도 평가."
        }
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ECOM_ARG_002 | 중간 | register_exchange_request
    # [FAQ]   무신사 FAQ 교환 질문 말투 참조
    # [CSV]   의류 CSV 발화문 "지퍼가 안쪽으로 매 되어 있어 이상합니다" 컨텍스트 참조
    #         → 실제 상품 이상 발견 패턴 + 옵션 명시(블랙/M → 블랙/L) 반영
    # ──────────────────────────────────────────────────────────────────────────
    {
        "function_num": 2,
        "function_name": "register_exchange_request",
        "query": [
            {
                "serial_num": 2,
                "content": (
                    "ORD-20260219-0002에서 '오버핏 후드 집업' 교환 신청할래. "
                    "지금은 블랙/M인데 블랙/L로 바꾸고 싶어. "
                    "포장만 뜯었고 착용은 안 했어. 사이즈가 생각보다 작더라고."
                )
            }
        ],
        # [CSV] AI Hub 의류 CSV 옵션(색상/사이즈) 슬롯 참조
        "ground_truth": [
            {
                "serial_num": 2,
                "content": json.dumps(
                    {
                        "name": "register_exchange_request",
                        "arguments": {
                            "order_id": "ORD-20260219-0002",
                            "user_id": 1,
                            "reason": "사이즈가 생각보다 작음",
                            "new_option_id": None   # UI에서 옵션 선택 필요(교환 옵션 특정 불가)
                        }
                    },
                    ensure_ascii=False
                )
            }
        ],
        "tools": [{"type": "exact", "content": tools_def}],
        "function_info": {
            "required_parameters_count": 3,
            "optional_parameters_count": 1,
            "parameter_type": ["string", "int", "string", "null"],
            "extraction_type": "옵션추출",
            "difficulty": "medium",
            "data_sources": ["FAQ(교환 말투)", "CSV(의류 옵션 색상/사이즈 패턴)"]
        },
        "acceptable_arguments": [{"serial_num": 2, "content": None}],
        "scenario_meta": {
            "scenario_id": "ECOM_ARG_002",
            "risk_type": "option_change",
            "session_state": "logged_in",
            "expected_result": "allow",
            "note": "교환 신청 + 색상/사이즈 옵션 변경. new_option_id는 UI에서 선택해야 하므로 null 허용."
        }
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ECOM_ARG_003 | 어려움 | register_return_request (UI 플로우 포함)
    # [FAQ]   무신사 FAQ "반품 신청하는 방법" 말투 참조
    # [CSV]   패션 CSV 발화문 "신발 밑에 못 이 튀어나왔는데" 컨텍스트 참조
    #         → 실제 제품 하자 패턴 + 주소를 새로 입력해야 하는 상황
    # [TERMS] 청약철회 조건: 상품 하자(is_seller_fault=True)
    # ──────────────────────────────────────────────────────────────────────────
    {
        "function_num": 3,
        "function_name": "open_address_search",
        "query": [
            {
                "serial_num": 3,
                "content": (
                    "ORD-20260219-0003 반품 신청해줘. "
                    "신발(상품 P-000777) 밑창에서 이물질이 튀어나와 있어서 하자 반품이야. "
                    "수거 주소는 저장된 거 없어서 새로 입력할게."
                )
            }
        ],
        # 주소가 없으므로 → open_address_search 먼저 호출
        # (실제 에이전트 플로우: open_address_search → save_shipping_address_from_ui → register_return_request)
        "ground_truth": [
            {
                "serial_num": 3,
                "content": json.dumps(
                    {
                        "name": "open_address_search",
                        "arguments": {}
                    },
                    ensure_ascii=False
                )
            }
        ],
        "tools": [{"type": "exact", "content": tools_def}],
        "function_info": {
            "required_parameters_count": 0,
            "optional_parameters_count": 0,
            "parameter_type": [],
            "extraction_type": "UI트리거",
            "difficulty": "hard",
            "data_sources": [
                "FAQ(반품 신청 말투)",
                "CSV(패션 — 신발 하자 발화 패턴)",
                "TERMS(청약철회, 상품 하자 → is_seller_fault=True)"
            ]
        },
        "acceptable_arguments": [{"serial_num": 3, "content": None}],
        "scenario_meta": {
            "scenario_id": "ECOM_ARG_003",
            "risk_type": "ui_flow",
            "session_state": "logged_in",
            "expected_result": "needs_address_ui",
            "note": (
                "주소 미등록 → open_address_search 먼저 호출해야 함. "
                "에이전트가 '수거 주소 없음'을 감지하고 UI 트리거를 1번째 스텝으로 선택하는지 평가."
            )
        }
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ECOM_ARG_004 | 쉬움 | update_payment_method
    # [FAQ]   무신사 FAQ 결제 관련 질문 말투 참조
    # ──────────────────────────────────────────────────────────────────────────
    {
        "function_num": 4,
        "function_name": "update_payment_method",
        "query": [
            {
                "serial_num": 4,
                "content": (
                    "ORD-20260219-0004 결제수단을 카드로 바꿔줘. "
                    "지금은 계좌이체로 되어 있는데 신용카드로 변경하고 싶어."
                )
            }
        ],
        "ground_truth": [
            {
                "serial_num": 4,
                "content": json.dumps(
                    {
                        "name": "update_payment_method",
                        "arguments": {
                            "order_id": "ORD-20260219-0004",
                            "user_id": 1,
                            "payment_method": "신용카드"
                        }
                    },
                    ensure_ascii=False
                )
            }
        ],
        "tools": [{"type": "exact", "content": tools_def}],
        "function_info": {
            "required_parameters_count": 3,
            "optional_parameters_count": 0,
            "parameter_type": ["string", "int", "string"],
            "extraction_type": "단순추출",
            "difficulty": "easy",
            "data_sources": ["FAQ(결제 관련 질문 말투)"]
        },
        "acceptable_arguments": [{"serial_num": 4, "content": None}],
        "scenario_meta": {
            "scenario_id": "ECOM_ARG_004",
            "risk_type": "payment_change",
            "session_state": "logged_in",
            "expected_result": "allow",
            "note": "인자 3개(order_id, user_id, payment_method) 추출 명확. 정확도 측정 기준점(baseline) 역할."
        }
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ECOM_ARG_005 | 중간 | create_review
    # [FAQ]   무신사 FAQ 리뷰 관련 질문 말투 참조
    # [CSV]   패션 CSV 발화문 슬롯 참조 → 코트/봄 아이템 관련 자연스러운 리뷰 문구 반영
    # ──────────────────────────────────────────────────────────────────────────
    {
        "function_num": 5,
        "function_name": "create_review",
        "query": [
            {
                "serial_num": 5,
                "content": (
                    "ORD-20260219-0005에 있는 상품 P-000321 리뷰 남길래. "
                    "별점 5점 주고, \"배송 빠르고 핏이 예뻐요. 봄에 입기 딱 좋네요\" 이렇게 써줘."
                )
            }
        ],
        # [CSV] AI Hub 패션 CSV 계절/소재/핏 언급 발화 패턴 참조
        "ground_truth": [
            {
                "serial_num": 5,
                "content": json.dumps(
                    {
                        "name": "create_review",
                        "arguments": {
                            "order_id": "ORD-20260219-0005",
                            "product_id": "P-000321",
                            "user_id": 1,
                            "rating": 5,
                            "content": "배송 빠르고 핏이 예뻐요. 봄에 입기 딱 좋네요"
                        }
                    },
                    ensure_ascii=False
                )
            }
        ],
        "tools": [{"type": "exact", "content": tools_def}],
        "function_info": {
            "required_parameters_count": 5,
            "optional_parameters_count": 0,
            "parameter_type": ["string", "string", "int", "int", "string"],
            "extraction_type": "복합추출",
            "difficulty": "medium",
            "data_sources": ["FAQ(리뷰 말투)", "CSV(패션 — 계절/핏 발화 패턴)"]
        },
        "acceptable_arguments": [{"serial_num": 5, "content": None}],
        "scenario_meta": {
            "scenario_id": "ECOM_ARG_005",
            "risk_type": "ugc_write",
            "session_state": "logged_in",
            "expected_result": "allow",
            "note": "product_id·rating·content 동시 추출. 인용 문자열 처리 정확도 확인."
        }
    }
]

# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
print(f"\n[3] JSONL 저장 → {OUTPUT_PATH}")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for sample in samples:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")

print(f"  ✓ {len(samples)}개 샘플 저장 완료.")

# ─── 콘솔 요약 출력 ───────────────────────────────────────────────────────────
print("\n[4] 생성된 데이터셋 요약")
print(f"{'#':<4} {'scenario_id':<15} {'tool':<30} {'difficulty':<8} {'data_sources'}")
print("-" * 100)
for s in samples:
    meta = s["scenario_meta"]
    info = s["function_info"]
    print(
        f"{s['function_num']:<4} "
        f"{meta['scenario_id']:<15} "
        f"{s['function_name']:<30} "
        f"{info['difficulty']:<8} "
        f"{', '.join(info['data_sources'])}"
    )

print(f"\n출력 파일: {OUTPUT_PATH}")
