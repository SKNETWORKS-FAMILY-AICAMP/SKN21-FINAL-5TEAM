"""
generate_arg_accuracy_dialog_dataset.py

[목적]
이커머스 액션 기반 챗봇의 Argument Accuracy 평가를 위한
Dialog 모드 데이터셋 20개를 생성합니다.
FunctionChat-Bench 스타일의 JSONL 포맷으로 저장됩니다.

[평가 방식]
- Slot Filling Rate는 평가하지 않습니다.
- Argument Accuracy만 평가합니다 (type_of_output == "call" 인 턴만).
- completion 유형 턴은 평가에 포함하지 않습니다.
- order_id는 test@example.com의 실제 DB 주문 ID를 사용합니다.
"""

import json
import os
import sys
import random
import csv
import re
from pathlib import Path
from dotenv import load_dotenv

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent

def find_project_root(current_path: Path, marker: str = ".env") -> Path:
    for parent in [current_path] + list(current_path.parents):
        if (parent / marker).exists():
            return parent
    return current_path.parents[4]

PROJECT_ROOT = find_project_root(DATA_DIR)
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

RAW_DIR     = PROJECT_ROOT / "ecommerce" / "chatbot" / "data" / "raw"
FASHION_CSV = RAW_DIR / "AI_Hub" / "패션_validation.csv"
CLOTHES_CSV = RAW_DIR / "AI_Hub" / "의류_validation.csv"
TOOLS_PATH  = DATA_DIR / "tools.json"
OUTPUT_PATH = DATA_DIR / "my_eval_arg_accuracy_dialog_20.jsonl"

# ─── OpenAI 설정 ──────────────────────────────────────────────────────────────
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = "gpt-4o-mini"

# ─── DB에서 실제 주문 ID 조회 ─────────────────────────────────────────────────
def get_real_order_ids() -> list:
    """test@example.com 사용자의 실제 주문 ID 목록을 DB에서 가져옵니다."""
    try:
        from sqlalchemy import create_engine, text
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASSWORD")
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "3306")
        db_name = os.getenv("DB_NAME")
        db_url  = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine  = create_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT o.order_number FROM orders o "
                "JOIN users u ON o.user_id=u.id "
                "WHERE u.email='test@example.com' LIMIT 20"
            )).fetchall()
        ids = [str(r[0]) for r in rows]
        if ids:
            print(f"[INFO] 실제 주문 ID 조회 완료: {ids}")
            return ids
    except Exception as e:
        print(f"[WARN] DB 조회 실패: {e}")
    # fallback
    return ["1", "2", "3"]

# ─── Tools 로드 ───────────────────────────────────────────────────────────────
def load_tools() -> list:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        return json.load(f)

# ─── CSV 샘플링 ───────────────────────────────────────────────────────────────
def load_csv_samples(path: Path, n: int = 30) -> list[dict]:
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
    """CSV 행에서 상품 정보 추출 (할루시네이션 방지)"""
    if not samples:
        return {}
    row = random.choice(samples)
    # 다양한 컬럼명 시도
    keys = list(row.keys())
    info = {}
    for k in keys:
        v = str(row.get(k, "")).strip()
        if v and v != "nan":
            info[k] = v
    return info

# ─── GPT-4o-mini 호출 ─────────────────────────────────────────────────────────
def call_gpt(system_prompt: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=3000,
    )
    return response.choices[0].message.content.strip()

# ─── 시나리오 정의 ─────────────────────────────────────────────────────────────
SCENARIOS = [
    {"id": 1,  "name": "주문 취소",                      "tools": ["cancel_order"],                                   "rag_policy": "optional"},
    {"id": 2,  "name": "환불 신청",                      "tools": ["check_refund_eligibility", "register_return_request"], "rag_policy": "required"},
    {"id": 3,  "name": "교환 신청",                      "tools": ["check_exchange_eligibility", "register_exchange_request"], "rag_policy": "optional"},
    {"id": 4,  "name": "주문 내역 조회 (주문번호 없음)", "tools": ["get_user_orders"],                                "rag_policy": "forbidden"},
    {"id": 5,  "name": "주문 내역 조회 (주문번호 있음)", "tools": ["get_order_details"],                              "rag_policy": "forbidden"},
    {"id": 6,  "name": "자연어 키워드 검색",             "tools": ["search_knowledge_base"],                          "rag_policy": "required"},
    {"id": 7,  "name": "필터 기반 추천",                 "tools": ["search_knowledge_base"],                          "rag_policy": "optional"},
    {"id": 8,  "name": "이미지 검색",                    "tools": ["search_knowledge_base"],                          "rag_policy": "optional"},
    {"id": 9,  "name": "중고 판매 신청 + 수거 신청",    "tools": ["open_address_search", "register_return_request"],  "rag_policy": "optional"},
    {"id": 10, "name": "리뷰 초안 작성 + 리뷰 등록",    "tools": ["create_review"],                                  "rag_policy": "forbidden"},
    {"id": 11, "name": "상품권 등록",                    "tools": ["register_gift_card"],                             "rag_policy": "forbidden"},
]

