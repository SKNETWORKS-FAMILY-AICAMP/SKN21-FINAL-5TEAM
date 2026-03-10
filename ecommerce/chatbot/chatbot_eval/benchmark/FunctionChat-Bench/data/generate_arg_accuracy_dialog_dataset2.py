"""
generate_arg_accuracy_dialog_dataset.py

[목적]
이커머스 챗봇의 Argument Accuracy 평가를 위한 Dialog 모드 데이터셋을 생성합니다.
기존 버전을 기반으로 아래 내용이 포함된 11개 시나리오 버전입니다:
  1. 실제 DB 주문 ID를 상태(status) 포함하여 조회
  2. 취소/반품/환불/교환이 가능한 경우와 불가능한 경우를 모두 다루는 시나리오 포함
  3. 주문 상태 정책에 따른 ground_truth 생성
  4. [핵심] 불가능 시나리오 반영: 불가능한 상태라도 봇이 텍스트로 미리 차단하지 않고 shipping을 호출하여 시스템적으로 검증하도록 유도.

[주문 상태 정책]
- PENDING  : 취소/반품/교환 모두 불가
- PAID     : 취소 가능, 반품 불가(→취소 안내), 교환 무료
- PREPARING: 취소 가능, 반품 불가(→취소 안내), 교환 무료
- SHIPPED  : 취소 불가, 반품 가능, 교환 유료
- DELIVERED(7일 이내): 취소 불가, 반품 가능, 교환 유료
- DELIVERED(7일 초과): 취소/반품/교환 모두 불가
- CANCELLED/REFUNDED : 모두 불가

[평가 방식]
- Argument Accuracy만 평가합니다 (type_of_output == "call" 인 턴만).
- FunctionChat-Bench JSONL 포맷으로 저장됩니다.
"""


import json
import os
import sys
import random
import csv
import re
from pathlib import Path
from dotenv import load_dotenv

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import DATA_DIR, PROJECT_ROOT, RAW_DIR, FASHION_CSV, CLOTHES_CSV, TOOLS_PATH

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# 프로젝트 루트를 sys.path에 추가 (backend 모듈 import용)
sys.path.insert(0, str(PROJECT_ROOT))


# models, crud, db 등 명시적 import (실제 경로에 맞게 조정)
from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.router.users.models import User
from ecommerce.platform.backend.app.router.orders.models import Order
from ecommerce.platform.backend.app.router.shipping.models import ShippingInfo
from ecommerce.platform.backend.app.router.points.models import PointHistory
from ecommerce.platform.backend.app.router.user_history.models import UserHistory
from ecommerce.platform.backend.app.router.carts.models import Cart
from ecommerce.platform.backend.app.router.payments.models import Payment
from ecommerce.platform.backend.app.router.products.models import Product
from ecommerce.platform.backend.app.router.reviews.models import Review
# ... 필요한 모든 관계 모델 import (추가 필요시 아래에 계속 추가)
from ecommerce.platform.backend.app.router.users.crud import get_user_by_email
from ecommerce.platform.backend.app.router.orders.crud import get_orders_by_user_id

OUTPUT_PATH = DATA_DIR / "my_eval_arg_accuracy_dialogs2.jsonl"

# ─── OpenAI 설정 ──────────────────────────────────────────────────────────────
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-4o-mini"


# ─── DB에서 실제 주문 정보 (주문번호 + 상태) 조회 ────────────────────────────
def load_eval_users() -> list:
    """eval_data.jsonl에서 모든 유저 정보와 액션 정보를 로드하여 리스트로 반환합니다."""
    path = PROJECT_ROOT / "ecommerce/chatbot/chatbot_eval/benchmark/eval_data.jsonl"
    users = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                item = json.loads(line)
                if item.get("type") == "user":
                    user_data = {
                        "email": item["data"]["user_email"],
                        "actions": {act["type"]: act.get("data", {}) for act in item.get("action", [])}
                    }
                    users.append(user_data)
    except Exception as e:
        print(f"[WARN] eval_data.jsonl 읽기 실패: {e}")
    
    # 만약 유저 데이터가 없으면 기본 유저 추가 (fallback)
    if not users:
        users.append({"email": "test2@example.com", "actions": {}})
    return users

