"""
make_answers.py
[목적]
2차 검증을 통과한 questions_validated_phase2.jsonl을 읽어 
최종 Ground Truth(expected_tool)를 결정하고 answers.jsonl에 저장합니다.
상세 규칙에 따라 툴 이름과 사유, 신뢰도, 규칙 추적 정보를 기록합니다.
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
INPUT_PATH = DATA_DIR_50 / "4_questions_validated_phase2.jsonl"
OUTPUT_PATH = DATA_DIR_50 / "5_dataset_labeled.jsonl"

MAX_WORKERS = 10

def build_answer_generation_prompt(question: str, account_role: str) -> str:
    return f"""너는 이커머스 평가 데이터셋의 정답 툴 이름 생성 규칙을 설계하는 역할이다.

목표:
- 질문 하나를 보고 expected_tool 하나만 결정하는 규칙을 만든다.
- FunctionChat-Bench dialog 모드용이지만 실제 문항은 단일턴 + 단일툴이다.
- argument는 평가하지 않는다.
- shipping은 평가 대상이 아니다.

허용 툴:
- get_user_orders (목록 조회)
- cancel (배송 전 취소)
- refund (배송 후 환불)
- exchange (배송 후 교환)
- change_option (배송 전 옵션 변경)

입력값:
- question: {question}
- account_role: {account_role}

툴 결정 기준:
1. 질문에 주문번호가 없고, 주문내역/주문목록/최근 주문/번호를 모른다/어떤 주문인지 먼저 봐야 한다는 의미가 있으면 get_user_orders
2. 취소, 실수 주문, 잘못 눌렀다, 환불 말고 취소, 그냥 취소 등은 cancel
3. 반품, 환불, 파손, 불량, 설명과 다름, 오배송 등은 refund
4. 배송 완료 이후의 일반 교환, 이미 받은 상품 교환, 새 상품으로 교환은 exchange
5. 배송 전 옵션만 변경, 사이즈 변경, 색상 변경, 옵션 잘못 선택은 change_option

account_role 보정:
- pre_delivery -> change_option, cancel 해석이 자연스러움
- delivered -> refund, exchange 해석이 자연스러움
- mixed -> get_user_orders 및 경계형 문항이 자연스러움

출력 형식:
- JSON 객체 하나만 출력하라.
{{
  "expected_tool": "툴이름",
  "confidence": "high / medium / low",
  "reasoning": "결정 사유 (한두 문장)",
  "rule_trace": "적용한 규칙 요약"
}}

중요:
- 반드시 expected_tool 하나만 출력하라. (shipping 제외)
- argument 관여 금지.
"""

def parse_json_response(raw: str) -> dict[str, Any]:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    return json.loads(raw.strip())

def generate_answer_for_one(item: dict) -> dict[str, Any]:
    question = item.get("question", "")
    role = item.get("account_role", "mixed")
    
    prompt = build_answer_generation_prompt(question, role)
    try:
        raw = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}]
        ).choices[0].message.content.strip()
        
        answer_data = parse_json_response(raw)
        
        # 원본 데이터와 정답 데이터를 합침
        final_record = item.copy()
        final_record.update({
            "expected_tool": answer_data.get("expected_tool"),
            "answer_meta": {
                "confidence": answer_data.get("confidence"),
                "reasoning": answer_data.get("reasoning"),
                "rule_trace": answer_data.get("rule_trace")
            }
        })
        return final_record
    except Exception as e:
        print(f"  [Error] {e}")
        return None

def main():
    print("=" * 72)
    print("[정답 생성] questions_validated_phase2.jsonl → answers.jsonl")
    print(f"- {MAX_WORKERS}개 동시 처리 중...")
    print("=" * 72)

    if not INPUT_PATH.exists():
        print(f"[Error] 입력 파일이 없습니다: {INPUT_PATH}")
        return

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]

    total = len(items)
    print(f"총 대상 질문: {total}개")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {executor.submit(generate_answer_for_one, item): item for item in items}
        
        completed = 0
        with open(OUTPUT_PATH, "w", encoding="utf-8") as out_f:
            for future in concurrent.futures.as_completed(future_to_item):
                completed += 1
                res = future.result()
                if res:
                    out_f.write(json.dumps(res, ensure_ascii=False) + "\n")
                    out_f.flush()
                print(f"\r Progress: [{completed}/{total}] 완료", end="", flush=True)

    print("\n\n" + "=" * 72)
    print(f"✅ 정답 생성 완료!")
    print(f"   저장 파일: {OUTPUT_PATH}")
    print("=" * 72)

if __name__ == "__main__":
    main()
