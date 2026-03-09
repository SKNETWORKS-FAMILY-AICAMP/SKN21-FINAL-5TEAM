"""
generate_arg_accuracy_dialog_dataset.py

[목적]
이커머스 챗봇의 Argument Accuracy 평가를 위한 Dialog 모드 데이터셋을 생성합니다.
기존 버전을 기반으로 아래 내용이 포함된 20개 시나리오 버전입니다:
  1. 실제 DB 주문 ID를 상태(status) 포함하여 조회
  2. 취소/반품/환불/교환이 가능한 경우와 불가능한 경우를 모두 다루는 시나리오 포함
  3. 주문 상태 정책에 따른 ground_truth 생성
  4. [핵심] HITL(Human-In-The-Loop) 반영: 주문번호가 주어지더라도 바로 액션을 진행하지 않고, 반드시 get_user_orders를 통해 확인받도록 강제.
  5. [핵심] 불가능 시나리오 반영: 불가능한 상태라도 봇이 텍스트로 미리 차단하지 않고 get_order_details를 호출하여 시스템적으로 검증하도록 유도.

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
from datetime import datetime
from dotenv import load_dotenv

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import DATA_DIR, PROJECT_ROOT, RAW_DIR, FASHION_CSV, CLOTHES_CSV, TOOLS_PATH

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

OUTPUT_PATH = DATA_DIR / "my_eval_arg_accuracy_dialogs.jsonl"

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
# PROJECT_ROOT를 sys.path에 추가하여 ecommerce 패키지 import 가능하게 함
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ─── OpenAI 설정 ──────────────────────────────────────────────────────────────
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-4o-mini"

# ─── SQLAlchemy ORM 모델 import (모든 관계 설정을 위해 순서대로) ──────────────
from ecommerce.platform.backend.app.router.users.models import User
from ecommerce.platform.backend.app.router.orders.models import Order
from ecommerce.platform.backend.app.router.shipping.models import ShippingInfo
from ecommerce.platform.backend.app.router.carts.models import Cart
from ecommerce.platform.backend.app.router.products.models import Product
from ecommerce.platform.backend.app.router.reviews.models import Review
from ecommerce.platform.backend.app.router.payments.models import Payment
from ecommerce.platform.backend.app.router.points.models import PointHistory
from ecommerce.platform.backend.app.router.user_history.models import UserHistory
from ecommerce.platform.backend.app.database import SessionLocal, engine

# ─── DB 세션 생성 ─────────────────────────────────────────────────────────────
Session = SessionLocal


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
    user_email 사용자의 실제 주문 목록과 user_id를 DB에서 가져옵니다.
    각 주문의 order_number, status, shipping_fee, shipping_info(delivered_at) 포함.
    ORM 기반 쿼리로 성능 최적화됨.
    """
    session = None
    try:
        session = Session()
        
        # 유저 조회
        user = session.query(User).filter(User.email == user_email).first()
        user_id = user.id if user else 1

        # 주문 조회 (ORM 쿼리 - 훨씬 빠름)
        orders_query = session.query(Order).filter(
            Order.user_id == user_id,
            Order.order_number.like('ORD-eval_dataset-%')
        ).limit(50).all()

        orders = []
        for order in orders_query:
            # ShippingInfo 조회
            shipping_info = session.query(ShippingInfo).filter(
                ShippingInfo.order_id == order.id
            ).first()
            
            delivered_at = shipping_info.delivered_at if shipping_info else None
            days_since = None
            if delivered_at:
                days_since = (datetime.now() - delivered_at).days
            
            orders.append({
                "order_id": str(order.order_number),
                "status": str(order.status.value if hasattr(order.status, 'value') else order.status),
                "shipping_fee": float(order.shipping_fee) if order.shipping_fee else 0.0,
                "days_since_delivery": days_since,
            })
        
        print(f"[INFO] 실제 주문 조회 완료: {[o['order_id'] + '(' + o['status'] + ')' for o in orders]}")
        return user_id, orders
    except Exception as e:
        print(f"[WARN] DB 조회 실패: {e}")
    finally:
        if session:
            session.close()
    
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
        temperature=0.7,
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

