"""
generate_queries_v5.py
[목적]
order_intent_router 평가용 중간 질의 데이터셋을 생성합니다.
- 사용자 첫 발화 기준의 라우팅 평가에 집중합니다.
- 실제 DB에서 조회한 user_id / order_id를 사용합니다.
- 상위 router 기준 5개 tool만 정답 라벨로 사용합니다.
- 결과는 JSON / JSONL 두 형식으로 저장합니다.
"""

import csv
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import DATA_DIR, PROJECT_ROOT, FASHION_CSV, CLOTHES_CSV, TOOLS_PATH

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT))

from ecommerce.backend.app.database import SessionLocal
import ecommerce.backend.app.models  # noqa: F401  # mapper 초기화용
from ecommerce.backend.app.router.users.crud import get_user_by_email
from ecommerce.backend.app.router.orders.crud import get_orders_by_user_id

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OUTPUT_JSON_PATH = DATA_DIR / "intermediate_queries_v1.json"
TARGET_USER_COUNT = 3
SAMPLES_PER_SCENARIO = 10

ROLE_POOL = [
    {"role": "A", "desc": "명확한 질문, 정중체, 쉬운 샘플 중심"},
    {"role": "B", "desc": "구어체, 짧은 발화, 오타/축약 포함"},
    {"role": "C", "desc": "복합 질문, 간접 표현, 혼동 유도 샘플 중심"},
]

DIFFICULTY_DIST = ["easy"] * 2 + ["medium"] * 3 + ["hard"] * 5
CONFUSION_PAIRS = {
    "shipping": "cancel",
    "exchange": "refund",
    "refund": "exchange",
    "cancel": "refund",
    "get_user_orders": "shipping",
}

# order_intent_router 상위 라우팅 기준 5개 tool만 사용
SCENARIOS = [
    {
        "name": "배송 조회",
        "expected_tool": "shipping",
        "required_status": ["shipped", "delivered"],
        "include_order": True,
    },
    {
        "name": "교환 신청",
        "expected_tool": "exchange",
        "required_status": ["paid", "preparing", "shipped", "delivered"],
        "include_order": True,
    },
    {
        "name": "환불/반품 신청",
        "expected_tool": "refund",
        "required_status": ["shipped", "delivered"],
        "include_order": True,
    },
    {
        "name": "주문 취소",
        "expected_tool": "cancel",
        "required_status": ["paid", "preparing"],
        "include_order": True,
    },
    {
        "name": "주문 내역 조회",
        "expected_tool": "get_user_orders",
        "required_status": [],
        "include_order": False,
    },
]


def load_eval_users() -> list[dict[str, Any]]:
    """평가용 후보 사용자 이메일 목록을 로드합니다."""
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
                users.append({
                    "email": email,
                    "actions": {act["type"]: act.get("data", {}) for act in item.get("action", [])},
                })
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



def pick_product_info(samples: list[dict[str, str]]) -> dict[str, str]:
    if not samples:
        return {}
    row = random.choice(samples)
    return {
        k: str(v).strip()
        for k, v in row.items()
        if str(v).strip() and str(v).strip().lower() != "nan"
    }



def get_real_orders_with_status(user_email: str) -> tuple[Optional[int], list[dict[str, Any]]]:
    """실제 DB 기준 user_id / orders를 조회합니다."""
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
    """eval_data 후보 중 실제 주문이 있는 사용자만 추려 3명을 선택합니다."""
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

    # 계정 A/B/C 역할 부여
    selected = candidates[:target_count]
    users_with_roles: list[dict[str, Any]] = []
    for role_info, candidate in zip(ROLE_POOL, selected, strict=True):
        merged = {**candidate, **role_info}
        users_with_roles.append(merged)
    return users_with_roles



def filter_orders_for_scenario(orders: list[dict[str, Any]], scenario: dict[str, Any]) -> list[dict[str, Any]]:
    required = [s.lower() for s in scenario.get("required_status", [])]
    if not required:
        return list(orders)
    return [o for o in orders if o["status"].lower() in required]



def select_role_pool(users_with_roles: list[dict[str, Any]], difficulty: str) -> list[dict[str, Any]]:
    if difficulty == "easy":
        return [u for u in users_with_roles if u["role"] == "A"] or users_with_roles
    if difficulty == "medium":
        return [u for u in users_with_roles if u["role"] in {"A", "B"}] or users_with_roles
    return [u for u in users_with_roles if u["role"] in {"B", "C"}] or users_with_roles



