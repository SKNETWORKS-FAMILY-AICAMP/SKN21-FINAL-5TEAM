"""
validate_questions_phase2.py (Parallelized Version)
[목적]
2차 검수 속도를 높이기 위해 ThreadPoolExecutor를 사용한 병렬 처리를 지원합니다.
상세 규칙에 따라 의미 변질, shipping 포함, 중복성 등을 확인하고 최종 유효 질문을 선별합니다.
"""

import json
import os
import re
import sys
import concurrent.futures
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
INPUT_PATH = DATA_DIR_50 / "3_questions_diversified.jsonl"
OUTPUT_PATH = DATA_DIR_50 / "4_questions_validated_phase2.jsonl"

# 동시 요청 수 설정 (속도 조절)
MAX_WORKERS = 10 

def build_phase2_prompt(
    original_question: str,
    variant_question: str,
    account_role: str,
    intended_tool: str,
    trap_type: str
) -> str:
    return f"""너는 다변화된 이커머스 평가 질문을 2차 검수하는 역할이다.

평가 목적:
- FunctionChat-Bench dialog 모드 (단일턴 + 단일툴)
- 툴 이름 정확도만 평가 (argument 제외)

허용 툴:
- get_user_orders (목록 조회)
- cancel (배송 전 취소)
- refund (배송 후 환불)
- exchange (배송 후 교환)
- change_option (배송 전 옵션 변경)

입력 정보:
- original_question: {original_question}
- variant_question: {variant_question}
- account_role: {account_role}
- intended_tool_family: {intended_tool}
- trap_type: {trap_type}

검수 목표:
1. variant_question이 original_question과 같은 툴로 해석되는가
2. 다변화 과정에서 의미가 바뀌지 않았는가
3. shipping 등 범위 밖 의미가 새로 생기지 않았는가
4. 여전히 단일턴/단일툴 문항인가
5. account_role과 충돌하지 않는가
6. 너무 원문과 비슷하지 않는가

출력 형식:
- JSON 객체 하나만 출력하라. (반드시 아래 필드 유지)
{{
  "keep": true 또는 false,
  "tool_guess": "get_user_orders / cancel / refund / exchange / change_option / ambiguous / out_of_scope",
  "semantic_drift": true 또는 false,
  "too_similar_to_original": true 또는 false,
  "reason": "사유",
  "revised_variant": "수정안 또는 variant_question 그대로"
}}

판정 규칙:
- 원래 {intended_tool}와 동등하게 유지되면 keep=true
- 다른 툴로 읽히거나 애매해지면 keep=false
- 원문과 거의 같은 문장이면 keep=false 또는 revised_variant로 더 다르게 바꿔라
- shipping 의미가 추가되면 keep=false
- 계정 역할과 안 맞는 방향으로 바뀌면 keep=false
"""

def parse_json_response(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    # 가금 JSON 앞에 설명이 붙는 경우 대비
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    raw = raw.strip()
    return json.loads(raw)

def validate_one_variant(orig, var, role, tool, trap, item_context) -> dict[str, Any]:
    prompt = build_phase2_prompt(orig, var, role, tool, trap)
    try:
        raw = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}]
        ).choices[0].message.content.strip()
        
        val_res = parse_json_response(raw)
        
        if val_res.get("keep"):
            return {
                "keep": True,
                "data": {
                    "question": val_res.get("revised_variant", var),
                    "account_role": role,
                    "intended_tool_family": tool,
                    "trap_type": trap,
                    "original_question": orig,
                    "order_id": item_context.get("order_id"),
                    "user_id": item_context.get("user_id"),
                    "user_email": item_context.get("user_email"),
                    "scenario": item_context.get("scenario"),
                    "order": item_context.get("order"),
                    "validation_detail": val_res
                }
            }
        else:
            return {"keep": False, "reason": val_res.get("reason", "Unknown")}
            
    except Exception as e:
        return {"keep": False, "reason": f"API Error: {str(e)}"}

def main():
    print("=" * 72)
    print("[2차 검증(병렬)] questions_diversified.jsonl → questions_validated_phase2.jsonl")
    print(f"- 최대 {MAX_WORKERS}개 동시 호출 진행 중...")
    print("=" * 72)

    if not INPUT_PATH.exists():
        print(f"[Error] 입력 파일이 없습니다: {INPUT_PATH}")
        return

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        master_items = [json.loads(line) for line in f if line.strip()]

    tasks = []
    for item in master_items:
        orig = item["original_question"]
        variants = item["variants"]
        role = item["account_role"]
        tool = item["intended_tool_family"]
        trap = item["trap_type"]
        
        for v in variants:
            tasks.append({
                "orig": orig, "var": v, "role": role, "tool": tool, "trap": trap, "item": item
            })

    print(f"총 검토 대상: {len(tasks)}개")

    final_kept_data = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_task = {
            executor.submit(
                validate_one_variant, 
                t["orig"], t["var"], t["role"], t["tool"], t["trap"], t["item"]
            ): t for t in tasks
        }
        
        completed = 0
        kept = 0
        
        with open(OUTPUT_PATH, "w", encoding="utf-8") as out_f:
            for future in concurrent.futures.as_completed(future_to_task):
                completed += 1
                task = future_to_task[future]
                try:
                    res = future.result()
                    if res.get("keep"):
                        kept += 1
                        out_f.write(json.dumps(res["data"], ensure_ascii=False) + "\n")
                        out_f.flush() # 실시간 저장
                        status = "KEEP"
                    else:
                        status = "SKIP"
                except Exception as e:
                    status = "FAIL"
                
                # 진행 상황 로그 (한 줄 출력)
                print(f"\r progress: [{completed}/{len(tasks)}] (Keep: {kept}) - Current: {status}", end="", flush=True)

    print("\n\n" + "=" * 72)
    print(f"✅ 검증 완료!")
    print(f"   최종 생성 문항: {kept}개 / {len(tasks)}개")
    print(f"   저장 경로: {OUTPUT_PATH}")
    print("=" * 72)

if __name__ == "__main__":
    main()