### 취소 (cancel_order)
- 가능: PAID, PREPARING 상태에서만 가능
- 처리: 즉시 취소, 전액 환불, 재고 자동 복구
- 불가 시: 현재 상태에서는 취소가 불가능함을 안내 (tool 미호출 or 오류 반환)

### 반품/환불 (check_refund_eligibility → register_return_request)
- 가능: SHIPPED 또는 DELIVERED(7일 이내)
- 판매자 귀책: 전액 환불
- 구매자 귀책: 왕복 배송비(배송비×2) 차감 후 환불
- 배송 전(PAID/PREPARING) 상태: 환불 불가 → cancel_order 안내

### 교환 (check_exchange_eligibility → 분기)
- PAID/PREPARING: change_product_option (무료)
- SHIPPED/DELIVERED 7일 이내: register_exchange_request (유료, 왕복 배송비)
- 불가: CANCELLED, REFUNDED, DELIVERED 7일 초과
"""

# ─── 시나리오 정의 (11개) ──────────────────────────────────────────────────────
SCENARIOS = [
    {"id": 1,  "name": "주문취소 (가능: PREPARING)", "action": "cancel",   "possible": True,  "required_status": ["preparing", "paid"], "tools": ["get_user_orders", "cancel_order"],            "rag_policy": "optional",  "ux_flow": "select"},
    {"id": 2,  "name": "환불 (가능: DELIVERED)",    "action": "refund",   "possible": True,  "required_status": ["delivered"],        "tools": ["get_user_orders", "check_refund_eligibility"], "rag_policy": "required",  "ux_flow": "select"},
    {"id": 3,  "name": "교환 (가능: DELIVERED 유료)", "action": "exchange", "possible": True,  "required_status": ["delivered"],        "tools": ["get_user_orders", "check_exchange_eligibility"], "rag_policy": "optional",  "ux_flow": "select"},
    {"id": 4,  "name": "주문 내역 조회 (주문번호 없음)", "action": "query",   "possible": True,  "required_status": [],                   "tools": ["get_user_orders"],          "rag_policy": "forbidden", "ux_flow": "direct"},
    {"id": 5,  "name": "주문 내역 조회 (주문번호 있음)", "action": "query",   "possible": True,  "required_status": [],                   "tools": ["get_order_details"],        "rag_policy": "forbidden", "ux_flow": "direct"},
    {"id": 6,  "name": "배송 현황 조회",             "action": "query",    "possible": True,  "required_status": ["shipped"],          "tools": ["get_user_orders", "get_shipping_details"],    "rag_policy": "forbidden", "ux_flow": "select"},
    {"id": 7,  "name": "리뷰 등록",                  "action": "review",   "possible": True,  "required_status": ["delivered"],        "tools": ["get_user_orders", "create_review"],           "rag_policy": "forbidden", "ux_flow": "select"},
    {"id": 8, "name": "교환 (불가: CANCELLED)",   "action": "exchange", "possible": False, "required_status": ["cancelled"],        "tools": ["get_user_orders", "get_order_details"],       "rag_policy": "optional",  "ux_flow": "select"},
    {"id": 9, "name": "FAQ 검색 (배송 정책)",         "action": "faq",      "possible": True,  "required_status": [],                   "tools": ["search_knowledge_base"],    "rag_policy": "required",  "ux_flow": "direct"},
    {"id": 10, "name": "FAQ 검색 (취소/반품 정책)",    "action": "faq",      "possible": True,  "required_status": [],                   "tools": ["search_knowledge_base"],    "rag_policy": "required",  "ux_flow": "direct"},
    {"id": 11, "name": "결제 수단 변경",               "action": "other",    "possible": True,  "required_status": ["paid", "preparing"],"tools": ["get_user_orders", "update_payment_method"],   "rag_policy": "optional",  "ux_flow": "select"},
]

# ─── acceptable_arguments ─────────────────────────────────────────────────────
ACCEPTABLE = {
    "reason": [
        "단순 변심", "simple_change_of_mind", "change_of_mind", "customer_preference",
        "사이즈가 안 맞아요", "색상이 화면과 달라요", "배송이 너무 늦어서 취소합니다",
        "상품이 파손되었어요", "다른 상품이 배송됨", "마음에 들지 않음"
    ],
    "size": ["XS", "S", "M", "L", "XL", "90", "95", "100", "105", "FREE", "free"],
    "color": ["black", "white", "ivory", "cream", "beige", "navy", "gray", "brown",
              "블랙", "화이트", "아이보리", "크림", "베이지", "네이비", "그레이", "브라운"],
    "rating": [1, 2, 3, 4, 5],
    "payment_method": ["카드", "계좌이체", "CARD", "BANK_TRANSFER", "카카오페이", "네이버페이"],
}



# ─── 시스템 프롬프트 ──────────────────────────────────────────────────────────
def get_system_prompt(user_id: int) -> str:
    return f"""당신은 이커머스 챗봇 평가용 데이터셋 전문가입니다.
