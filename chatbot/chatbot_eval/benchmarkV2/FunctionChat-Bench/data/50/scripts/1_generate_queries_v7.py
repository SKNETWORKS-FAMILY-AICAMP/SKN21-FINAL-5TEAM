"""
generate_queries_v7.py
[목적]
order_intent_router 툴 호출 정확도 평가용 질문 데이터셋 50개를 생성합니다.
- 평가 대상 툴: get_user_orders, cancel, refund, exchange, change_option (5개)
- shipping 관련 질문은 절대 생성하지 않습니다.
- 단일턴(single-turn), 단일툴(single-tool) 호출 평가 전용입니다.
- 평가 지표는 툴 이름 정확도만 봅니다. argument 정확도는 평가하지 않습니다.
- 질문은 모두 한국어 구어체 사용자 발화로 작성됩니다.
- 실제 DB에서 조회한 user_id / order_id를 사용합니다.
- 결과는 JSON 형식으로 저장합니다.
"""

import csv
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

# 프로젝트 루트 및 데이터 경로 설정
current_dir = Path(__file__).resolve().parent
# paths.py가 있는 data/ 폴더를 path에 추가
data_root = current_dir.parent.parent
if str(data_root) not in sys.path:
    sys.path.insert(0, str(data_root))

from paths import PROJECT_ROOT
from model_config import DEFAULT_MODEL

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT))

from ecommerce.backend.app.database import SessionLocal
import ecommerce.backend.app.models  # noqa: F401  # mapper 초기화용
from ecommerce.backend.app.router.users.crud import get_user_by_email
from ecommerce.backend.app.router.orders.crud import get_orders_by_user_id

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = DEFAULT_MODEL

# 50개 전용 데이터 폴더 (data/50/data/)
DATA_DIR_50 = current_dir.parent / "data"
OUTPUT_JSONL_PATH = DATA_DIR_50 / "1_questions_raw.jsonl"
TARGET_USER_COUNT = 3
SAMPLES_PER_SCENARIO = 10
MAX_ATTEMPTS_PER_SCENARIO = 80

# ============================================================
# 평가 대상 5개 시나리오 (shipping 제외)
# ============================================================
SCENARIOS = [
    {
        "id": 1,
        "name": "주문 내역 조회",
        "expected_tool": "get_user_orders",
        "action": "get_user_orders",
        "tools": ["get_user_orders"],
        "possible": True,
        "required_status": [],           # 상태 무관
        "include_order": False,          # 주문번호 불포함
        "account_roles": ["pre_delivery", "delivered", "mixed"],
    },
    {
        "id": 2,
        "name": "주문 취소",
        "expected_tool": "cancel",
        "action": "cancel",
        "tools": ["cancel"],
        "possible": True,
        "required_status": ["paid", "preparing"],
        "include_order": True,
        "account_roles": ["pre_delivery"],
    },
    {
        "id": 3,
        "name": "환불/반품 신청",
        "expected_tool": "refund",
        "action": "refund",
        "tools": ["refund"],
        "possible": True,
        "required_status": ["shipped", "delivered"],
        "include_order": True,
        "account_roles": ["delivered"],
    },
    {
        "id": 4,
        "name": "교환 신청",
        "expected_tool": "exchange",
        "action": "exchange",
        "tools": ["exchange"],
        "possible": True,
        "required_status": ["shipped", "delivered"],
        "include_order": True,
        "account_roles": ["delivered"],
    },
    {
        "id": 5,
        "name": "옵션 변경",
        "expected_tool": "change_option",
        "action": "change_option",
        "tools": ["change_option"],
        "possible": True,
        "required_status": ["paid", "preparing"],
        "include_order": True,
        "account_roles": ["pre_delivery"],
    },
]

# ============================================================
# 혼동쌍 (Confusion Pairs) — 함정 유형과 연결
# ============================================================
CONFUSION_PAIRS = {
    "cancel": "refund",
    "refund": "cancel",
    "exchange": "change_option",
    "change_option": "exchange",
    "get_user_orders": "cancel",
}

