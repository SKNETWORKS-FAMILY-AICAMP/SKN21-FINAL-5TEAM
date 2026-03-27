"""
generate_queries_v6.py

[목적]
- 15개 기본 평가 데이터셋 생성을 위한 intermediate_queries_v6.json 생성
- LLM을 사용해 실제 사용자 발화처럼 자연스러운 질문을 생성
- eval_data.jsonl의 주문번호와 DB의 실제 user_id를 반영

[출력 형식]
- convert_v6_to_v4.py가 바로 읽을 수 있는 구조:
  scenario / order / user_id / user_email / user_query / meta
"""

import csv
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import DATA_DIR, PROJECT_ROOT, FASHION_CSV, CLOTHES_CSV, TOOLS_PATH

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT))

from ecommerce.backend.app.database import SessionLocal
import ecommerce.backend.app.models  # noqa: F401
from ecommerce.backend.app.router.users.crud import get_user_by_email

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OUTPUT_JSON_PATH = DATA_DIR / "intermediate_queries.json"
EVAL_DATA_PATH = PROJECT_ROOT / "chatbot" / "chatbot_eval" / "benchmarkV2" / "eval_data.jsonl"

STYLE_POOL = [
    "정중하고 명확한 질문",
    "짧은 구어체 질문",
    "약간 우회적이지만 의미는 분명한 질문",
]

SCENARIO_MAP = {
    "주문조회": {
        "name": "배송 조회",
        "action": "shipping",
        "tools": ["shipping"],
        "requires_order": True,
    },
    "교환": {
        "name": "교환 신청",
        "action": "exchange",
        "tools": ["exchange", "change_option"],
        "requires_order": True,
    },
    "환불": {
        "name": "환불/반품 신청",
        "action": "refund",
        "tools": ["refund"],
        "requires_order": True,
    },
    "주문취소": {
        "name": "주문 취소",
        "action": "cancel",
        "tools": ["cancel"],
        "requires_order": True,
    },
    "주문 내역 조회": {
        "name": "주문 내역 조회",
        "action": "get_user_orders",
        "tools": ["get_user_orders"],
        "requires_order": False,
    },
}


def load_tools() -> dict[str, dict[str, Any]]:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        tools = json.load(f)
    return {
        tool["function"]["name"]: tool["function"]
        for tool in tools
        if tool.get("type") == "function"
    }


