"""
diversify_questions.py
[목적]
1차 검증을 통과한 questions_validated_phase1.jsonl의 각 질문에 대해
LLM을 사용하여 5개의 다변화된 질문을 생성합니다.
결과는 questions_diversified.jsonl에 저장합니다.

다변화 원칙:
- 원문과 같은 툴로 해석되어야 한다.
- shipping 관련 의미를 추가하면 안 된다.
- 질문의 핵심 의도를 바꾸면 안 된다.
- account_role에 맞는 현실성은 유지해야 한다.
- 질문은 한국어 구어체여야 한다.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

# 프로젝트 루트 및 데이터 경로 설정
current_dir = Path(__file__).resolve().parent
# paths.py가 있는 data/ 폴더를 path에 추가 (scripts -> 50 -> data)
# current_dir: scripts/50
# current_dir.parent: scripts/
# current_dir.parent.parent: project_root/
# data_root: project_root/data/
data_root = current_dir.parent.parent / "data"
if str(data_root) not in sys.path:
    sys.path.insert(0, str(data_root))

from paths import PROJECT_ROOT
from model_config import DIVERSIFY_MODEL

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = DIVERSIFY_MODEL

# 50개 전용 데이터 폴더 (data/50/data/)
DATA_DIR_50 = current_dir.parent / "data"
INPUT_PATH = DATA_DIR_50 / "2_questions_validated_phase1.jsonl"
OUTPUT_PATH = DATA_DIR_50 / "3_questions_diversified.jsonl"

# shipping 금지 패턴
FORBIDDEN_SHIPPING_PATTERNS = [
    "배송 조회", "배송조회", "택배", "송장", "배송 상태", "배송상태",
    "배송 현황", "배송현황", "배송 추적", "배송추적", "지금 어디쯤",
    "어디쯤", "도착 예정", "도착예정", "출발했", "이동 중",
]


def build_diversify_prompt(
    original_question: str,
    account_role: str,
    intended_tool: str,
    trap_type: str,
    order_id: str,
) -> str:
    order_instruction = (
        f"- 원문에 주문번호({order_id})가 포함되어 있다면, 다변화된 질문에도 동일한 주문번호를 반드시 포함하라."
        if order_id and order_id in original_question
        else "- 원문에 주문번호가 없으므로, 다변화된 질문에도 주문번호를 넣지 마라."
    )

    return f"""너는 검증을 통과한 이커머스 평가 질문을 다변화하는 역할이다.

평가 목적:
- FunctionChat-Bench dialog 모드
- 실제 문항은 단일턴 + 단일툴
- 툴 이름 정확도만 평가
- argument 정확도는 평가하지 않음

허용 툴:
- get_user_orders
- cancel
- refund
- exchange
- change_option

중요 원칙:
- 원문과 같은 툴로 해석되어야 한다.
- shipping 관련 의미를 추가하면 안 된다. (배송 조회, 택배, 송장, 배송 상태, 배송 현황, 배송 추적 등 금지)
- 멀티턴 전제를 추가하면 안 된다.
- 질문의 핵심 의도를 바꾸면 안 된다.
- account_role에 맞는 현실성은 유지해야 한다.
- 질문은 한국어 구어체여야 한다.
{order_instruction}

다변화 방식 (아래 중 다양하게 조합하라):
- 직설형
- 번복형
- 사유 선행형
- 장문형
- 짧은 구어체형
- 감정 섞인 자연 발화형

하지만 아래는 금지:
- 다른 툴로 해석될 수 있는 단어를 새로 섞는 것
- shipping 유도 표현 추가
- 상담형/설명형으로 바꾸기
- 지나친 문장 장식
- 거의 같은 문장 반복

입력:
- original_question: {original_question}
- account_role: {account_role}
- intended_tool_family: {intended_tool}
- trap_type: {trap_type}

생성 규칙:
- 5개 문장 모두 서로 말투와 표현 순서를 다르게 하라.
- 하지만 모두 같은 intended_tool_family({intended_tool})로 해석 가능해야 한다.
- 5개 중 최소 1개는 번복 표현 또는 최종 의사 강조 표현을 포함하라.
- 5개 중 최소 1개는 사유를 앞에 두는 표현을 사용하라.
- 5개 중 최소 1개는 짧고 구어체적인 표현으로 만들라.
- 원문을 거의 그대로 복사한 문장은 만들지 마라.