# 20개 배분: 각 시나리오에서 1~2개씩 총 20개 (11개 시나리오 중 9개는 2개, 2개는 1개)
SCENARIO_DISTRIBUTION = [1,2,3,4,5,6,7,8,9,10,11,1,2,3,4,5,6,7,8,9]
# 총 20개, 순서 섞기 전에 고정

# ─── acceptable_arguments 정의 ────────────────────────────────────────────────
ACCEPTABLE = {
    "reason": [
        "단순 변심", "simple_change_of_mind", "change_of_mind",
        "customer_preference", "사이즈 문제", "색상 불만족",
        "배송 지연", "상품 불량", "오배송", "파손"
    ],
    "size": ["XS", "S", "M", "L", "XL", "90", "95", "100", "105", "FREE"],
    "color": ["black", "white", "ivory", "cream", "beige", "navy", "gray", "brown",
              "블랙", "화이트", "아이보리", "크림", "베이지", "네이비", "그레이", "브라운"],
    "rating": [1, 2, 3, 4, 5],
    "payment_method": ["카드", "계좌이체", "CARD", "BANK_TRANSFER", "카카오페이", "네이버페이"],
}

# ─── 시나리오별 Dialog 생성 ───────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 이커머스 챗봇 평가용 데이터셋 전문가입니다.
주어진 시나리오에 따라 멀티턴 대화와 Ground Truth tool call을 생성합니다.

규칙:
1. output은 반드시 순수 JSON 객체만 반환합니다. 마크다운 코드블록, 설명 텍스트 없이.
2. 모든 tool call에는 user_id: 1을 반드시 포함합니다.
3. order_id는 반드시 {ORDER_ID} placeholder를 사용해야 합니다. [매우 중요] tool_calls의 arguments 뿐만 아니라, "query" 배열 내 user 또는 assistant의 대화 텍스트(content) 안에도 반드시 {ORDER_ID}가 1회 이상 명시적으로 등장해야 합니다.
4. dialog는 멀티턴으로, 필수 argument(주문번호, 취소사유, 교환사유 등)가 dialog 안에 이미 구체적인 텍스트로 포함되어야 합니다.
5. Slot Filling 질문은 생성하지 않습니다. (type_of_output: "slot" 턴은 만들지 않음)
6. type_of_output: "call" 인 턴이 반드시 2개 이상 포함되어야 합니다.
7. 상품 정보는 반드시 제공된 CSV 데이터를 기반으로 생성합니다. 임의 상품명 생성 금지.
"""


def build_prompt_for_scenario(scenario: dict, product_info: dict, dialog_num: int) -> str:
    tool_names_str = ", ".join(scenario["tools"])
    product_str = json.dumps(product_info, ensure_ascii=False)

    return f"""
시나리오: {scenario['name']} (시나리오 ID: {scenario['id']})
다이얼로그 번호: {dialog_num}
평가 대상 tools: {tool_names_str}
RAG 정책: {scenario['rag_policy']}

참고 상품 정보 (CSV 기반, 이 정보만 사용할 것):
{product_str}

다음 형식으로 JSON을 반환하세요:

{{
  "scenario_id": "{scenario['id']}-{dialog_num}",
  "scenario_name": "{scenario['name']}",
  "order_id_source": "get_user_orders:test@example.com",
  "rag_policy": "{scenario['rag_policy']}",
  "source_file": "AI_Hub CSV",
  "source_row_id": "<CSV에서 참조한 행 정보>",
  "evidence": "<사용한 근거>",
  "turns": [
    {{
      "turn_num": 1,
      "query": [
        {{"role": "user", "content": "..."}}
      ],
      "ground_truth": {{
        "role": "assistant",
        "content": "...",
        "tool_calls": null
      }},
      "type_of_output": "completion"
    }},
    {{
      "turn_num": 2,
      "query": [
        {{"role": "user", "content": "..."}},
        {{"role": "assistant", "content": "..."}},
        {{"role": "user", "content": "..."}}
      ],
      "ground_truth": {{
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {{
            "id": "random_id",
            "type": "function",
            "function": {{
              "name": "<tool_name>",
              "arguments": "<JSON string with all required params + user_id: 1>"
            }}
          }}
        ]
      }},
      "type_of_output": "call",
      "acceptable_arguments": {{
        "reason": ["단순 변심", "simple_change_of_mind", "customer_preference"]
      }}
    }}
  ]
}}