def load_eval_users() -> list[dict[str, Any]]:
    users = []
    with open(EVAL_DATA_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("type") != "user":
                continue
            users.append(item)
    return users


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


def parse_json_response(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    return json.loads(raw.strip())


def build_system_prompt(
    *,
    scenario_name: str,
    expected_tool: str,
    style_desc: str,
    tool_desc: str,
    requires_order: bool,
) -> str:
    order_rule = (
        "문장에 주문번호가 반드시 자연스럽게 들어가야 하며, 주문번호 위치에는 {ORDER_ID} placeholder를 사용하세요."
        if requires_order
        else "문장에 특정 주문번호는 넣지 말고, 주문 목록이나 최근 주문 기록을 묻는 형태로 작성하세요."
    )
    return f"""당신은 이커머스 고객지원 챗봇의 평가 데이터셋을 만드는 도우미입니다.
자연스러운 한국어 사용자 질문 1개만 생성하세요.

# 생성 목표
- 시나리오: {scenario_name}
- 정답 tool: {expected_tool}
- 질문 스타일: {style_desc}
- 도구 설명: {tool_desc}

# 제약
1. 질문은 실제 고객이 입력할 법한 한국어여야 합니다.
2. 정답은 반드시 {expected_tool} 이어야 합니다.
3. {order_rule}
4. 출력은 반드시 JSON 객체만 반환하세요.

# 반환 형식
{{
  "query": "생성된 질문",
  "rationale": "왜 이 질문이 해당 tool로 라우팅되어야 하는지 짧은 근거"
}}
""" 


def build_query_prompt(
    *,
    scenario_name: str,
    expected_tool: str,
    requires_order: bool,
    order_id: str,
    product_info: dict[str, Any],
) -> str:
    product_str = json.dumps(product_info, ensure_ascii=False)
    if requires_order:
        order_block = f"""
- 이 샘플은 특정 주문 기반입니다.
- 실제 주문번호 placeholder 대상: {order_id}
- 생성 문장에 주문번호가 들어가야 할 때는 반드시 {{ORDER_ID}} 또는 {{{{ORDER_ID}}}} 를 사용하세요.
"""
    else:
        order_block = """
- 이 샘플은 주문 목록 조회 중심입니다.
- 특정 주문번호 없이도 자연스러운 질문이어야 합니다.
"""

    return f"""다음 정보를 바탕으로 자연스러운 한국어 질문을 만드세요.
- 시나리오: {scenario_name}
- 정답 tool: {expected_tool}
- 참조 상품 정보: {product_str}
{order_block}
[중요]
- 질문은 실제 사용자 발화처럼 자연스러워야 합니다.
- 최종 해석은 반드시 {expected_tool} 이어야 합니다.
"""


def generate_query(
    *,
    scenario: dict[str, Any],
    order_id: str,
    tool_desc: str,
    product_info: dict[str, Any],
) -> tuple[str, str]:
    style_desc = random.choice(STYLE_POOL)
    system_prompt = build_system_prompt(
        scenario_name=scenario["name"],
        expected_tool=scenario["action"],
        style_desc=style_desc,
        tool_desc=tool_desc,
        requires_order=scenario["requires_order"],
    )
    user_prompt = build_query_prompt(
        scenario_name=scenario["name"],
        expected_tool=scenario["action"],
        requires_order=scenario["requires_order"],
        order_id=order_id,
        product_info=product_info,
    )

    raw = (
        client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=300,
        )
        .choices[0]
        .message.content.strip()
    )

    data = parse_json_response(raw)
    query = str(data.get("query", "")).strip()
    rationale = str(data.get("rationale", "")).strip()
    if scenario["requires_order"]:
        query = query.replace("{ORDER_ID}", order_id).replace("{{ORDER_ID}}", order_id)
    return query, rationale


def main() -> None:
    print("=" * 72)
    print("[1단계] 15개 기본 평가 질문 생성 (LLM 기반)")
    print("=" * 72)

    tool_map = load_tools()
    fashion_samples = load_csv_samples(FASHION_CSV, n=100)
    clothes_samples = load_csv_samples(CLOTHES_CSV, n=100)
    all_samples = fashion_samples + clothes_samples
    eval_users = load_eval_users()
    db = SessionLocal()
    records: list[dict[str, Any]] = []
    idx = 1

    try:
        for user_item in eval_users:
            email = user_item["data"]["user_email"]
            user_db = get_user_by_email(db, email)
            actual_uid = int(user_db.id) if user_db else 1

            for act in user_item["action"]:
                scenario_key = act["type"]
                order_id = act["data"].get("order_number", "")
                mapped = SCENARIO_MAP.get(scenario_key)
                if not mapped:
                    continue

                tool_name = mapped["action"]
                tool_desc = tool_map.get(tool_name, {}).get("description", "")
                product_info = pick_product_info(all_samples)
                query, rationale = generate_query(
                    scenario=mapped,
                    order_id=order_id,
                    tool_desc=tool_desc,
                    product_info=product_info,
                )
                records.append(
                    {
                        "scenario": {
                            "name": mapped["name"],
                            "action": mapped["action"],
                            "tools": mapped["tools"],
                            "possible": True,
                        },
                        "order": {"order_id": order_id, "status": ""},
                        "user_id": actual_uid,
                        "user_email": email,
                        "user_query": query,
                        "meta": {"note": f"llm_eval_case_{idx:03d}", "rationale": rationale},
                    }
                )
                print(f"[{idx:02d}] {email} | {mapped['name']} | {order_id}")
                idx += 1

            mapped = SCENARIO_MAP["주문 내역 조회"]
            tool_name = mapped["action"]
            tool_desc = tool_map.get(tool_name, {}).get("description", "")
            product_info = pick_product_info(all_samples)
            query, rationale = generate_query(
                scenario=mapped,
                order_id="",
                tool_desc=tool_desc,
                product_info=product_info,
            )
            records.append(
                {
                    "scenario": {
                        "name": mapped["name"],
                        "action": mapped["action"],
                        "tools": mapped["tools"],
                        "possible": True,
                    },
                    "order": {"order_id": "", "status": ""},
                    "user_id": actual_uid,
                    "user_email": email,
                    "user_query": query,
                    "meta": {"note": f"llm_eval_case_{idx:03d}", "rationale": rationale},
                }
            )
            print(f"[{idx:02d}] {email} | {mapped['name']} | (없음)")
            idx += 1

        with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 완료! 총 {len(records)}개 저장")
        print(f"- JSON 저장: {OUTPUT_JSON_PATH}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