def get_real_orders_with_status(user_email: str) -> tuple[int, list[dict]]:
    """
    user_email 사용자의 실제 주문 목록과 user_id를 ORM 세션에서 가져옵니다.
    각 주문의 order_number, status, shipping_fee, shipping_info(delivered_at) 포함.
    """
    try:
        from datetime import datetime
        session = SessionLocal()
        user = get_user_by_email(session, user_email)
        user_id = user.id if user else 1

        # crud 함수로 주문 목록 조회 (limit 50)
        orders, _ = get_orders_by_user_id(session, user_id, limit=50)
        result = []
        for o in orders:
            delivered_at = None
            if hasattr(o, "shipping_info") and o.shipping_info:
                delivered_at = o.shipping_info.delivered_at
            days_since = None
            if delivered_at:
                days_since = (datetime.now() - delivered_at).days
            result.append({
                "order_id": o.order_number,
                "status": o.status,
                "shipping_fee": o.shipping_fee or 0.0,
                "days_since_delivery": days_since,
            })
        session.close()
        print(f"[INFO] 실제 주문 조회 완료: {[o['order_id'] + '(' + o['status'] + ')' for o in result]}")
        return user_id, result
    except Exception as e:
        print(f"[WARN] ORM DB 조회 실패: {e}")
    # Fallback
    return 1, [
        {"order_id": "ORD-FALLBACK-0001", "status": "paid",      "shipping_fee": 3000.0, "days_since_delivery": None},
        {"order_id": "ORD-FALLBACK-0002", "status": "shipped",    "shipping_fee": 3000.0, "days_since_delivery": None},
        {"order_id": "ORD-FALLBACK-0003", "status": "delivered",  "shipping_fee": 3000.0, "days_since_delivery": 2},
    ]


def classify_order(order: dict) -> dict:
    """주문 상태에 따라 취소/반품/교환 가능 여부를 판단합니다."""
    status = order["status"]
    days = order.get("days_since_delivery")

    can_cancel = status in ("paid", "preparing")
    can_return = (
        status in ("shipped", "delivered")
        and not (status == "delivered" and days is not None and days > 7)
    )
    can_exchange = (
        status in ("paid", "preparing", "shipped", "delivered")
        and not (status == "delivered" and days is not None and days > 7)
        and status not in ("cancelled", "refunded")
    )
    exchange_free = status in ("paid", "preparing")

    return {
        "can_cancel": can_cancel,
        "can_return": can_return,
        "can_exchange": can_exchange,
        "exchange_free": exchange_free,
    }


# ─── Tools 로드 ───────────────────────────────────────────────────────────────
def load_tools() -> list:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        return json.load(f)

def simplify_tool_definition_for_prompt(tool_def: dict) -> dict:
    """GPT 프롬프트에 넣기 좋게 툴 정의를 요약합니다."""
    func = tool_def.get("function", {})
    return {
        "name": func.get("name"),
        "description": func.get("description"),
        "parameters": func.get("parameters", {}).get("properties", {}),
        "required": func.get("parameters", {}).get("required", [])
    }


# ─── CSV 샘플링 ───────────────────────────────────────────────────────────────
def load_csv_samples(path: Path, n: int = 100) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
                if len(rows) >= n:
                    break
    except Exception as e:
        print(f"[WARN] CSV 로드 실패 {path}: {e}")
    return rows


def pick_product_info(samples: list[dict]) -> dict:
    if not samples:
        return {}
    row = random.choice(samples)
    return {k: str(v).strip() for k, v in row.items() if str(v).strip() and str(v).strip() != "nan"}


# ─── GPT 호출 ─────────────────────────────────────────────────────────────────
def call_gpt(system_prompt: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=3000,
    )
    return response.choices[0].message.content.strip()