출력 형식:
반드시 JSON 객체 하나만 출력하라.
{{
  "variants": ["질문1", "질문2", "질문3", "질문4", "질문5"]
}}
"""


def parse_json_response(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()
    return json.loads(raw)


def has_shipping_pattern(text: str) -> bool:
    """텍스트에 shipping 금지 패턴이 포함되어 있는지 확인"""
    return any(p in text for p in FORBIDDEN_SHIPPING_PATTERNS)


def diversify_question(
    original_question: str,
    account_role: str,
    intended_tool: str,
    trap_type: str,
    order_id: str,
) -> list[str]:
    """LLM을 사용하여 원본 질문의 다변화 5개 생성"""
    prompt = build_diversify_prompt(original_question, account_role, intended_tool, trap_type, order_id)

    try:
        raw = (
            client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            .choices[0]
            .message.content.strip()
        )
        data = parse_json_response(raw)
        variants = data.get("variants", [])

        # shipping 패턴 필터링
        clean_variants = []
        for v in variants:
            if isinstance(v, str) and v.strip():
                if not has_shipping_pattern(v):
                    clean_variants.append(v.strip())
                else:
                    print(f"    [필터] shipping 패턴 감지 제거: {v[:40]}...")

        return clean_variants[:5]
    except Exception as e:
        print(f"  [ERROR] 다변화 실패: {e}")
        return []


def main() -> None:
    print("=" * 72)
    print("[다변화] questions_validated_phase1.jsonl → questions_diversified.jsonl")
    print("- 각 원본 질문에 대해 5개의 다변화된 질문 생성")
    print("- shipping 표현 자동 필터링")
    print("=" * 72)

    if not INPUT_PATH.exists():
        print(f"[ERROR] 입력 파일이 없습니다: {INPUT_PATH}")
        return

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]

    # keep=true인 항목만 대상
    kept_items = [item for item in items if item.get("validation_phase1", {}).get("keep", False)]
    print(f"검증 통과 질문 수: {len(kept_items)}")

    results = []
    total_variants = 0

    for idx, item in enumerate(kept_items, start=1):
        query = item.get("user_query", "")
        meta = item.get("meta", {})
        scenario = item.get("scenario", {})
        order = item.get("order", {})

        intended_tool = scenario.get("action", "")
        account_role = meta.get("account_role", "mixed")
        trap_type = meta.get("trap_type", "")
        order_id = order.get("order_id", "") if order else ""

        print(f"\n[{idx}/{len(kept_items)}] [{intended_tool}] {query[:50]}...")

        variants = diversify_question(query, account_role, intended_tool, trap_type, order_id)

        if not variants:
            print(f"  [WARN] 다변화 결과 없음, 원본만 유지")
            variants = []

        total_variants += len(variants)

        # 결과 레코드: 원본 정보 + 다변화 결과
        result = {
            "original_question": query,
            "account_role": account_role,
            "intended_tool_family": intended_tool,
            "trap_type": trap_type,
            "order_id": order_id,
            "user_id": item.get("user_id"),
            "user_email": item.get("user_email"),
            "scenario": scenario,
            "order": order,
            "variants": variants,
            "meta": meta,
        }
        results.append(result)
        print(f"  생성된 다변화: {len(variants)}개")

    # 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n" + "=" * 72)
    print(f"✅ 다변화 완료!")
    print(f"   원본 질문: {len(kept_items)}")
    print(f"   총 다변화: {total_variants}개")
    print(f"   평균 다변화/질문: {total_variants / max(len(kept_items), 1):.1f}개")
    print(f"   저장 경로: {OUTPUT_PATH}")
    print("=" * 72)

    # 도구별 통계
    tool_stats: dict[str, int] = {}
    for r in results:
        tool = r.get("intended_tool_family", "unknown")
        tool_stats[tool] = tool_stats.get(tool, 0) + len(r.get("variants", []))

    print("\n[도구별 다변화 수]")
    for tool_name in ["get_user_orders", "cancel", "refund", "exchange", "change_option"]:
        print(f"  {tool_name}: {tool_stats.get(tool_name, 0)}개")


if __name__ == "__main__":
    main()
