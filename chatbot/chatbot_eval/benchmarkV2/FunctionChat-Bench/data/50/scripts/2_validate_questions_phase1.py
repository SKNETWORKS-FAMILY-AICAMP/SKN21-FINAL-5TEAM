"""
validate_questions_phase1.py
[목적]
questions_raw.jsonl 원본을 읽어 LLM 기반 1차 검증을 수행합니다.
검증 기준:
  - 단일턴/단일툴 문항인가
  - shipping 관련 표현이 없는가
  - intended_tool_family가 올바른가
  - 정답 툴이 애매하지 않은가
  - account_role과 질문이 모순되지 않는가
  - 한국어 구어체 사용자 발화인가
결과를 questions_validated_phase1.jsonl로 저장합니다.
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
# paths.py가 있는 data/ 폴더를 path에 추가
data_root = current_dir.parent.parent
if str(data_root) not in sys.path:
    sys.path.insert(0, str(data_root))

from paths import PROJECT_ROOT
from model_config import DEFAULT_MODEL

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = DEFAULT_MODEL

# 50개 전용 데이터 폴더 (data/50/data/)
DATA_DIR_50 = current_dir.parent / "data"
INPUT_PATH = DATA_DIR_50 / "1_questions_raw.jsonl"
OUTPUT_PATH = DATA_DIR_50 / "2_questions_validated_phase1.jsonl"

ALLOWED_TOOLS = ["get_user_orders", "cancel", "refund", "exchange", "change_option"]
ALLOWED_ROLES = ["pre_delivery", "delivered", "mixed"]
ALLOWED_TRAPS = [
    "no_order_id", "cancel_vs_refund", "exchange_vs_change_option",
    "final_intent_reversal", "reason_based_inference", "mixed_signal_but_single_tool",
]

# shipping 관련 금지 패턴
FORBIDDEN_SHIPPING_PATTERNS = [
    "배송 조회", "배송조회", "택배", "송장", "배송 상태", "배송상태",
    "배송 현황", "배송현황", "배송 추적", "배송추적", "지금 어디쯤",
    "어디쯤", "도착 예정", "도착예정", "출발했", "이동 중",
]


def build_validation_prompt(question: str, account_role: str, intended_tool: str, trap_type: str) -> str:
    return f"""너는 이커머스 에이전트 챗봇의 툴 호출 정확도 평가용 질문 데이터셋을 만드는 역할이다.

목표:
- FunctionChat-Bench dialog 모드용 데이터셋을 만든다.
- 하지만 실제 문항은 단일턴(single-turn), 단일툴(single-tool) 호출 평가용이다.
- 평가 지표는 툴 이름 정확도만 본다.
- argument 정확도는 평가하지 않는다.

평가 대상 툴은 아래 5개뿐이다.
1. get_user_orders — 주문번호 모를 때 주문 목록 조회
2. cancel — 배송 전 주문 취소
3. refund — 배송 후 반품/환불
4. exchange — 배송 후 교환 (회수/재배송)
5. change_option — 배송 전 옵션(사이즈/색상) 변경

중요 제약:
- shipping 관련 질문은 절대 만들지 마라.
- 멀티턴이 필요한 질문은 만들지 마라.
- 한 질문은 최종적으로 하나의 툴로만 해석될 수 있어야 한다.
- 상담형 답변 유도 질문, 정책 설명 질문, 비교 질문은 만들지 마라.

이제 아래 질문을 1차 검증하라.

검증 대상:
- question: {question}
- account_role: {account_role}
- intended_tool_family: {intended_tool}
- trap_type: {trap_type}

검증 항목:
1. 이 질문은 단일턴/단일툴 문항인가?
2. shipping 관련 의미가 포함되어 있는가?
3. intended_tool_family가 질문의 최종 의도에 맞는가?
4. 정답 툴이 애매하지 않은가? (두 개 이상의 툴로 해석 가능하면 안 됨)
5. account_role과 질문 내용이 모순되지 않는가?
6. 한국어 구어체 사용자 발화인가?
7. 상담형/정책설명/비교 질문이 아닌가?

출력 형식:
반드시 JSON 객체 하나만 출력하라.
{{
  "keep": true 또는 false,
  "tool_guess": "get_user_orders / cancel / refund / exchange / change_option / ambiguous / out_of_scope",
  "is_single_turn": true 또는 false,
  "has_shipping_context": true 또는 false,
  "is_ambiguous": true 또는 false,
  "role_conflict": true 또는 false,
  "reason": "한두 문장 설명"
}}