# ─── 주문 상태 정책 정의 ──────────────────────────────────────────────────────
ORDER_STATUS_POLICY = """
## 주문 상태 정책 (반드시 준수)

| 상태                   | 취소 | 반품/환불 | 교환       |
|------------------------|------|-----------|------------|
| PENDING (결제 대기)    |  불가 | 불가      | 불가       |
| PAID (결제 완료)       |  가능 | 불가→취소 안내 | 가능(무료) |
| PREPARING (상품준비중) |  가능 | 불가→취소 안내 | 가능(무료) |
| SHIPPED (배송중)       |  불가 | 가능      | 가능(유료) |
| DELIVERED 7일 이내     |  불가 | 가능      | 가능(유료) |
| DELIVERED 7일 초과     |  불가 | 불가      | 불가       |
| CANCELLED              |  불가 | 불가      | 불가       |
| REFUNDED               |  불가 | 불가      | 불가       |

### 취소 (cancel)
- 가능: PAID, PREPARING 상태에서만 가능
- 처리: 즉시 취소, 전액 환불
- 불가 시: 현재 상태에서는 취소가 불가능함을 안내

### 반품/환불 (refund)
- 가능: SHIPPED 또는 DELIVERED(7일 이내)
- 배송 전(PAID/PREPARING) 상태: 환불 불가 → cancel 안내

### 교환 (exchange / change_option)
- PAID/PREPARING: change_option (무료)
- SHIPPED/DELIVERED 7일 이내: exchange (유료, 왕복 배송비)
- 불가: CANCELLED, REFUNDED, DELIVERED 7일 초과
"""

