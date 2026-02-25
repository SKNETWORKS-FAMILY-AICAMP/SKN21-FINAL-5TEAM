
import json
import re
import random
import os
from datetime import datetime

# 경로 설정 (스크립트 위치 기준 상대 경로)
base_dir = os.path.dirname(os.path.abspath(__file__))
input_file = os.path.join(base_dir, "data", "my_eval_dataset_100.jsonl")
output_file = os.path.join(base_dir, "data", "my_eval_dataset_100_updated.jsonl")

# seed.py 기준 서버 주문번호 (2026-02-25 기준)
today_str = "20260219"
server_order_ids = [
    f"ORD-{today_str}-0001",
    f"ORD-{today_str}-0002",
    f"ORD-{today_str}-0003"
]

# 패턴 정의
# 1. 다양한 형식 지원: ORD-2026-0001 또는 ORD-20260117-3766 등
std_pattern = re.compile(r"ORD-[\d-]{4,13}")

def replace_order_ids(line):
    # 한 행(Line) 내에서 일관성을 위해 한 번 선택한 번호를 계속 사용함
    target_id = random.choice(server_order_ids)
    
    def get_fixed_id(match):
        return target_id

    # 1. 표준 패턴 교체
    line = std_pattern.sub(get_fixed_id, line)
    
    # 2. 짧은 패턴(4자리) 교체 (필요시 활성화)
    # line = short_pattern.sub(get_fixed_id, line)
    
    return line

try:
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    updated_lines = [replace_order_ids(line) for line in lines]

    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(updated_lines)

    print(f"✅ 변환 완료! 총 {len(updated_lines)}개의 그룹 데이터를 처리했습니다.")
    print(f"📂 결과 파일: {output_file}")
    print(f"💡 교체된 주문번호 예시: {server_order_ids}")

except Exception as e:
    print(f"❌ 오류 발생: {e}")