def get_query_system_prompt(
    role_info: dict[str, Any],
    scenario: dict[str, Any],
    difficulty: str,
    confusion_pair: Optional[str],
    tool_info: Optional[dict[str, Any]],
) -> str:
    role_desc = role_info["desc"]
    role_name = role_info["role"]
    expected_tool = scenario["expected_tool"]
    tool_desc = tool_info.get("description", "") if tool_info else ""

    confusion_text = (
        f"- Hard 난이도이므로 `{confusion_pair}` 와 헷갈릴 수 있는 표현을 자연스럽게 섞으세요.\n"
        if confusion_pair
        else ""
    )

    return f"""당신은 이커머스 에이전트 챗봇의 order_intent_router 평가용 데이터셋 설계 도우미입니다.
고객이 입력할 자연스러운 한국어 발화(가능하면 한 문장, 길어도 두 문장)를 1개 생성하세요.

# 현재 고객 설정
- 계정 역할: {role_name}
- 스타일: {role_desc}

# 현재 생성 목표
- 시나리오: {scenario['name']}
- 정답 tool: {expected_tool}
- 난이도: {difficulty}
{confusion_text}
# 정답 tool 설명
- {tool_desc}

# 매우 중요한 제약
1. 이번 데이터셋은 상위 router 평가용입니다. 정답 tool은 반드시 아래 5개 중 하나여야 합니다.
   - shipping
   - exchange
   - refund
   - cancel
   - get_user_orders
2. 교환 관련 질문은 배송 전/후 세부 처리와 무관하게 상위 라우팅 기준으로 exchange가 정답이 되도록 작성하세요.
3. 환불/반품은 이미 받은 상품 또는 배송 완료/배송 중 반품 문맥이 드러나게 하세요.
4. 주문 취소는 발송 전 취소 의도가 드러나게 하세요.
5. 주문 내역 조회는 전체 목록/최근 주문 리스트를 묻는 표현이 되게 하세요.
6. 배송 조회는 특정 주문의 현재 위치/배송 상태를 묻는 표현이 되게 하세요.
7. 어려운 질문은 단순히 길게 쓰지 말고, 부정 표현/간접 표현/혼동되는 맥락을 활용하세요.
8. 주문번호가 필요한 경우에는 {{ORDER_ID}} placeholder를 사용하세요.
9. 출력은 반드시 순수 JSON 객체만 반환하세요. 마크다운, 설명문, 코드블록을 넣지 마세요.

# 반환 JSON 형식
{{
  "query": "생성된 발화",
  "annotation_rationale": "왜 {expected_tool}로 라우팅되어야 하는지에 대한 근거"
}}
"""



def build_query_prompt(
    scenario: dict[str, Any],
    product_info: dict[str, Any],
    order: Optional[dict[str, Any]],
    difficulty: str,
    confusion_pair: Optional[str],
    tool_info: Optional[dict[str, Any]],
) -> str:
    product_str = json.dumps(product_info, ensure_ascii=False)
    order_status = order["status"].upper() if order else "N/A"
    order_id_hint = order["order_id"] if order else "N/A"
    expected_tool = scenario["expected_tool"]
    tool_desc = tool_info.get("description", "") if tool_info else ""

    order_constraints = ""
    if scenario.get("include_order", False) and order:
        order_constraints = f"""
- 이 샘플은 특정 주문 기반입니다.
- 실제 주문 상태: {order_status}
- 실제 주문번호 placeholder 대상: {order_id_hint}
- 생성 문장에 주문번호가 들어가야 할 때는 반드시 {{ORDER_ID}} 또는 {{{{ORDER_ID}}}} 를 사용하세요.
"""
    else:
        order_constraints = """
- 이 샘플은 전체 주문 목록 조회 중심입니다.
- 특정 주문번호가 없어도 자연스럽게 성립해야 합니다.
- 가능하면 주문번호를 모른다는 맥락이나 최근 주문 목록을 보고 싶다는 맥락을 활용하세요.
"""

    return f"""
다음 정보를 바탕으로 사용자의 첫 발화를 생성하세요.
- 시나리오: {scenario['name']}
- 정답 tool: {expected_tool}
- 도구 설명: {tool_desc}
- 난이도: {difficulty}
- 혼동 유도 대상: {confusion_pair or '없음'}
- 참조 상품 정보: {product_str}
{order_constraints}
[중요]
- 질문은 실제 사용자 발화처럼 자연스러워야 합니다.
- 정답은 반드시 {expected_tool} 이어야 합니다.
- 다른 tool로도 읽힐 수 있는 단서를 일부 넣더라도, 최종적으로는 {expected_tool} 로 해석되는 문장이어야 합니다.
- annotation_rationale에는 왜 {expected_tool} 인지 구체적으로 적으세요.
"""