주어진 시나리오에 따라 멀티턴 대화와 Ground Truth tool call을 생성합니다.

{ORDER_STATUS_POLICY}

규칙:
1. output은 반드시 순수 JSON 객체만 반환합니다. 마크다운 코드블록, 설명 텍스트 없이.
2. 모든 tool call에는 user_id: {user_id}을(를) 반드시 포함합니다.
3. order_id는 반드시 {{ORDER_ID}} placeholder를 사용해야 합니다. tool_calls의 arguments와 query 대화 내용 모두에 {{ORDER_ID}}를 명시적으로 포함하세요.
4. dialog는 멀티턴으로, 필수 argument(주문번호, 취소사유, 교환사유 등)가 대화 안에 구체적으로 포함되어야 합니다.
5. Slot Filling 질문은 생성하지 않습니다. (type_of_output: "slot" 턴은 만들지 않음)
6. type_of_output: "call" 인 턴이 반드시 2개 이상 포함되어야 합니다.
7. 상품 정보는 반드시 제공된 CSV 데이터를 기반으로 생성합니다. 임의 상품명 생성 금지.
8. [중요] 주문 상태(order_status)에 맞게 tool call을 생성하세요.
9. [중요] user_id는 항상 {user_id}로 고정합니다. 이 챗봇은 로그인된 사용자(user_id={user_id})의 컨텍스트에서 동작하므로, 대화에서 user_id를 사용자에게 묻지 않습니다.

10. [HITL (Human-in-the-loop) 핵심 규칙 - 실제 클라이언트 UX 흐름]
    사용자가 취소/환불/교환/리뷰 등을 요청할 때, 설령 **주문번호를 같이 제공하더라도** 
    실제 클라이언트에서는 사용자에게 주문 내역을 띄워주고 확인을 받는 절차(HITL)를 진행합니다.
    따라서:
    1단계: 사용자가 정보를 제공하여 요청 (예: "{{ORDER_ID}} 주문 취소할래. 단순변심이야")
    → 챗봇은 이 주문번호로 바로 취소 도구를 호출하는 것이 아니라,
      반드시 `get_user_orders(user_id={user_id}, requires_selection=True, action_context="cancel/refund/exchange")` 를 호출하여 
      목록 UI를 띄워야 합니다. 이것이 턴1의 Ground Truth입니다.
    
    2단계: 챗봇이 "목록에서 주문을 선택해주세요" 라고 안내.
    → 사용자가 목록 UI 프론트엔드를 통해 "{{ORDER_ID}} 주문이요, 사유는 단순 변심입니다" 와 같이 선택.
    → 이때 챗봇은 해당 action tool (cancel_order, check_refund_eligibility 등)을 호출합니다.

