"""
select_final_50.py
[목적]
dataset_labeled.jsonl에서 품질이 높은 50개의 문항을 전략적으로 선정합니다.
툴별 할당량(14, 10, 10, 8, 8)을 준수하며, 난이도와 다양성을 고려합니다.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

# 프로젝트 루트 및 데이터 폴더 설정
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
INPUT_PATH = DATA_DIR_50 / "5_dataset_labeled.jsonl"
OUTPUT_PATH = DATA_DIR_50 / "6_dataset_selected_50.jsonl"

TARGET_QUOTAS = {
    "get_user_orders": 14,
    "cancel": 10,
    "refund": 10,
    "exchange": 8,
    "change_option": 8
}

def build_selection_prompt(items: list[dict], tool_name: str, quota: int) -> str:
    # LLM에게 전달할 문항 정보 요약
    summarized_items = []
    for idx, item in enumerate(items):
        summarized_items.append({
            "idx": idx,
            "question": item.get("question"),
            "role": item.get("account_role"),
            "trap": item.get("trap_type"),
            "difficulty": item.get("meta", {}).get("difficulty_quality", "normal"),
            "is_drift": item.get("validation_detail", {}).get("semantic_drift", False)
        })

    return f"""너는 이커머스 평가 데이터셋에서 최종 {quota}개의 문항을 선정하는 전문가다.

현재 대상 툴: {tool_name} (목표 개수: {quota}개)

선정 기준:
1. 품질이 높은 'good_hard' 난이도를 최우선으로 한다.
2. 표현이 지나치게 비슷한 문항은 중복으로 간주하고 하나만 남긴다.
3. trap_type과 account_role이 다양하게 분산되도록 한다.
4. semantic_drift=true인 문항은 최후순위로 둔다.
5. 정확히 {quota}개의 인덱스(idx)만 골라라.

후보 문항 리스트:
{json.dumps(summarized_items, ensure_ascii=False, indent=2)}

출력 형식:
반드시 선정된 {quota}개의 'idx' 값들만 JSON 배열로 출력하라.
{{
  "selected_indices": [0, 1, 2, ...]
}}
"""

def parse_json_response(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    return json.loads(raw.strip())

def select_best_items(items_of_tool: list[dict], tool_name: str, quota: int) -> list[dict]:
    """해당 툴 그룹에서 LLM을 사용해 최적의 N개 선정"""
    if len(items_of_tool) <= quota:
        return items_of_tool

    prompt = build_selection_prompt(items_of_tool, tool_name, quota)
    try:
        raw = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        ).choices[0].message.content.strip()
        
        selection = parse_json_response(raw)
        indices = selection.get("selected_indices", [])
        
        # 안전장치: 개수가 안 맞으면 앞에서부터 채움
        final_selected = []
        for idx in indices:
            if 0 <= idx < len(items_of_tool):
                final_selected.append(items_of_tool[idx])
        
        if len(final_selected) < quota:
            remaining = [it for it in items_of_tool if it not in final_selected]
            final_selected.extend(remaining[:(quota - len(final_selected))])
            
        return final_selected[:quota]
    except Exception as e:
        print(f"  [Error] Selection failed for {tool_name}: {e}")
        return items_of_tool[:quota]

def main():
    print("=" * 72)
    print("[최종 50선 추출] dataset_labeled.jsonl → dataset_selected_50.jsonl")
    print("=" * 72)

    if not INPUT_PATH.exists():
        print(f"[Error] 입력 파일이 없습니다: {INPUT_PATH}")
        return

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        all_items = [json.loads(line) for line in f if line.strip()]

    # 1. 툴별 그룹화
    groups: dict[str, list[dict]] = {k: [] for k in TARGET_QUOTAS.keys()}
    for item in all_items:
        tool = item.get("expected_tool")
        if tool in groups:
            groups[tool].append(item)

    final_50 = []
    
    # 2. 툴별로 LLM 기반 선별
    for tool_name, quota in TARGET_QUOTAS.items():
        print(f"\n[{tool_name}] 선별 중... (후보: {len(groups[tool_name])}개 -> 목표: {quota}개)")
        selected = select_best_items(groups[tool_name], tool_name, quota)
        print(f"  -> {len(selected)}개 선정 완료")
        
        # 3. 데이터 정제 (필요한 필드만 남김)
        for s in selected:
            cleaned = {
                "question": s.get("question"),
                "account_role": s.get("account_role"),
                "expected_tool": s.get("expected_tool"),
                "confidence": s.get("answer_meta", {}).get("confidence", "high"),
                "reasoning": s.get("answer_meta", {}).get("reasoning", ""),
                "rule_trace": s.get("answer_meta", {}).get("rule_trace", "")
            }
            final_50.append(cleaned)

    # 4. 수량 강제 확인
    if len(final_50) != 50:
        print(f"\n[Warning] 최종 개수가 50개가 아님 ({len(final_50)}개). 조정 필요.")
        final_50 = final_50[:50]

    # 5. 저장
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out_f:
        for item in final_50:
            out_f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("\n" + "=" * 72)
    print(f"✅ 최종 선정 완료! (총 {len(final_50)}개)")
    print(f"   저장 경로: {OUTPUT_PATH}")
    print("=" * 72)

    # 확인용 통계
    stats = {}
    for f in final_50:
        t = f["expected_tool"]
        stats[t] = stats.get(t, 0) + 1
    
    for tool, count in stats.items():
        print(f"  {tool}: {count}개")

if __name__ == "__main__":
    main()