# ============================================================
# 함정 유형(trap_type) 정의 — 시나리오별 적용 가능 유형
# ============================================================
TRAP_TYPES = {
    "get_user_orders": ["no_order_id", "mixed_signal_but_single_tool"],
    "cancel": ["cancel_vs_refund", "final_intent_reversal", "reason_based_inference"],
    "refund": ["cancel_vs_refund", "reason_based_inference", "mixed_signal_but_single_tool"],
    "exchange": ["exchange_vs_change_option", "reason_based_inference", "final_intent_reversal"],
    "change_option": ["exchange_vs_change_option", "reason_based_inference", "mixed_signal_but_single_tool"],
}

# ============================================================
# 시나리오별 Hard 템플릿 (LLM 참고용)
# ============================================================
HARD_TEMPLATE_FAMILIES = {
    "get_user_orders": [
        "주문번호를 몰라서 최근 주문내역부터 보여주세요.",
        "환불하려는데 주문번호를 모르겠어서 목록부터 보고 싶어요.",
        "취소하려는 주문 찾으려고 최근 주문 리스트부터 볼게요.",
        "제가 최근에 주문한 것들부터 먼저 보고 싶어요.",
    ],
    "cancel": [
        "{ORDER_ID} 아직 배송 전이면 취소하고 싶어요.",
        "반품 말고 {ORDER_ID} 주문 자체를 취소하고 싶어요.",
        "이미 보낸 거 아니면 {ORDER_ID} 취소해주세요.",
        "환불 말고 {ORDER_ID} 그냥 취소할게요.",
    ],
    "refund": [
        "취소는 아니고 {ORDER_ID} 받은 상품 반품하고 싶어요.",
        "교환 말고 {ORDER_ID} 환불할게요.",
        "{ORDER_ID} 그냥 돌려보내고 싶어요.",
        "이미 받은 {ORDER_ID} 상품이라 취소 말고 반품으로 하고 싶어요.",
    ],
    "exchange": [
        "반품 말고 {ORDER_ID} 다른 사이즈로 바꾸고 싶어요.",
        "{ORDER_ID} 받은 거 교환하고 싶어요. 환불은 아니에요.",
        "{ORDER_ID} 같은 상품 색상만 바꿔서 다시 받고 싶어요.",
        "돈으로 돌려받는 건 말고 {ORDER_ID} 교환해주세요.",
    ],
    "change_option": [
        "{ORDER_ID} 아직 안 보내셨으면 사이즈만 M으로 바꿔주세요.",
        "교환 말고 {ORDER_ID} 옵션만 변경하고 싶어요. 아직 배송 전이잖아요.",
        "{ORDER_ID} 색상을 블랙으로 바꿀 수 있나요? 아직 준비 중이라면요.",
        "배송 전이면 {ORDER_ID} 사이즈만 변경해주세요.",
    ],
}

# ============================================================
# 시나리오별 핵심 키워드 (검증용)
# ============================================================
SCENARIO_KEYWORDS = {
    "get_user_orders": [
        "주문내역", "주문 목록", "리스트", "최근 주문", "주문한", "주문 기록", "산 거",
        "주문한 것들", "구매 내역", "어떤 주문", "번호를 몰", "번호 모르",
        "목록", "내역", "주문번호를 몰",
    ],
    "cancel": [
        "취소", "안 받을", "배송 전", "안 나갔", "안 보낸", "보내기 전", "포장 시작 전",
        "준비 중", "출고 전", "발송 전", "포기할래", "잘못 주문", "실수로 주문",
    ],
    "refund": [
        "환불", "반품", "돌려보내", "반송", "반납", "돌려주", "돈 돌려받", "되돌려",
        "받은 거 돌려", "상품 반납", "파손", "불량", "오배송", "설명이랑 다",
    ],
    "exchange": [
        "교환", "바꾸", "다른 사이즈", "다른 색상", "같은 상품", "다시 받고",
        "교환 접수", "교환해",
    ],
    "change_option": [
        "옵션 변경", "옵션만", "사이즈 변경", "사이즈만", "색상 변경", "색상만",
        "바꿔주", "변경해", "옵션을 바꾸", "배송 전", "아직 안 보낸",
    ],
}