# ─── 시나리오 정의 (11개) ──────────────────────────────────────────────────────
SCENARIOS = [
    {"id": 1, "name": "주문 취소", "action": "cancel", "possible": True, "required_status": ["preparing", "paid"], "tools": ["cancel", "shipping"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 2, "name": "환불 신청", "action": "refund", "possible": True, "required_status": ["delivered", "shipped"], "tools": ["refund", "shipping"], "rag_policy": "required", "ux_flow": "direct"},
    {"id": 3, "name": "교환 신청", "action": "exchange", "possible": True, "required_status": ["delivered", "shipped"], "tools": ["exchange", "shipping"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 4, "name": "주문 내역 조회 (주문번호 없음)", "action": "shipping_no_id", "possible": True, "required_status": [], "tools": ["shipping"], "rag_policy": "forbidden", "ux_flow": "direct"},
    {"id": 5, "name": "주문 내역 조회 (주문번호 있음)", "action": "shipping_with_id", "possible": True, "required_status": [], "tools": ["shipping"], "rag_policy": "forbidden", "ux_flow": "direct"},
    {"id": 6, "name": "상품 키워드 검색", "action": "search_by_text_clip", "possible": True, "required_status": [], "tools": ["search_by_text_clip"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 7, "name": "의류 추천", "action": "recommend_clothes", "possible": True, "required_status": [], "tools": ["recommend_clothes"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 8, "name": "이미지 검색", "action": "search_by_image", "possible": True, "required_status": [], "tools": ["search_by_image"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 9, "name": "중고 판매 신청", "action": "used_sale", "possible": True, "required_status": [], "tools": ["open_used_sale_form", "register_used_sale"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 10, "name": "리뷰 작성", "action": "review", "possible": True, "required_status": ["delivered"], "tools": ["generate_review_draft", "create_review"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 11, "name": "상품권 등록", "action": "register_gift_card", "possible": True, "required_status": [], "tools": ["register_gift_card"], "rag_policy": "optional", "ux_flow": "direct"},
]

# SCENARIOS에서 ID와 action 이름을 추출하여 자동 생성
SCENARIO_NAME_MAP = {s["id"]: s["action"] for s in SCENARIOS}

# ─── acceptable_arguments ─────────────────────────────────────────────────────
ACCEPTABLE = {
    "reason": [
        "단순 변심", "simple_change_of_mind", "change_of_mind", "customer_preference",
        "사이즈가 안 맞아요", "색상이 화면과 달라요", "배송이 너무 늦어서 취소합니다",
        "상품이 파손되었어요", "다른 상품이 배송됨", "마음에 들지 않음",
        "그냥 마음이 바뀌었어요", "배송이 너무 느려요", "주문을 잘못했어요",
        "필요가 없어졌어요", "다른 쇼핑몰에서 더 저렴하게 팔아요",
        "상품 정보와 실제 상품이 달라요", "생각했던 것과 달라요",
        "실수로 주문했어요", "변심", "단순변심", "잘못 주문", "배송 지연",
        "마음이 변함", "단순 변심으로 인한 취소", "사이즈 불일치", "상품 불만족"
    ],
    "size": ["XS", "S", "M", "L", "XL", "90", "95", "100", "105", "FREE", "free"],
    "color": ["black", "white", "ivory", "cream", "beige", "navy", "gray", "brown",
              "블랙", "화이트", "아이보리", "크림", "베이지", "네이비", "그레이", "브라운"],
    "rating": [1, 2, 3, 4, 5],
    "payment_method": ["카드", "계좌이체", "CARD", "BANK_TRANSFER", "카카오페이", "네이버페이"]
}



# ─── 시스템 프롬프트 ──────────────────────────────────────────────────────────
def get_system_prompt(user_id: int) -> str:
    return f"""당신은 이커머스 챗봇 평가용 데이터셋 전문가입니다.
주어진 시나리오에 따라 멀티턴 대화와 Ground Truth tool call을 생성합니다.

{ORDER_STATUS_POLICY}

규칙:
1. output은 반드시 순수 JSON 객체만 반환합니다. 마크다운 코드블록, 설명 텍스트 없이.
2. 모든 tool call에는 user_id: {user_id}을(를) 반드시 포함합니다.
3. order_id는 반드시 {{ORDER_ID}} placeholder를 사용해야 합니다.
4. dialog는 멀티턴으로, 필수 argument(주문번호, 사유 등)가 대화 안에 구체적으로 포함되어야 합니다.
5. type_of_output: "call" 인 턴이 반드시 1개 이상 포함되어야 합니다.
6. [중요] 사용자가 주문번호와 필수 인자를 모두 제공한 경우, 해당 요청을 처리하기 위한 적절한 도구를 호출합니다.
7. [중요] 불가능한 시나리오에서는 텍스트로 즉시 거절하지 말고, 먼저 상태 확인 또는 가능 여부 검증용 도구를 호출하는 흐름으로 생성합니다.
8. 모든 대화는 한국어로 작성합니다.
9. user_id는 항상 {user_id}로 고정합니다.
"""


def build_prompt_for_scenario(
    scenario: dict,
    product_info: dict,
    dialog_num: int,
    order: dict,
    user_email: str,
    user_id: int,
    all_openai_tools: list,
) -> str:
    # 해당 시나리오에서 사용하는 툴들의 상세 정의 추출
    relevant_tool_names = scenario.get("tools", [])
    relevant_tools_simplified = [
        simplify_tool_definition_for_prompt(t) for t in all_openai_tools 
        if t.get("function", {}).get("name") in relevant_tool_names
    ]
    tools_json_str = json.dumps(relevant_tools_simplified, ensure_ascii=False, indent=2)

    product_str = json.dumps(product_info, ensure_ascii=False)
    action_possible = "가능" if scenario["possible"] else "불가능"
    order_status = order["status"].upper()

    ux_flow = scenario.get("ux_flow", "direct")
    action_context_map = {
        "cancel": "cancel", "refund": "refund", "exchange": "exchange",
        "review": "review", "query": None, "faq": None, "other": None,
    }
    action_context = action_context_map.get(scenario["action"])

    if ux_flow == "select":
        flow_instruction = f"""
[대화 흐름 - 주문 선택 UX (HITL 구조 참고)]

턴 1 (type_of_output: "call"):
  - 사용자의 요청에는 주문번호와 필요한 인자가 포함되도록 생성하세요.
  - 사용자가 별도의 추가 질문 없이 바로 요청을 수행할 수 있는 형태로 작성합니다.
예:
"{{ORDER_ID}} 주문 취소하고 싶어요. 단순 변심입니다."
"{{ORDER_ID}} 환불받고 싶은데요, 사이즈가 안 맞네요."
"제가 주문한 {{ORDER_ID}} 교환하고 싶어요."

턴 2 (type_of_output: "call"):

- assistant는 주문 선택 또는 요청 확인 메시지를 생성합니다.
- 사용자는 해당 주문({{ORDER_ID}})을 확인합니다.

가능 시나리오 (possible=true):
- ground_truth: 요청을 처리하기 위한 action tool 호출 (예: cancel, refund 등)

불가능 시나리오 (possible=false):
- ground_truth: 주문 상태 또는 가능 여부를 확인하기 위한 검증용 tool 호출
"""
    else:
        flow_instruction = """
[대화 흐름 - 직접 요청]
사용자가 필요한 정보를 직접 대화에서 제공합니다.
"""

    turns_example = f"""
  "turns": [
    {{
      "turn_num": 1,
      "query": [
        {{"role": "user", "content": "ORDER_ID 주문을 취소하고 싶어요. 단순 변심입니다."}}
      ],
      "ground_truth": {{
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {{
            "id": "call_1",
            "type": "function",
            "function": {{
                "name": "cancel",
                "arguments": {{
                "order_id": {{ORDER_ID}},
                "user_id": {user_id},
                "reason": "단순 변심"
                }}
            }}
          }}
        ]
      }},
      "type_of_output": "call",
      "acceptable_arguments": {{
        "reason": ["단순 변심", "simple_change_of_mind"]
      }}
    }}
  ]"""

    return f"""
당신은 이커머스 챗봇 평가용 데이터셋 전문가입니다.
주어진 시나리오와 상품 정보, 그리고 실제 사용 가능한 **툴(도구) 정의**를 바탕으로 사용자와 챗봇 간의 대화(turns)를 생성하세요.

시나리오: {scenario['name']} (시나리오 ID: {scenario['id']})
다이얼로그 번호: {dialog_num}
RAG 정책: {scenario['rag_policy']}
주문 상태: {order_status}
이 시나리오의 요청 처리 가능 여부: {action_possible}

### 🛠 사용할 수 있는 툴(도구) 상세 정의
GPT는 아래 JSON 구조에 정의된 **파라미터 이름과 타입**을 엄격히 준수하여 `ground_truth`의 `arguments`를 생성해야 합니다.
{tools_json_str}

### 📦 참고 상품 정보 (CSV 기반, 이 정보만 사용할 것):
{product_str}

다음 형식으로 JSON을 반환하세요:

{{
  "scenario_id": "{scenario['id']}-{dialog_num}",
  "scenario_name": "{scenario['name']}",
  "order_status": "{order_status}",
  "order_id_source": "shipping:{user_email}",
  "rag_policy": "{scenario['rag_policy']}",
  "possible": {str(scenario['possible']).lower()},
  "source_file": "AI_Hub CSV",
  "source_row_id": "<CSV에서 참조한 행 정보>",
  "evidence": "<사용한 근거>",
{turns_example}
}}

중요:
- type_of_output이 "call"인 턴이 반드시 1개 이상 포함되어야 합니다.
- query 배열은 해당 turn까지의 전체 대화 기록을 포함해야 합니다.
- **`arguments`는 JSON 객체(object) 형식**으로 생성하세요 (이스케이프된 문자열이 아님).
- 모든 대화는 **한국어**로 작성하세요.
- 불가능한 주문 상태의 시나리오에서는 최종 액션 도구(cancel, refund, exchange)를 바로 호출하지 말고, `shipping` 도구를 호출하여 시스템적으로 상태를 검증하는 흐름으로 생성하세요.
"""


# ─── 후처리 ───────────────────────────────────────────────────────────────────
def replace_order_id_in_turns(turns: list, order_id: str) -> list:
    """{{ORDER_ID}} 또는 {ORDER_ID} 플레이스홀더를 실제 주문 ID로 치환합니다."""
    for t in turns:
        # 1. ground_truth 내의 도구 호출 인자(arguments) 치환
        gt = t.get("ground_truth", {})
        if gt and isinstance(gt, dict):
            for tc in gt.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", "")
                
                if isinstance(args, str):
                    # 문자열인 경우 두 가지 중괄호 형식 모두 대응
                    fn["arguments"] = args.replace("{{ORDER_ID}}", order_id).replace("{ORDER_ID}", order_id)
                elif isinstance(args, dict):
                    # 딕셔너리인 경우 내부의 문자열 값들을 순회하며 치환
                    new_args = {}
                    for k, v in args.items():
                        if isinstance(v, str):
                            new_args[k] = v.replace("{{ORDER_ID}}", order_id).replace("{ORDER_ID}", order_id)
                        else:
                            new_args[k] = v
                    fn["arguments"] = new_args

        # 2. [추가] acceptable_arguments 필드 내부의 리스트 값 치환
        # 이 부분이 추가되어야 모델 답변이 허용 범위(acceptable) 내에 있는지 정상 평가됩니다.
        acc_args = t.get("acceptable_arguments", {})
        if isinstance(acc_args, dict):
            for k, v in acc_args.items():
                if isinstance(v, list):
                    acc_args[k] = [
                        val.replace("{{ORDER_ID}}", order_id).replace("{ORDER_ID}", order_id) 
                        if isinstance(val, str) else val 
                        for val in v
                    ]

        # 3. 사용자 및 어시스턴트의 대화 내용(query) 치환
        has_id_in_query = False
        for msg in t.get("query", []):
            if isinstance(msg.get("content"), str):
                content = msg["content"].replace("{{ORDER_ID}}", order_id).replace("{ORDER_ID}", order_id)
                if order_id in content:
                    has_id_in_query = True
                msg["content"] = content

        # 만약 대화 내용에 주문번호가 언급되지 않았다면 마지막 메시지에 강제 추가 (평가 가이드용)
        if t.get("type_of_output") == "call" and not has_id_in_query:
            if t.get("query"):
                t["query"][-1]["content"] += f" 주문번호는 {order_id} 입니다."
                
    return turns


def ensure_acceptable_arguments(turns: list, order: dict) -> list:
    for t in turns:
        if t.get("type_of_output") == "call":
            if "acceptable_arguments" not in t:
                t["acceptable_arguments"] = {}
            
            # [추가] ACCEPTABLE 딕셔너리에 기반한 자동 매핑 보강
            gt_tool_calls = t.get("ground_truth", {}).get("tool_calls", [])
            for tc in gt_tool_calls:
                args = tc.get("function", {}).get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        args = {}
                
                for key in args.keys():
                    if key in ACCEPTABLE:
                        raw_values = ACCEPTABLE[key]
                        # 리스트 내부의 플레이스홀더를 실제 주문번호로 치환
                        t["acceptable_arguments"][key] = [
                            val.replace("{{ORDER_ID}}", order["order_id"]).replace("{ORDER_ID}", order["order_id"])
                            if isinstance(val, str) else val
                            for val in raw_values
                        ]
    return turns


def filter_call_turns_only(turns: list) -> list:
    return [t for t in turns if t.get("type_of_output") == "call"]


# ─── 다이얼로그 생성 ──────────────────────────────────────────────────────────
def generate_dialog(
    scenario: dict,
    product_info: dict,
    dialog_num: int,
    all_openai_tools: list,
    order: dict,
    user_email: str,
    user_id: int,
) -> dict | None:
    prompt = build_prompt_for_scenario(scenario, product_info, dialog_num, order, user_email, user_id, all_openai_tools)
    system_prompt = get_system_prompt(user_id)
    try:
        raw = call_gpt(system_prompt, prompt)
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        data = json.loads(raw.strip())

        # 1. ensure_acceptable_arguments 보완 (먼저 수행하여 치환 대상을 확보)
        data["turns"] = ensure_acceptable_arguments(data.get("turns", []), order)

        # 2. 실제 주문 ID 치환
        data["turns"] = replace_order_id_in_turns(data.get("turns", []), order["order_id"])

        # call 턴만 필터링
        data["turns"] = filter_call_turns_only(data.get("turns", []))

        # turn_num 1부터 재정렬
        for idx, t in enumerate(data["turns"], start=1):
            t["turn_num"] = idx

        # tool_call id 순차 번호로 정리
        call_id_counter = 1
        for t in data["turns"]:
            gt = t.get("ground_truth", {})
            if isinstance(gt, dict):
                for tc in gt.get("tool_calls", []) or []:
                    if "type" not in tc:
                        tc["type"] = "function"
                    tc["id"] = f"call_{call_id_counter}"
                    call_id_counter += 1

        if not data["turns"]:
            print(f"[WARN] dialog {dialog_num}: call 턴이 없습니다.")
            return None

        data["dialog_num"] = dialog_num
        data["tools_count"] = len(all_openai_tools)
        data["tools"] = all_openai_tools
        data["user_id"] = user_id
        data["user_email"] = user_email
        # 주문 메타 정보 저장
        data["order_id"] = order["order_id"]
        data["order_status"] = order["status"]
        data["possible"] = scenario["possible"]

        return data
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 파싱 실패 (dialog {dialog_num}): {e}")
        return None
    except Exception as e:
        print(f"[ERROR] 생성 실패 (dialog {dialog_num}): {e}")
        return None


# ─── 주문 선택 로직 ───────────────────────────────────────────────────────────
def pick_order_for_scenario(scenario: dict, all_orders: list[dict], target_order_number: str = None) -> dict | None:
    """
    eval_data.jsonl 에 지정된 target_order_number 가 있으면 그것을 최우선으로 선택합니다.
    시나리오의 required_status에 맞는 주문을 DB 주문 목록에서 선택합니다.
    """
    required = scenario.get("required_status", [])
    if target_order_number:
        matched_target = [o for o in all_orders if o["order_id"] == target_order_number]
        if matched_target:
            order = matched_target[0]
            if required and order["status"] not in required:
                print(f"[WARN] target_order {target_order_number} 상태({order['status']})가 시나리오 필요({required})와 다름. 그래도 사용.")
            return order
        else:
            print(f"[WARN] target_order {target_order_number} 를 사용자 주문 목록에서 못 찾음. 임의 검색으로 진행합니다.")

    if not required:
        return random.choice(all_orders) if all_orders else None

    # 상태가 맞는 주문 필터링
    matched = [o for o in all_orders if o["status"] in required]
    if matched:
        return random.choice(matched)

    # 없으면 fallback: 첫 번째 주문 사용 (임의)
    print(f"[WARN] 시나리오 '{scenario['name']}' 에 맞는 상태({required}) 주문 없음. 임의 주문 사용.")
    return random.choice(all_orders) if all_orders else None


def simplify_tool_definition(openai_tool: dict) -> dict:
    """OpenAI 도구 정의를 요청된 간단한 형식으로 변환합니다."""
    fn = openai_tool.get("function", {})
    params = fn.get("parameters", {}).get("properties", {})
    simplified_params = {}
    for p_name, p_info in params.items():
        simplified_params[p_name] = p_info.get("type", "string")
    
    return {
        "name": fn.get("name"),
        "parameters": simplified_params
    }


# ─── 메인 실행 ────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Argument Accuracy Dialog 데이터셋 생성 시작 (New Schema & Flattened)")
    print("=" * 60)

    # 1. tools 로드
    all_openai_tools = load_tools()
    print(f"[INFO] tools.json 로드 완료: {len(all_openai_tools)}개 tool")

    # 2. CSV 샘플 로드
    fashion_samples = load_csv_samples(FASHION_CSV, n=100)
    clothes_samples = load_csv_samples(CLOTHES_CSV, n=100)
    all_samples = fashion_samples + clothes_samples
    print(f"[INFO] CSV 샘플 로드 완료: {len(all_samples)}개 행")

    # 3. 유저 리스트 로드
    users = load_eval_users()
    print(f"[INFO] 총 {len(users)}명의 유저에 대해 시나리오를 생성합니다.")

    ACTION_TO_EVAL_TYPE = {
        "cancel": "주문취소",
        "refund": "환불",
        "exchange": "교환",
        "query": "주문조회"
    }

    final_flat_results = []
    task_id_counter = 1

    # 4. 유저별 순회
    for u_idx, user_info in enumerate(users, start=1):
        user_email = user_info["email"]
        actions = user_info["actions"]
        print(f"\n>>> [{u_idx}/{len(users)}] 유저 '{user_email}' 데이터 생성 시작")

        user_id, all_orders = get_real_orders_with_status(user_email)
        if not all_orders:
            print(f"  [ERROR] 유저 {user_email}의 주문 정보를 가져오지 못했습니다. 건너뜁니다.")
            continue

        for s_idx, scenario in enumerate(SCENARIOS, start=1):
            print(f"  ({s_idx}/11) 시나리오 '{scenario['name']}' 생성 중...")

            action = scenario.get("action")
            target_eval_type = ACTION_TO_EVAL_TYPE.get(action)
            target_order_number = actions.get(target_eval_type, {}).get("order_number") if target_eval_type else None

            order = pick_order_for_scenario(scenario, all_orders, target_order_number)
            if not order:
                print(f"    → 맞는 상태의 주문 없음. 건너뜁니다.")
                continue

            print(f"    → 사용 주문: {order['order_id']} (상태: {order['status']})")

            product_info = pick_product_info(all_samples) if all_samples else {}

            # 다이얼로그 생성 (내부적으로 GPT 호출 및 후처리 수행)
            dialog_data = generate_dialog(scenario, product_info, s_idx, all_openai_tools, order, user_email, user_id)

            if not dialog_data or not dialog_data.get("turns"):
                print(f"    → 생성 실패, 건너뜁니다.")
                continue

            # 관련 도구들 요약 (해당 시나리오에서 정의된 tools 사용)
            relevant_tool_names = scenario.get("tools", [])
            relevant_tools_simplified = [
                simplify_tool_definition(t) for t in all_openai_tools 
                if t.get("function", {}).get("name") in relevant_tool_names
            ]

            call_turns = [t for t in dialog_data["turns"] if t.get("type_of_output") == "call"]
            if not call_turns:
                print(f"    → call 타입 턴 없음, 건너뜁니다.")
                continue

            for turn_idx, target_turn in enumerate(call_turns, start=1):
                mapped_acceptable = {}
                gt_tool_calls = target_turn.get("ground_truth", {}).get("tool_calls", [])

                if gt_tool_calls:
                    for tc in gt_tool_calls:
                        args = tc.get("function", {}).get("arguments", {})
                        if isinstance(args, str):
                            try: args = json.loads(args)
                            except: args = {}
                        
                        # 1. 일반적인 인자(reason 등)는 ACCEPTABLE 딕셔너리에서 가져옴
                        for key in args.keys():
                            if key in ACCEPTABLE and key != "order_id":
                                mapped_acceptable[key] = ACCEPTABLE[key]
                        
                        # 2. [핵심] order_id는 현재 주문의 실제 번호를 리스트에 직접 삽입
                        # 이렇게 하면 {ORDER_ID}가 남지 않고 실제 ORD-123... 값이 들어갑니다.
                        if "order_id" in args:
                            mapped_acceptable["order_id"] = [order["order_id"]]

                flat_item = {
                    "task_id": f"eval_{task_id_counter:04d}",
                    "serial_num": task_id_counter,
                    "scenario_name": SCENARIO_NAME_MAP.get(scenario["id"], scenario["name"]),
                    "user_id": user_id,
                    "user_email": user_email,
                    "tools": relevant_tools_simplified,
                    "messages": target_turn["query"],
                    "ground_truth": target_turn["ground_truth"],
                    "acceptable_arguments": mapped_acceptable,
                    "type_of_output": "call",
                    "prediction": {"tool_calls": None}
                }

                final_flat_results.append(flat_item)
                task_id_counter += 1

            print(f"    → 완료 (추출된 턴 수: {len(call_turns)}개, possible={scenario['possible']})")

    # 5. JSONL 저장
    OUTPUT_PATH = DATA_DIR / "my_eval_arg_accuracy_dialogs2.jsonl"
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for item in final_flat_results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("\n" + "=" * 60)
    print(f"✅ 데이터셋 생성 및 포맷 변환 완료!")
    print(f"   저장 경로: {OUTPUT_PATH}")
    print(f"   총 평가 항목(턴) 수: {len(final_flat_results)}개")
    print("=" * 60)

if __name__ == "__main__":
    main()