판정 규칙:
- intended_tool_family와 tool_guess가 일치하고 다른 문제가 없으면 keep=true
- tool_guess가 다르거나 ambiguous/out_of_scope이면 keep=false
- shipping 의미가 있으면 keep=false
- 단일턴이 아니면 keep=false
- account_role과 모순이 있으면 keep=false
"""


def parse_json_response(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()
    return json.loads(raw)


def rule_based_precheck(item: dict[str, Any]) -> tuple[bool, str]:
    """LLM 호출 전 빠른 규칙 기반 사전 검증"""
    query = item.get("user_query", "")
    meta = item.get("meta", {})
    scenario = item.get("scenario", {})

    intended_tool = scenario.get("action", "")
    account_role = meta.get("account_role", "")
    trap_type = meta.get("trap_type", "")

    # 1. 필수 필드 존재 여부
    if not query.strip():
        return False, "빈 질문"
    if intended_tool not in ALLOWED_TOOLS:
        return False, f"허용되지 않는 도구: {intended_tool}"
    if account_role not in ALLOWED_ROLES:
        return False, f"허용되지 않는 account_role: {account_role}"
    if trap_type not in ALLOWED_TRAPS:
        return False, f"허용되지 않는 trap_type: {trap_type}"

    # 2. shipping 금지 패턴 검사
    for pattern in FORBIDDEN_SHIPPING_PATTERNS:
        if pattern in query:
            return False, f"shipping 관련 표현 감지: {pattern}"

    # 3. 질문 길이 제한 (너무 긴 질문은 의심)
    if len(query) > 200:
        return False, f"질문이 너무 깁니다: {len(query)}자"

    return True, "사전 검증 통과"


def validate_with_llm(question: str, account_role: str, intended_tool: str, trap_type: str) -> dict[str, Any]:
    """LLM 기반 1차 검증"""
    prompt = build_validation_prompt(question, account_role, intended_tool, trap_type)

    try:
        raw = (
            client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "user", "content": prompt},
                ],
            )
            .choices[0]
            .message.content.strip()
        )
        return parse_json_response(raw)
    except Exception as e:
        print(f"  [ERROR] LLM 검증 실패: {e}")
        return {
            "keep": False,
            "tool_guess": "error",
            "is_single_turn": None,
            "has_shipping_context": None,
            "is_ambiguous": None,
            "role_conflict": None,
            "reason": f"LLM 호출 에러: {str(e)}",
        }


def main() -> None:
    print("=" * 72)
    print("[1차 검증] questions_raw.jsonl → questions_validated_phase1.jsonl")
    print("- LLM 기반 검증: 단일턴/단일툴, shipping 금지, 의도 일치 등")
    print("=" * 72)

    if not INPUT_PATH.exists():
        print(f"[ERROR] 입력 파일이 없습니다: {INPUT_PATH}")
        return

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]

    print(f"원본 질문 수: {len(items)}")

    results = []
    kept_count = 0
    removed_count = 0

    for idx, item in enumerate(items, start=1):
        query = item.get("user_query", "")
        meta = item.get("meta", {})
        scenario = item.get("scenario", {})
        intended_tool = scenario.get("action", "")
        account_role = meta.get("account_role", "mixed")
        trap_type = meta.get("trap_type", "")

        print(f"\n[{idx}/{len(items)}] [{intended_tool}] {query[:50]}...")

        # 1. 규칙 기반 사전 검증
        precheck_ok, precheck_reason = rule_based_precheck(item)
        if not precheck_ok:
            print(f"  [제거] 사전검증 실패: {precheck_reason}")
            removed_count += 1
            item["validation_phase1"] = {
                "keep": False,
                "tool_guess": intended_tool,
                "reason": f"사전검증 실패: {precheck_reason}",
                "method": "rule_based",
            }
            results.append(item)
            continue

        # 2. LLM 기반 검증
        validation = validate_with_llm(query, account_role, intended_tool, trap_type)
        item["validation_phase1"] = {
            "keep": validation.get("keep", False),
            "tool_guess": validation.get("tool_guess", "unknown"),
            "is_single_turn": validation.get("is_single_turn"),
            "has_shipping_context": validation.get("has_shipping_context"),
            "is_ambiguous": validation.get("is_ambiguous"),
            "role_conflict": validation.get("role_conflict"),
            "reason": validation.get("reason", ""),
            "method": "llm",
        }

        if validation.get("keep", False):
            kept_count += 1
            print(f"  [통과] {validation.get('reason', '')}")
        else:
            removed_count += 1
            print(f"  [제거] {validation.get('reason', '')}")

        results.append(item)

    # 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n" + "=" * 72)
    print(f"✅ 1차 검증 완료!")
    print(f"   총 질문: {len(items)}")
    print(f"   통과: {kept_count}")
    print(f"   제거: {removed_count}")
    print(f"   저장 경로: {OUTPUT_PATH}")
    print("=" * 72)

    # 도구별 통과/제거 통계
    tool_stats: dict[str, dict[str, int]] = {}
    for r in results:
        tool = r.get("scenario", {}).get("action", "unknown")
        kept = r.get("validation_phase1", {}).get("keep", False)
        if tool not in tool_stats:
            tool_stats[tool] = {"kept": 0, "removed": 0}
        if kept:
            tool_stats[tool]["kept"] += 1
        else:
            tool_stats[tool]["removed"] += 1

    print("\n[도구별 통계]")
    for tool_name in ALLOWED_TOOLS:
        stats = tool_stats.get(tool_name, {"kept": 0, "removed": 0})
        print(f"  {tool_name}: 통과={stats['kept']}, 제거={stats['removed']}")


if __name__ == "__main__":
    main()