# ============================================================
# Hard 신호 키워드 (검증: 질문이 "어려운" 발화인지 확인)
# ============================================================
HARD_SIGNAL_KEYWORDS = [
    "말고", "아니고", "일단", "먼저", "안 받을", "돌려보내", "다시 받고", "배송 전",
    "목록", "리스트", "바꾸고", "반품", "환불", "취소", "안 보낸", "발송 전",
    "준비 중", "출고 전", "도착", "돈 돌려받", "반납", "주문 기록",
    "파손", "불량", "잘못", "실수", "오배송", "옵션만", "사이즈만", "색상만",
    "모르겠", "몰라서", "아직",
]

# ============================================================
# 혼동 신호 키워드 (검증: 함정 유도 신호가 포함되었는지)
# ============================================================
CONFUSION_SIGNAL_KEYWORDS = {
    "cancel": ["환불", "반품", "돌려보내", "돌려주", "돈 돌려받", "반품 말고", "환불 말고", "파손", "불량"],
    "refund": ["취소", "안 나갔", "안 보낸", "발송 전", "출고 전", "준비 중", "취소는 아니고", "취소 말고"],
    "exchange": ["옵션 변경", "옵션만", "사이즈만", "색상만", "배송 전", "반품 말고", "환불 말고"],
    "change_option": ["교환", "바꾸", "다른 사이즈", "다른 색상", "반품", "환불", "교환 말고"],
    "get_user_orders": ["취소", "환불", "교환", "반품", "취소하려는", "환불하려는", "교환하려는"],
}

# ============================================================
# 생성 금지 패턴
# ============================================================
FORBIDDEN_LONG_ARG_PATTERNS = [
    "배송 예정일", "언제 도착", "어제", "오늘까지", "내일까지",
    "상세", "정확한", "택배", "송장", "배송조회", "배송 상태", "배송 현황",
    "지금 어디", "출발했", "배송 추적",
]

FORBIDDEN_SHIPPING_PATTERNS = [
    "배송 조회", "배송조회", "택배", "송장", "배송 상태", "배송상태",
    "배송 현황", "배송현황", "배송 추적", "배송추적", "지금 어디쯤",
    "어디쯤", "도착 예정", "도착예정", "출발했", "이동 중",
]


# ============================================================
# DB 관련 유틸리티
# ============================================================
def load_eval_users() -> list[dict[str, Any]]:
    path = PROJECT_ROOT / "chatbot/chatbot_eval/benchmark/eval_data.jsonl"
    users: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("type") != "user":
                    continue
                email = item.get("data", {}).get("user_email")
                if not email or email in seen:
                    continue
                seen.add(email)
                users.append({"email": email})
    except Exception as e:
        print(f"[WARN] eval_data.jsonl 읽기 실패: {e}")
    return users


def load_tools() -> list[dict[str, Any]]:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_csv_samples(path: Path, n: int = 100) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
                if len(rows) >= n:
                    break
    except Exception as e:
        print(f"[WARN] CSV 로드 실패 ({path.name}): {e}")
    return rows


def get_real_orders_with_status(user_email: str) -> tuple[Optional[int], list[dict[str, Any]]]:
    result: list[dict[str, Any]] = []
    session = SessionLocal()
    try:
        from datetime import datetime

        user = get_user_by_email(session, user_email)
        if not user:
            print(f"[WARN] DB에 사용자가 없음: {user_email}")
            return None, []

        user_id = int(user.id)
        orders, _ = get_orders_by_user_id(session, user_id, limit=100)
        for o in orders:
            delivered_at = None
            if getattr(o, "shipping_info", None):
                delivered_at = getattr(o.shipping_info, "delivered_at", None)
            days_since = None
            if delivered_at:
                days_since = (datetime.now() - delivered_at).days
            status_value = getattr(o.status, "value", o.status)
            result.append(
                {
                    "order_id": o.order_number,
                    "status": str(status_value).lower(),
                    "shipping_fee": float(o.shipping_fee) if o.shipping_fee is not None else 0.0,
                    "days_since_delivery": days_since,
                }
            )
        return user_id, result
    except Exception as e:
        print(f"[ERROR] ORM DB 조회 실패 ({user_email}): {e}")
        return None, []
    finally:
        session.close()