11. [핵심 - 불가능 케이스 검증 방식]
    possible이 False인 시나리오에서는:
    - 1단계: 위와 동일하게 무조건 get_user_orders 호출
    - 2단계: 사용자가 해당하는 불가 주문을 선택하면, **챗봇이 임의로 텍스트로 거절해서는 안 됩니다.**
      반드시 `get_order_details` (또는 check_refund_eligibility)를 호출하여 백엔드/시스템 상태를 확인하는 call을 만들어야 합니다.
      이것이 불가 시나리오 턴 2의 Ground Truth입니다.
    - 대화 맥락에서 assistant가 시스템 호출 없이 섣불리 불가하다고 말하지 않도록 주의하세요.

12. [핵심 - 필수 파라미터 대화 포함]
    - cancel_order: 주문번호 + 취소 사유
    - check_refund_eligibility: 주문번호 + 환불 사유
    - check_exchange_eligibility: 주문번호 + 교환 사유
"""


def build_prompt_for_scenario(
    scenario: dict,
    product_info: dict,
    dialog_num: int,
    order: dict,
    user_email: str,
    user_id: int,
) -> str:
    tool_names_str = ", ".join(scenario["tools"])
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
[대화 흐름 - 주문 선택 UX (반드시 이 흐름을 따르세요: HITL 구조)]

턴 1 (type_of_output: "call"):
  - 사용자가 처음부터 주문번호를 함께 요청하게 합니다. 
    예: "{{ORDER_ID}} 주문을 취소하고 싶어요. 단순 변심입니다." 또는 "{{ORDER_ID}} 환불받고 싶은데요, 사이즈가 안 맞네요."
  - **[중요]** 주문번호가 있더라도, 시스템은 사용자가 화면에서 직접 클릭해 확인(HITL)하도록 유도합니다.
  - ground_truth: get_user_orders(user_id={user_id}, requires_selection=True, action_context="{action_context or ''}")

턴 2 (type_of_output: "call"):
  - assistant는 턴 1 이후 "주문 내역에서 원하시는 주문을 선택해주세요." 등으로 명확히 안내합니다.
  - 사용자가 "네, 이 주문({{ORDER_ID}})입니다." 처럼 선택을 확정합니다.
  - **[중요 - 가능 시나리오(possible=true)]**: 
    ground_truth: 해당 action의 최종 tool 호출 (예: cancel_order, check_refund_eligibility 등)
  - **[중요 - 불가능 시나리오(possible=false)]**: 
    ground_truth: 시스템이 주문 상태를 확인하기 위해 `get_order_details` 호출 
"""
    else:
        flow_instruction = """
[대화 흐름 - 직접 요청]
사용자가 필요한 정보를 직접 대화에서 제공합니다.
type_of_output이 "call"인 턴이 반드시 2개 이상 포함되어야 합니다.
"""

    turns_example = f"""
  "turns": [
    {{
      "turn_num": 1,
      "query": [
        {{"role": "user", "content": "{{ORDER_ID}} 주문을 취소하고 싶어요. 단순 변심입니다."}}
      ],
      "ground_truth": {{
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {{
            "id": "call_1",
            "type": "function",
            "function": {{
              "name": "get_user_orders",
              "arguments": "{{\\"user_id\\": {user_id}, \\"requires_selection\\": true, \\"action_context\\": \\"cancel\\"}}"
            }}
          }}
        ]
      }},
      "type_of_output": "call",
      "acceptable_arguments": {{}}
    }},
    {{
      "turn_num": 2,
      "query": [
        {{"role": "user", "content": "{{ORDER_ID}} 주문을 취소하고 싶어요. 단순 변심입니다."}},
        {{"role": "assistant", "content": "주문 목록에서 취소하실 주문을 선택하여 주시기 바랍니다."}},
        {{"role": "user", "content": "{{ORDER_ID}} 주문. 확인했습니다."}}
      ],
      "ground_truth": {{
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {{
            "id": "call_2",
            "type": "function",
            "function": {{
              "name": "cancel_order",
              "arguments": "{{\\"order_id\\": \\"{{ORDER_ID}}\\", \\"user_id\\": {user_id}, \\"reason\\": \\"단순 변심\\"}}"
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
주어진 시나리오와 상품 정보를 바탕으로, 사용자와 챗봇 간의 대화(turns)를 생성하세요.

시나리오: {scenario['name']} (시나리오 ID: {scenario['id']})
다이얼로그 번호: {dialog_num}
평가 대상 tools: {tool_names_str}
RAG 정책: {scenario['rag_policy']}
주문 상태: {order_status}
이 시나리오의 요청 처리 가능 여부: {action_possible}
UX 흐름: {ux_flow}

{flow_instruction}

참고 상품 정보 (CSV 기반, 이 정보만 사용할 것):
{product_str}

다음 형식으로 JSON을 반환하세요:

{{
  "scenario_id": "{scenario['id']}-{dialog_num}",
  "scenario_name": "{scenario['name']}",
  "order_status": "{order_status}",
  "order_id_source": "get_user_orders:{user_email}",
  "rag_policy": "{scenario['rag_policy']}",
  "possible": {str(scenario['possible']).lower()},
  "source_file": "AI_Hub CSV",
  "source_row_id": "<CSV에서 참조한 행 정보>",
  "evidence": "<사용한 근거>",
{turns_example}
}}

중요:
- 위 예시는 취소 시나리오(가능) 기준입니다. 불가능(possible=false) 조건이라면 턴 2의 ground_truth name이 `get_order_details`가 되도록 생성해야 합니다.
- type_of_output이 "call"인 턴이 반드시 2개 이상 포함되어야 합니다.
- query 배열은 해당 turn까지의 전체 대화 기록을 포함해야 합니다 (누적 방식).
- arguments는 JSON 문자열로 직렬화하세요.
- acceptable_arguments는 type_of_output=="call"인 모든 턴에 반드시 포함해야 합니다.
- 해당되는 파라미터가 없다면 빈 딕셔너리 {{}} 로 설정하세요.
- tool call이 없는 턴은 tool_calls를 null로 설정하고 content에 텍스트를 넣으세요.
- 모든 대화는 **한국어**로 작성하세요.
"""