중요:
- type_of_output이 "call"인 턴이 반드시 2개 이상 포함되어야 합니다.
- completion 유형 턴은 포함해도 되지만, 포함하지 않아도 됩니다. (Argument Accuracy 전용)
- query 배열은 해당 turn까지의 전체 대화 기록을 포함해야 합니다 (누적 방식).
- arguments는 JSON 문자열로 직렬화하세요.
- acceptable_arguments는 type_of_output=="call"인 모든 턴에 반드시 포함해야 합니다. (reason, size, color, rating, payment_method)
- 해당되는 파라미터가 없다면 빈 딕셔너리 {{}} 귿로 설정하세요. 절대 누락하지 마세요.
- tool call이 없는 턴은 tool_calls를 null로 설정하고 content에 텍스트를 넣으세요.
- turn_num은 1부터 시작하여 순차적으로 증가합니다.
"""


def replace_order_id_in_turns(turns: list, real_order_ids: list) -> list:
    """{ORDER_ID} placeholder를 DB의 실제 주문 ID로 치환합니다."""
    if not real_order_ids:
        return turns
    chosen_id = random.choice(real_order_ids)
    for t in turns:
        # ground_truth 내 arguments 치환
        gt = t.get("ground_truth", {})
        if gt and isinstance(gt, dict):
            tool_calls = gt.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "")
                    if isinstance(args, str):
                        fn["arguments"] = args.replace("{ORDER_ID}", chosen_id)
                    elif isinstance(args, dict):
                        args_str = json.dumps(args, ensure_ascii=False)
                        fn["arguments"] = args_str.replace("{ORDER_ID}", chosen_id)
        # query 내 메시지에서도 치환
        has_id_in_query = False
        for msg in t.get("query", []):
            if isinstance(msg.get("content"), str):
                if "{ORDER_ID}" in msg["content"]:
                    has_id_in_query = True
                msg["content"] = msg["content"].replace("{ORDER_ID}", chosen_id)
        
        # [검증] call 타입인데 대화 내용에 대상 ID가 언급되지 않았다면 Warning
        if t.get("type_of_output") == "call" and not has_id_in_query:
            # 강제로 마지막 user 대화에 주문번호를 주입 (Fail-safe)
            if t.get("query"):
                t["query"][-1]["content"] += f" 주문번호는 {chosen_id} 입니다."
    return turns


def ensure_acceptable_arguments_on_call_turns(turns: list) -> list:
    """call 유형 턴에 acceptable_arguments가 없는 경우 빈 딕셔너리로 기본값을 넣어줄니다."""
    for t in turns:
        if t.get("type_of_output") == "call" and "acceptable_arguments" not in t:
            # ground_truth의 arguments를 분석해서 적절한 기본값을 샘플링
            acc = {}
            gt = t.get("ground_truth", {})
            tc_list = gt.get("tool_calls", []) if isinstance(gt, dict) else []
            if tc_list:
                fn = tc_list[0].get("function", {})
                args_raw = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except:
                    args = {}
                # reason 파라미터가 있으면 기본 허용 목록 제공
                if "reason" in args:
                    acc["reason"] = ACCEPTABLE["reason"]
                if "size" in args:
                    acc["size"] = ACCEPTABLE["size"]
                if "color" in args:
                    acc["color"] = ACCEPTABLE["color"]
                if "rating" in args:
                    acc["rating"] = ACCEPTABLE["rating"]
                if "payment_method" in args:
                    acc["payment_method"] = ACCEPTABLE["payment_method"]
            t["acceptable_arguments"] = acc
    return turns


def filter_call_turns_only(turns: list) -> list:
    """type_of_output이 'call'인 턴만 필터링합니다."""
    return [t for t in turns if t.get("type_of_output") == "call"]


def generate_dialog(scenario: dict, product_info: dict, dialog_num: int, tools: list,
                    real_order_ids: list) -> dict | None:
    prompt = build_prompt_for_scenario(scenario, product_info, dialog_num)
    try:
        raw = call_gpt(SYSTEM_PROMPT, prompt)
        # JSON 파싱 시도
        # 코드블록 제거
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        data = json.loads(raw.strip())

        # 후첸리 1: {ORDER_ID} 실제 ID로 치환
        data["turns"] = replace_order_id_in_turns(data.get("turns", []), real_order_ids)

        # 후첸리 2: acceptable_arguments 누락 보완
        data["turns"] = ensure_acceptable_arguments_on_call_turns(data.get("turns", []))

        # 후첸리 3: call 턴만 필터링 (Argument Accuracy 전용)
        data["turns"] = filter_call_turns_only(data.get("turns", []))

        if not data["turns"]:
            print(f"[WARN] dialog {dialog_num}: call 턴이 없습니다.")
            return None

        # tools 필드 추가
        data["dialog_num"] = dialog_num
        data["tools_count"] = len(tools)
        data["tools"] = tools

        return data
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 파싱 실패 (dialog {dialog_num}, scenario {scenario['name']}): {e}")
        print(f"  Raw response (first 300 chars): {raw[:300]}")
        return None
    except Exception as e:
        print(f"[ERROR] 생성 실패 (dialog {dialog_num}): {e}")
        return None


# ─── 메인 실행 ────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Argument Accuracy Dialog 데이터셋 생성 시작")
    print("=" * 60)

    # 1. tools 로드
    tools = load_tools()
    print(f"[INFO] tools.json 로드 완료: {len(tools)}개 tool")

    # 2. CSV 샘플 로드
    fashion_samples = load_csv_samples(FASHION_CSV, n=100)
    clothes_samples = load_csv_samples(CLOTHES_CSV, n=100)
    all_samples = fashion_samples + clothes_samples
    print(f"[INFO] CSV 샘플 로드 완료: {len(all_samples)}개 행")

    # 3. 실제 DB 주문 ID 조회
    real_order_ids = get_real_order_ids()
    print(f"[INFO] 실제 주문 ID: {real_order_ids}")

    # 4. 시나리오 ID → 시나리오 매핑
    scenario_map = {s["id"]: s for s in SCENARIOS}

    # 5. 20개 생성
    results = []
    serial_counter = 1

    for i, scenario_id in enumerate(SCENARIO_DISTRIBUTION):
        dialog_num = i + 1
        scenario = scenario_map[scenario_id]
        product_info = pick_product_info(all_samples) if all_samples else {}

        print(f"\n[{dialog_num:02d}/20] 시나리오 '{scenario['name']}' 생성 중...")

        dialog_data = generate_dialog(scenario, product_info, dialog_num, tools, real_order_ids)

        if dialog_data is None:
            print(f"  → 재시도 중...")
            dialog_data = generate_dialog(scenario, product_info, dialog_num, tools, real_order_ids)

        if dialog_data is None:
            print(f"  → 생성 실패, 건너맕니다.")
            continue

        # serial_num 보정
        turns = dialog_data.get("turns", [])
        for t in turns:
            t["serial_num"] = serial_counter
            serial_counter += 1

        results.append(dialog_data)
        print(f"  → 완료 ({len(turns)} turns, call 타입: {sum(1 for t in turns if t.get('type_of_output') == 'call')}개)")

    # 5. JSONL 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("\n" + "=" * 60)
    print(f"✅ 데이터셋 생성 완료!")
    print(f"   총 Dialog 수 : {len(results)}개 / 목표 20개")
    total_calls = sum(
        sum(1 for t in item.get("turns", []) if t.get("type_of_output") == "call")
        for item in results
    )
    print(f"   총 call 턴 수: {total_calls}개")
    print(f"   저장 경로    : {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