def select_users_from_db(raw_users: list[dict[str, Any]], target_count: int = TARGET_USER_COUNT) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for raw_user in raw_users:
        real_user_id, orders = get_real_orders_with_status(raw_user["email"])
        if real_user_id is None or not orders:
            continue
        if real_user_id in seen_ids:
            continue
        seen_ids.add(real_user_id)
        candidates.append(
            {
                "user_id": real_user_id,
                "email": raw_user["email"],
                "orders": orders,
            }
        )

    if len(candidates) < target_count:
        raise RuntimeError(
            f"실제 주문이 있는 DB 사용자 수가 부족합니다. 필요={target_count}, 확보={len(candidates)}"
        )

    return candidates[:target_count]


# ============================================================
# 시나리오용 주문 필터링 & Account Role 결정
# ============================================================
def filter_orders_for_scenario(orders: list[dict[str, Any]], scenario: dict[str, Any]) -> list[dict[str, Any]]:
    required = [s.lower() for s in scenario.get("required_status", [])]
    if not required:
        return list(orders)
    return [o for o in orders if o["status"].lower() in required]


def determine_account_role(scenario: dict[str, Any], order: Optional[dict[str, Any]]) -> str:
    """주문 상태와 시나리오에 따라 account_role 결정"""
    allowed_roles = scenario.get("account_roles", ["mixed"])

    if not order:
        return random.choice(allowed_roles)

    status = order.get("status", "").lower()
    if status in ["paid", "preparing"]:
        return "pre_delivery" if "pre_delivery" in allowed_roles else random.choice(allowed_roles)
    elif status in ["shipped", "delivered"]:
        return "delivered" if "delivered" in allowed_roles else random.choice(allowed_roles)
    else:
        return "mixed"


# ============================================================
# LLM 프롬프트 생성
# ============================================================
def get_query_system_prompt(
    scenario: dict[str, Any],
    account_role: str,
    confusion_pair: Optional[str],
    trap_type: str,
    tool_info: Optional[dict[str, Any]],
) -> str:
    expected_tool = scenario["expected_tool"]
    tool_desc = tool_info.get("description", "") if tool_info else ""
    templates = "\n".join(f"- {t}" for t in HARD_TEMPLATE_FAMILIES[expected_tool])

    return f"""너는 이커머스 에이전트 챗봇의 툴 호출 정확도 평가용 질문 데이터셋을 만드는 역할이다.

목표:
- FunctionChat-Bench dialog 모드용 데이터셋을 만든다.
- 실제 문항은 단일턴(single-turn), 단일툴(single-tool) 호출 평가용이다.
- 평가 지표는 툴 이름 정확도만 본다.
- argument 정확도는 평가하지 않는다.

평가 대상 툴은 아래 5개뿐이다.
1. get_user_orders — 주문번호 모를 때 주문 목록 조회
2. cancel — 배송 전 주문 취소
3. refund — 배송 후 반품/환불
4. exchange — 배송 후 교환 (회수/재배송)
5. change_option — 배송 전 옵션(사이즈/색상) 변경

중요 제약:
- shipping 관련 질문은 절대 만들지 마라. 배송 조회, 택배 위치, 송장번호, 배송 상태 확인 등의 질문은 금지.
- 멀티턴이 필요한 질문은 만들지 마라.
- 한 질문은 최종적으로 하나의 툴로만 해석될 수 있어야 한다.
- 상담형 답변 유도 질문, 정책 설명 질문, 비교 질문은 만들지 마라.
- 질문은 모두 한국어 구어체 사용자 발화로 작성한다.

이번에 만들 질문의 정보:
- 정답 tool: {expected_tool}
- 혼동쌍: {confusion_pair}
- account_role: {account_role}
- trap_type: {trap_type}
- 참고 설명: {tool_desc}

질문 난이도 요소 (적극 반영하라):
- 번복 표현 ("말고", "아니고", "일단", "먼저")
- 사유 기반 추론 ("파손됐는데", "사이즈가 안 맞아서")
- 주문번호 없음 (get_user_orders 유도)
- 교환 vs 옵션변경 경계
- 취소 vs 환불 경계
- 짧은 질문과 장문 질문 혼합
- 자연스러운 한국어 구어체

trap_type: {trap_type} 에 맞는 함정을 반드시 넣어라:
- no_order_id: 주문번호 없이 발화하여 get_user_orders로 유도
- cancel_vs_refund: 취소와 환불을 헷갈리게 하는 표현 사용
- exchange_vs_change_option: 교환과 옵션변경을 헷갈리게 하는 표현 사용
- final_intent_reversal: 처음에 다른 의도를 언급하다가 최종 의사를 번복
- reason_based_inference: 사유만 말하고 직접적 도구명을 생략
- mixed_signal_but_single_tool: 여러 도구의 키워드를 섞지만 최종 의도는 하나

시나리오별 hard 패턴 예시 (그대로 복사하지 말고 새 문장으로 변형하라):
{templates}

추가 규칙:
- question에는 assistant 발화나 설명을 넣지 마라.
- 반드시 사용자 발화 한 문장 또는 두세 문장 이내로 작성하라.
- 같은 표현을 반복하지 마라.
- 너무 쉬운 직설형만 만들지 마라.
- 주문번호가 필요한 경우 {{ORDER_ID}}를 자연스럽게 포함하라.

출력 형식:
반드시 JSON 객체 하나만 출력하라.
{{
  "question": "생성된 사용자 발화",
  "account_role": "{account_role}",
  "intended_tool_family": "{expected_tool}",
  "difficulty_reason": "왜 이 질문이 어려운지 한 문장",
  "trap_type": "{trap_type}"
}}
"""


