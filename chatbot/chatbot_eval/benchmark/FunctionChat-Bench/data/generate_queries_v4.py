"""
generate_queries_v4.py
[목적]
기존 generate_arg_accuracy_dialog_dataset.py 분리 1단계: 사용자 질문(Query)만 먼저 생성하여 중간 파일(intermediate_queries_v4.json)에 저장합니다.
생성된 질문은 사용자가 직접 검토/수정할 수 있습니다.
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
sys.path.insert(0, str(PROJECT_ROOT))

from ecommerce.platform.backend.app.database import SessionLocal
import ecommerce.platform.backend.app.models  # SQLAlchemy 모델 레지스트리 선 로드 (mapper 초기화용)
from ecommerce.platform.backend.app.router.users.crud import get_user_by_email
from ecommerce.platform.backend.app.router.orders.crud import get_orders_by_user_id
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-4o-mini"
OUTPUT_PATH = DATA_DIR / "intermediate_queries_v5.json"

def load_eval_users() -> list:
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
    if not users:
        users.append({"email": "test2@example.com", "actions": {}})
    return users

def get_real_orders_with_status(user_email: str, target_actions: dict = None) -> tuple[int, list[dict]]:
    user_id_map = {"test@example.com": 1, "test2@example.com": 2, "test3@example.com": 3}
    user_id = user_id_map.get(user_email, 1)

    result = []
    try:
        from datetime import datetime
        session = SessionLocal()
        user = get_user_by_email(session, user_email)
        if user: user_id = user.id
        orders, _ = get_orders_by_user_id(session, user_id, limit=50)
        for o in orders:
            delivered_at = None
            if hasattr(o, "shipping_info") and o.shipping_info:
                delivered_at = o.shipping_info.delivered_at
            days_since = None
            if delivered_at: days_since = (datetime.now() - delivered_at).days
            result.append({
                "order_id": o.order_number,
                "status": str(o.status.value if hasattr(o.status, 'value') else o.status),
                "shipping_fee": float(o.shipping_fee) if o.shipping_fee is not None else 0.0,
                "days_since_delivery": days_since,
            })
        session.close()
    except Exception as e:
        print(f"[WARN] ORM DB 조회 실패: {e}")

    target_actions = target_actions or {}
    for action_type, data in target_actions.items():
        o_num = data.get("order_number")
        if o_num and not any(o["order_id"] == o_num for o in result):
            status = "delivered"
            if action_type == "주문취소": status = "paid"
            elif action_type == "환불": status = "delivered"
            elif action_type == "교환": status = "shipped"
            result.append({
                "order_id": o_num, "status": status,
                "shipping_fee": 3000.0,
                "days_since_delivery": 2 if status == "delivered" else None
            })
    return user_id, result

def load_tools() -> list:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        return json.load(f)

def load_csv_samples(path: Path, n: int = 100) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
                if len(rows) >= n: break
    except Exception as e: pass
    return rows

def pick_product_info(samples: list[dict]) -> dict:
    if not samples: return {}
    row = random.choice(samples)
    return {k: str(v).strip() for k, v in row.items() if str(v).strip() and str(v).strip() != "nan"}

SCENARIOS = [
    {"id": 1, "name": "주문 취소", "action": "cancel", "possible": True, "required_status": ["preparing", "paid"], "tools": ["cancel", "shipping"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 2, "name": "환불 신청", "action": "refund", "possible": True, "required_status": ["delivered", "shipped"], "tools": ["refund", "shipping"], "rag_policy": "required", "ux_flow": "direct"},
    {"id": 3, "name": "교환 신청", "action": "exchange", "possible": True, "required_status": ["delivered", "shipped"], "tools": ["exchange", "shipping"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 4, "name": "주문 내역 조회 (주문번호 없음)", "action": "shipping_no_id", "possible": True, "required_status": [], "tools": ["shipping"], "rag_policy": "forbidden", "ux_flow": "direct"},
    {"id": 5, "name": "주문 내역 조회 (주문번호 있음)", "action": "shipping_with_id", "possible": True, "required_status": [], "tools": ["shipping"], "rag_policy": "forbidden", "ux_flow": "direct"},
    {"id": 6, "name": "상품 키워드 검색", "action": "search_by_text_clip", "possible": True, "required_status": [], "tools": ["search_by_text_clip"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 7, "name": "의류 추천", "action": "recommend_clothes", "possible": True, "required_status": [], "tools": ["recommend_clothes"], "rag_policy": "optional", "ux_flow": "direct"},
    # {"id": 8, "name": "이미지 검색", "action": "search_by_image", "possible": True, "required_status": [], "tools": ["search_by_image"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 8, "name": "중고 판매 신청", "action": "used_sale", "possible": True, "required_status": [], "tools": ["open_used_sale_form", "register_used_sale"], "rag_policy": "optional", "ux_flow": "direct"},
    {"id": 9, "name": "리뷰 작성", "action": "review", "possible": True, "required_status": ["delivered"], "tools": ["generate_review_draft", "create_review"], "rag_policy": "optional", "ux_flow": "direct"},
    # {"id": 10, "name": "상품권 등록", "action": "register_gift_card", "possible": True, "required_status": [], "tools": ["register_gift_card"], "rag_policy": "optional", "ux_flow": "direct"},
]

def get_query_system_prompt() -> str:
    return """당신은 이커머스 챗봇 평가용 데이터셋 전문가입니다.