# ─── 후처리 ───────────────────────────────────────────────────────────────────
def replace_order_id_in_turns(turns: list, order_id: str) -> list:
    """{ORDER_ID} placeholder를 실제 주문 ID로 치환합니다."""
    for t in turns:
        gt = t.get("ground_truth", {})
        if gt and isinstance(gt, dict):
            for tc in gt.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", "")
                if isinstance(args, str):
                    fn["arguments"] = args.replace("{ORDER_ID}", order_id)
                elif isinstance(args, dict):
                    fn["arguments"] = json.dumps(args, ensure_ascii=False).replace("{ORDER_ID}", order_id)

        has_id_in_query = False
        for msg in t.get("query", []):
            if isinstance(msg.get("content"), str):
                if "{ORDER_ID}" in msg["content"]:
                    has_id_in_query = True
                msg["content"] = msg["content"].replace("{ORDER_ID}", order_id)

        if t.get("type_of_output") == "call" and not has_id_in_query:
            if t.get("query"):
                t["query"][-1]["content"] += f" 주문번호는 {order_id} 입니다."
    return turns


def ensure_acceptable_arguments(turns: list) -> list:
    for t in turns:
        if t.get("type_of_output") == "call" and "acceptable_arguments" not in t:
            t["acceptable_arguments"] = {}
    return turns


def filter_call_turns_only(turns: list) -> list:
    return [t for t in turns if t.get("type_of_output") == "call"]


# ─── 다이얼로그 생성 ──────────────────────────────────────────────────────────
def generate_dialog(
    scenario: dict,
    product_info: dict,
    dialog_num: int,
    tools: list,
    order: dict,
    user_email: str,
    user_id: int,
) -> dict | None:
    prompt = build_prompt_for_scenario(scenario, product_info, dialog_num, order, user_email, user_id)
    system_prompt = get_system_prompt(user_id)
    try:
        raw = call_gpt(system_prompt, prompt)
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        data = json.loads(raw.strip())

        # 실제 주문 ID 치환
        data["turns"] = replace_order_id_in_turns(data.get("turns", []), order["order_id"])

        # acceptable_arguments 보완
        data["turns"] = ensure_acceptable_arguments(data.get("turns", []))

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
        data["tools_count"] = len(tools)
        data["tools"] = tools
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