def build_query_prompt(
    scenario: dict[str, Any],
    order: Optional[dict[str, Any]],
    account_role: str,
    trap_type: str,
) -> str:
    order_status = order["status"].upper() if order else "N/A"
    expected_tool = scenario["expected_tool"]

    order_constraints = (
        f"주문번호 {{ORDER_ID}}를 포함하세요. 현재 주문 상태는 {order_status}."
        if order and scenario.get("include_order", False)
        else "주문번호는 포함하지 마세요."
    )

    return f"""
다음 조건에 맞는 어려운 질문 1개를 생성하세요.
- 시나리오: {scenario['name']}
- 정답 tool: {expected_tool}
- account_role: {account_role}
- trap_type: {trap_type}
- {order_constraints}

중요:
- 질문은 어렵게 만들되, 슬롯/인자 정보를 더 붙여서 어렵게 만들지 마세요.
- 짧지만 혼동되게 만드세요.
- shipping/배송조회/택배/송장 관련 질문은 절대 금지입니다.
- exchange 시나리오에서는 배송 완료 후 같은 상품의 사이즈/색상 교환만 의미합니다.
- change_option 시나리오에서는 배송 전 옵션 변경만 의미합니다.
"""


# ============================================================
# 파싱 & 정규화 & 검증
# ============================================================
def parse_json_response(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()
    return json.loads(raw)


def normalize_query(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"ord-[a-z0-9_-]+", "<order>", text)
    text = re.sub(r"[\s\t\n]+", " ", text)
    text = re.sub(r"[!?.,~]+", "", text)
    text = text.replace("주세요", "줘요")
    text = text.replace("보여주세요", "보여줘요")
    return text


def validate_query(
    query: str,
    scenario: dict[str, Any],
    trap_type: str,
    order: Optional[dict[str, Any]],
) -> tuple[bool, str]:
    q = query.strip()
    expected_tool = scenario["expected_tool"]

    if not q:
        return False, "empty"
    if len(q) > 100:
        return False, "too_long"

    # 주문번호 포함 여부 체크
    if scenario.get("include_order", False):
        if not order or order["order_id"] not in q:
            return False, "missing_order_id"
    else:
        if order and order.get("order_id") and order["order_id"] in q:
            return False, "unexpected_order_id"

    # shipping 관련 표현 금지
    if any(p in q for p in FORBIDDEN_SHIPPING_PATTERNS):
        return False, "contains_shipping_pattern"

    # 시나리오 핵심 키워드 포함 여부
    if expected_tool in SCENARIO_KEYWORDS:
        if not any(k in q for k in SCENARIO_KEYWORDS[expected_tool]):
            return False, "missing_core_signal"

    # Hard 신호 최소 1개 존재
    hard_signal_count = sum(1 for k in HARD_SIGNAL_KEYWORDS if k in q)
    if hard_signal_count < 1:
        return False, "missing_hard_signal"

    # 혼동 신호 최소 1개 존재 (함정 유형에 따라)
    if trap_type in ["cancel_vs_refund", "exchange_vs_change_option", "mixed_signal_but_single_tool", "final_intent_reversal"]:
        confusion_kws = CONFUSION_SIGNAL_KEYWORDS.get(expected_tool, [])
        transition_kws = ["말고", "아니고", "먼저", "일단"]
        if not any(k in q for k in confusion_kws) and not any(k in q for k in transition_kws):
            return False, "missing_confusion_signal"

    # 과도한 인자/설명 금지
    long_arg_hits = sum(1 for k in FORBIDDEN_LONG_ARG_PATTERNS if k in q)
    if long_arg_hits >= 2:
        return False, "too_many_extra_args"

    return True, "ok"


# ============================================================
# LLM 질문 생성
# ============================================================
def generate_query(
    scenario: dict[str, Any],
    order: Optional[dict[str, Any]],
    account_role: str,
    confusion_pair: Optional[str],
    trap_type: str,
    tool_info: Optional[dict[str, Any]],
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    system_prompt = get_query_system_prompt(scenario, account_role, confusion_pair, trap_type, tool_info)
    user_prompt = build_query_prompt(scenario, order, account_role, trap_type)

    try:
        raw = (
            client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            .choices[0]
            .message.content.strip()
        )
        data = parse_json_response(raw)
        user_query = str(data.get("question", "")).strip()
        difficulty_reason = str(data.get("difficulty_reason", "")).strip()
        generated_trap_type = str(data.get("trap_type", trap_type)).strip()

        if order and scenario.get("include_order", False):
            user_query = user_query.replace("{{ORDER_ID}}", order["order_id"]).replace("{ORDER_ID}", order["order_id"])

        if not user_query:
            return None, None

        meta = {
            "difficulty_reason": difficulty_reason,
            "trap_type": generated_trap_type,
            "account_role": account_role,
        }
        return user_query, meta
    except Exception as e:
        print(f"[ERROR] 생성 에러 ({scenario['name']} / {trap_type}): {e}")
        return None, None


# ============================================================
# 레코드 빌더 & 저장
# ============================================================
def build_record(
    idx: int,
    user_info: dict[str, Any],
    scenario: dict[str, Any],
    user_query: str,
    meta: dict[str, Any],
    order: Optional[dict[str, Any]],
    confusion_pair: Optional[str],
) -> dict[str, Any]:
    return {
        "scenario": {
            "id": scenario["id"],
            "name": scenario["name"],
            "action": scenario["action"],
            "tools": scenario.get("tools", []),
            "possible": scenario["possible"],
        },
        "order": order,
        "user_id": user_info["user_id"],
        "user_email": user_info["email"],
        "user_query": user_query,
        "meta": {
            "difficulty": "hard",
            "difficulty_reason": meta.get("difficulty_reason", ""),
            "trap_type": meta.get("trap_type", ""),
            "account_role": meta.get("account_role", "mixed"),
            "confusion_pair": confusion_pair,
            "has_order_id": bool(order and order.get("order_id") and order["order_id"] in user_query),
            "normalized_query": normalize_query(user_query),
        },
    }


def save_outputs(records: list[dict[str, Any]]) -> None:
    OUTPUT_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSONL_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def summarize(records: list[dict[str, Any]], users: list[dict[str, Any]]) -> None:
    print("\n[요약]")
    print("- 선택된 DB 사용자:")
    for u in users:
        print(f"  - user_id={u['user_id']} / email={u['email']}")

    tool_counts: dict[str, int] = {}
    trap_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    for r in records:
        expected_tool = r["scenario"]["action"]
        tool_counts[expected_tool] = tool_counts.get(expected_tool, 0) + 1
        trap_counts[r["meta"]["trap_type"]] += 1
        role_counts[r["meta"]["account_role"]] += 1

    print("- tool별 개수:")
    for tool_name in ["get_user_orders", "cancel", "refund", "exchange", "change_option"]:
        print(f"  - {tool_name}: {tool_counts.get(tool_name, 0)}")
    print(f"- 전체 샘플 수: {len(records)}")
    print("- trap_type별 개수:")
    for trap, cnt in trap_counts.most_common():
        print(f"  - {trap}: {cnt}")
    print("- account_role별 개수:")
    for role, cnt in role_counts.most_common():
        print(f"  - {role}: {cnt}")
    print(f"- JSONL 저장: {OUTPUT_JSONL_PATH}")


# ============================================================
# 메인 실행
# ============================================================
def main() -> None:
    print("=" * 72)
    print("[1단계] order_intent_router 툴 호출 정확도 평가용 질의 50개 생성")
    print("- 평가 대상: get_user_orders, cancel, refund, exchange, change_option")
    print("- shipping 제외, 단일턴/단일툴, Hard 난이도 100%")
    print("- trap_type 기반 함정 유도 질문 생성")
    print("=" * 72)

    raw_users = load_eval_users()
    if not raw_users:
        raise RuntimeError("eval_data.jsonl 에서 사용자 목록을 읽지 못했습니다.")

    users = select_users_from_db(raw_users, target_count=TARGET_USER_COUNT)
    tools_info = load_tools()
    tools_map = {t["function"]["name"]: t["function"] for t in tools_info if t.get("type") == "function"}

    records: list[dict[str, Any]] = []
    normalized_seen: set[str] = set()
    total_count = 0

    for scenario in SCENARIOS:
        print(f"\n>>> 시나리오 '{scenario['name']}' ({scenario['expected_tool']}) 생성 중")
        expected_tool = scenario["expected_tool"]
        tool_info = tools_map.get(expected_tool)
        available_traps = TRAP_TYPES.get(expected_tool, ["mixed_signal_but_single_tool"])
        scenario_records = 0
        attempts = 0

        while scenario_records < SAMPLES_PER_SCENARIO and attempts < MAX_ATTEMPTS_PER_SCENARIO:
            attempts += 1

            # 사용자 라운드로빈
            user_info = users[scenario_records % len(users)]

            # 주문 필터링
            candidate_orders = filter_orders_for_scenario(user_info["orders"], scenario)
            order = random.choice(candidate_orders) if candidate_orders else None
            if scenario.get("include_order", False) and not order:
                print(f"  [WARN] 주문 부족: {scenario['name']} / user_id={user_info['user_id']}")
                continue

            # Account Role 결정
            account_role = determine_account_role(scenario, order)

            # Trap Type 라운드로빈 (다양성 보장)
            trap_type = available_traps[scenario_records % len(available_traps)]

            # Confusion Pair
            confusion_pair = CONFUSION_PAIRS.get(expected_tool)

            user_query, meta = generate_query(
                scenario=scenario,
                order=order,
                account_role=account_role,
                confusion_pair=confusion_pair,
                trap_type=trap_type,
                tool_info=tool_info,
            )
            if not user_query or not meta:
                continue

            valid, reason = validate_query(
                query=user_query,
                scenario=scenario,
                trap_type=trap_type,
                order=order,
            )
            if not valid:
                print(f"  [RETRY] 검증 실패 ({reason}): {user_query}")
                continue

            normalized = normalize_query(user_query)
            if normalized in normalized_seen:
                print(f"  [RETRY] 중복 문장: {user_query}")
                continue

            normalized_seen.add(normalized)
            total_count += 1
            scenario_records += 1
            records.append(
                build_record(
                    idx=total_count,
                    user_info=user_info,
                    scenario=scenario,
                    user_query=user_query,
                    meta=meta,
                    order=order,
                    confusion_pair=confusion_pair,
                )
            )
            print(
                f"  [{scenario_records}/{SAMPLES_PER_SCENARIO}] trap={trap_type} "
                f"(user_id={user_info['user_id']}) -> tool: {expected_tool}"
            )

        if scenario_records < SAMPLES_PER_SCENARIO:
            raise RuntimeError(
                f"시나리오 '{scenario['name']}' 샘플을 충분히 생성하지 못했습니다. "
                f"생성={scenario_records}, 목표={SAMPLES_PER_SCENARIO}, 시도={attempts}"
            )

    if len(records) != len(SCENARIOS) * SAMPLES_PER_SCENARIO:
        raise RuntimeError(f"최종 레코드 수가 50개가 아닙니다. 현재={len(records)}")

    save_outputs(records)
    print(f"\n✅ 완료! 총 {len(records)}개 저장")
    summarize(records, users)


if __name__ == "__main__":
    main()