주어진 시나리오상 챗봇에게 입력할 고객의 '자연스러운 한국어 발화(단일 문장)'를 1개 생성하세요.

규칙:
1. output은 반드시 순수 JSON 객체만 반환합니다. (마크다운 백틱 제외)
2. 대화에 주문번호가 언급되어야 할 경우, 무조건 `{ORDER_ID}` 라는 문자열(placeholder) 자체를 포함시켜 출력해야 합니다.
3. 생성된 질문에는 시나리오상 필요한 핵심 정보(단순 변심으로 취소, 사이즈가 안 맞아서 교환 등)가 자연스럽게 포함되어야 합니다.
4. Assistant 응답 등 다른 것은 절대 만들지 말고 오직 사용자의 "query"만 생성하세요.
"""

def build_query_prompt(scenario, product_info, order, user_email):
    action_possible = "가능" if scenario["possible"] else "불가능"
    product_str = json.dumps(product_info, ensure_ascii=False)
    order_status = order["status"].upper()
    
    return f"""
다음 정보를 바탕으로 고객 문장을 생성하세요.
시나리오: {scenario['name']}
주문 상태: {order_status}
해당 시나리오 가능 여부 (주문 상태 기반): {action_possible}

참고 상품 정보:
{product_str}

지정된 반환 JSON 포맷:
{{
  "query": "고객이 입력할 한국어 문장 (주문번호 필요 시 {{ORDER_ID}} 표시)"
}}
"""

def generate_query(scenario, product_info, order, user_email):
    prompt = build_query_prompt(scenario, product_info, order, user_email)
    try:
        raw = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": get_query_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=500,
        ).choices[0].message.content.strip()
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        data = json.loads(raw)
        
        user_query = data.get("query", "")
        # 플레이스홀더를 실제 order_id로 치환
        user_query = user_query.replace("{{ORDER_ID}}", order["order_id"]).replace("{ORDER_ID}", order["order_id"])
        
        # 특정 시나리오 외에는 주문번호가 무조건 명시적으로 포함되도록 강제
        if order["order_id"] not in user_query and scenario["action"] not in ["search_by_text_clip", "recommend_clothes", "used_sale", "shipping_no_id"]:
            user_query += f" (주문번호: {order['order_id']})"
            
        return user_query
    except Exception as e:
        print(f"[ERROR] 생성 에러: {e}")
        return None

def main():
    print("=" * 60)
    print("[1단계] 사용자 질의(Query) 데이터셋 생성 시작")
    print("=" * 60)
    
    all_openai_tools = load_tools()
    fashion_samples = load_csv_samples(FASHION_CSV, n=100)
    clothes_samples = load_csv_samples(CLOTHES_CSV, n=100)
    all_samples = fashion_samples + clothes_samples
    users = load_eval_users()
    
    ACTION_TO_EVAL_TYPE = {"cancel": "주문취소", "refund": "환불", "exchange": "교환", "query": "주문조회"}
    
    queries_data = []
    
    for u_idx, user_info in enumerate(users, start=1):
        user_email = user_info["email"]
        actions = user_info["actions"]
        print(f"\n>>> [{u_idx}/{len(users)}] 유저 '{user_email}' 질문 생성 중")
        
        user_id, all_orders = get_real_orders_with_status(user_email, actions)
        if not all_orders: continue
        
        for s_idx, scenario in enumerate(SCENARIOS, start=1):
            action = scenario.get("action")
            target_eval_type = ACTION_TO_EVAL_TYPE.get(action)
            
            if target_eval_type and target_eval_type in actions:
                target_order_number = actions[target_eval_type].get("order_number")
            else:
                target_order_number = list(actions.values())[0].get("order_number") if actions else None

            # pick order
            required = scenario.get("required_status", [])
            order = None
            if target_order_number:
                matches = [o for o in all_orders if o["order_id"] == target_order_number]
                if matches: order = matches[0]
            if not order:
                matched = [o for o in all_orders if o["status"] in required] if required else all_orders
                order = random.choice(matched) if matched else (random.choice(all_orders) if all_orders else None)
            if not order: continue

            product_info = pick_product_info(all_samples) if all_samples else {}
            
            user_query = generate_query(scenario, product_info, order, user_email)
            if not user_query: continue
            print(f"  ({s_idx}/{len(SCENARIOS)}) '{scenario['name']}' -> 완료 (주문: {order['order_id']}, 가능: {scenario['possible']})")
            
            queries_data.append({
                "scenario": {
                    "id": scenario["id"],
                    "name": scenario["name"],
                    "action": scenario["action"],
                    "tools": scenario.get("tools", []),
                    "possible": scenario["possible"]
                },
                "order": order,
                "user_id": user_id,
                "user_email": user_email,
                "user_query": user_query
            })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(queries_data, f, ensure_ascii=False, indent=2)
        
    print("\n" + "=" * 60)
    print(f"✅ 1단계 데이터셋(Query) 생성 완료!")
    print(f"   저장 경로: {OUTPUT_PATH}")
    print(f"   생성된 항목 수: {len(queries_data)}개")
    print("=" * 60)

if __name__ == "__main__":
    main()