# ─── 메인 실행 ────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Argument Accuracy Dialog 데이터셋 생성 시작 (Multi-User 지원)")
    print("주문 번호가 있어도 get_user_orders 호출 및 불가능 케이스 get_order_details 검증 필수")
    print("=" * 60)

    # 1. tools 로드
    tools = load_tools()
    print(f"[INFO] tools.json 로드 완료: {len(tools)}개 tool")

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

    results = []
    serial_counter = 1
    total_dialog_idx = 1

    # 4. 유저별 순회
    for u_idx, user_info in enumerate(users, start=1):
        user_email = user_info["email"]
        actions = user_info["actions"]
        print(f"\n>>> [{u_idx}/{len(users)}] 유저 '{user_email}' 데이터 생성 시작")

        user_id, all_orders = get_real_orders_with_status(user_email)
        if not all_orders:
            print(f"  [ERROR] 유저 {user_email}의 주문 정보를 가져오지 못했습니다. 건너뜁니다.")
            continue

        # 유저별로 11개 시나리오 실행
        for s_idx, scenario in enumerate(SCENARIOS, start=1):
            print(f"  ({s_idx}/11) 시나리오 '{scenario['name']}' 생성 중...")

            action = scenario.get("action")
            target_eval_type = ACTION_TO_EVAL_TYPE.get(action)
            target_order_number = actions.get(target_eval_type, {}).get("order_number") if target_eval_type else None

            # 시나리오에 맞는 주문 선택
            order = pick_order_for_scenario(scenario, all_orders, target_order_number)
            if not order:
                print(f"    → 맞는 상태의 주문 없음. 건너뜁니다.")
                continue

            print(f"    → 사용 주문: {order['order_id']} (상태: {order['status']})")

            product_info = pick_product_info(all_samples) if all_samples else {}

            # 대화 생성
            dialog_data = generate_dialog(scenario, product_info, total_dialog_idx, tools, order, user_email, user_id)

            if dialog_data is None:
                print(f"    → 재시도 중...")
                dialog_data = generate_dialog(scenario, product_info, total_dialog_idx, tools, order, user_email, user_id)

            if dialog_data is None:
                print(f"    → 생성 실패, 건너뜁니다.")
                continue

            # serial_num 보정 및 데이터 구조 검증
            turns = dialog_data.get("turns", [])
            if not isinstance(turns, list):
                print(f"    → [ERROR] turns가 리스트가 아닙니다. 건너뜁니다.")
                continue

            validated_turns = []
            for t in turns:
                if not isinstance(t, dict): continue
                t["serial_num"] = serial_counter
                serial_counter += 1
                validated_turns.append(t)
            
            dialog_data["turns"] = validated_turns
            results.append(dialog_data)
            
            total_dialog_idx += 1
            call_count = sum(1 for t in validated_turns if isinstance(t, dict) and t.get("type_of_output") == "call")
            print(f"    → 완료 ({len(validated_turns)} turns, call 타입: {call_count}개, possible={scenario['possible']})")

    # 5. JSONL 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("\n" + "=" * 60)
    print(f"✅ 데이터셋 생성 완료!")
    print(f"   총 유저 수    : {len(users)}명")
    print(f"   총 시나리오 수 : {len(SCENARIOS)}개")
    print(f"   최종 Dialog 수 : {len(results)}개")
    total_calls = sum(
        sum(1 for t in item.get("turns", []) if t.get("type_of_output") == "call")
        for item in results
    )
    possible_count = sum(1 for item in results if item.get("possible") is True)
    impossible_count = sum(1 for item in results if item.get("possible") is False)
    print(f"   총 call 턴 수: {total_calls}개")
    print(f"   가능 시나리오: {possible_count}개")
    print(f"   불가 시나리오: {impossible_count}개")
    print(f"   저장 경로    : {OUTPUT_PATH}")
    print("=" * 60)
    print("=" * 60)


if __name__ == "__main__":
    main()