def parse_json_response(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()
    return json.loads(raw)



def generate_query(
    scenario: dict[str, Any],
    product_info: dict[str, Any],
    order: Optional[dict[str, Any]],
    role_info: dict[str, Any],
    difficulty: str,
    confusion_pair: Optional[str],
    tool_info: Optional[dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    system_prompt = get_query_system_prompt(role_info, scenario, difficulty, confusion_pair, tool_info)
    user_prompt = build_query_prompt(scenario, product_info, order, difficulty, confusion_pair, tool_info)

    try:
        raw = (
            client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,
                max_tokens=800,
            )
            .choices[0]
            .message.content.strip()
        )
        data = parse_json_response(raw)
        user_query = str(data.get("query", "")).strip()
        rationale = str(data.get("annotation_rationale", "")).strip()

        if order:
            user_query = user_query.replace("{{ORDER_ID}}", order["order_id"]).replace("{ORDER_ID}", order["order_id"])

        if not user_query:
            return None, None
        return user_query, rationale
    except Exception as e:
        print(f"[ERROR] 생성 에러 ({scenario['name']} / {difficulty}): {e}")
        return None, None



def build_record(
    idx: int,
    role_info: dict[str, Any],
    scenario: dict[str, Any],
    difficulty: str,
    user_query: str,
    rationale: str,
    order: Optional[dict[str, Any]],
    confusion_pair: Optional[str],
) -> dict[str, Any]:
    expected_tool = scenario["expected_tool"]
    return {
        "id": f"eval_{idx:03d}",
        "user_id": role_info["user_id"],
        "user_role": role_info["role"],
        "scenario_name": scenario["name"],
        "difficulty": difficulty,
        "example_query": user_query,
        "expected_tool": expected_tool,
        "confusion_pair": confusion_pair,
        "has_order_id": bool(order and order["order_id"] in user_query),
        "annotation_rationale": rationale,
        "meta": {
            "user_email": role_info["email"],
            "order_id": order["order_id"] if order else None,
            "order_status": order["status"] if order else None,
            "router_level": "top_level_only",
        },
    }



def save_outputs(records: list[dict[str, Any]]) -> None:
    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)



def summarize(records: list[dict[str, Any]], users_with_roles: list[dict[str, Any]]) -> None:
    print("\n[요약]")
    print("- 선택된 DB 사용자 3명:")
    for u in users_with_roles:
        print(f"  - user_id={u['user_id']} / email={u['email']} / role={u['role']} ({u['desc']})")

    tool_counts: dict[str, int] = {}
    hard_count = 0
    for r in records:
        tool_counts[r["expected_tool"]] = tool_counts.get(r["expected_tool"], 0) + 1
        if r["difficulty"] == "hard":
            hard_count += 1

    print("- tool별 개수:")
    for tool_name in ["shipping", "exchange", "refund", "cancel", "get_user_orders"]:
        print(f"  - {tool_name}: {tool_counts.get(tool_name, 0)}")
    print(f"- hard 샘플 수: {hard_count}")
    print(f"- JSON 저장: {OUTPUT_JSON_PATH}")



def main() -> None:
    print("=" * 72)
    print("[1단계] order_intent_router 평가용 사용자 질의 50개 생성")
    print("- 실제 DB user_id / order_id 사용")
    print("- 상위 router 기준 5개 tool만 사용")
    print("=" * 72)

    fashion_samples = load_csv_samples(FASHION_CSV, n=100)
    clothes_samples = load_csv_samples(CLOTHES_CSV, n=100)
    all_samples = fashion_samples + clothes_samples

    raw_users = load_eval_users()
    if not raw_users:
        raise RuntimeError("eval_data.jsonl 에서 사용자 목록을 읽지 못했습니다.")

    users_with_roles = select_users_from_db(raw_users, target_count=TARGET_USER_COUNT)
    tools_info = load_tools()
    tools_map = {t["function"]["name"]: t["function"] for t in tools_info if t.get("type") == "function"}

    records: list[dict[str, Any]] = []
    total_count = 0

    for scenario in SCENARIOS:
        print(f"\n>>> 시나리오 '{scenario['name']}' 생성 중")
        expected_tool = scenario["expected_tool"]
        tool_info = tools_map.get(expected_tool)

        for i in range(SAMPLES_PER_SCENARIO):
            difficulty = DIFFICULTY_DIST[i]
            pool = select_role_pool(users_with_roles, difficulty)
            role_info = random.choice(pool)

            candidate_orders = filter_orders_for_scenario(role_info["orders"], scenario)
            order = random.choice(candidate_orders) if candidate_orders else None

            if scenario.get("include_order", False) and not order:
                print(f"  [WARN] 주문 부족: {scenario['name']} / role={role_info['role']} / user_id={role_info['user_id']}")
                continue

            confusion_pair = CONFUSION_PAIRS.get(expected_tool) if difficulty == "hard" else None
            product_info = pick_product_info(all_samples)

            user_query, rationale = generate_query(
                scenario=scenario,
                product_info=product_info,
                order=order,
                role_info=role_info,
                difficulty=difficulty,
                confusion_pair=confusion_pair,
                tool_info=tool_info,
            )
            if not user_query:
                continue

            total_count += 1
            records.append(
                build_record(
                    idx=total_count,
                    role_info=role_info,
                    scenario=scenario,
                    difficulty=difficulty,
                    user_query=user_query,
                    rationale=rationale,
                    order=order,
                    confusion_pair=confusion_pair,
                )
            )
            print(
                f"  [{i + 1}/{SAMPLES_PER_SCENARIO}] {difficulty} 완료 "
                f"(user_id={role_info['user_id']}, role={role_info['role']}) -> tool: {expected_tool}"
            )

    save_outputs(records)
    print(f"\n✅ 완료! 총 {len(records)}개 저장")
    summarize(records, users_with_roles)


if __name__ == "__main__":
    main()
