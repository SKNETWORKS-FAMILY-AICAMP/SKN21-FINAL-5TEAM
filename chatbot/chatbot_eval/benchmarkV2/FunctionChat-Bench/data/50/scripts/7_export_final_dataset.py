"""
export_final_dataset.py
[목적]
선정된 50개 문항(dataset_selected_50.jsonl)을 FunctionChat-Bench 평가 규격으로 변환합니다.
계정 역할(account_role)을 실제 DB 기반 user_id/email로 매핑하고 최종 포맷을 구성합니다.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# 프로젝트 루트 및 데이터 경로 설정
current_dir = Path(__file__).resolve().parent
# paths.py가 있는 data/ 폴더를 path에 추가
data_root = current_dir.parent.parent
if str(data_root) not in sys.path:
    sys.path.insert(0, str(data_root))

from paths import find_project_root
# 동적으로 프로젝트 전체 루트 탐색
PROJECT_ROOT = find_project_root(data_root)
sys.path.insert(0, str(PROJECT_ROOT))

from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.router.users.crud import get_user_by_email
import ecommerce.backend.app.models  # 모든 모델을 레지스트리에 등록하여 Mapper 초기화 오류 방지

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# 50개 전용 데이터 폴더 (data/50/data/)
DATA_DIR_50 = current_dir.parent / "data"
INPUT_PATH = DATA_DIR_50 / "6_dataset_selected_50.jsonl"
OUTPUT_PATH = DATA_DIR_50 / "7_my_eval_arg_accuracy_dialogs50.jsonl"

# 도구명 한글 시나리오 매핑
SCENARIO_MAP = {
    "get_user_orders": "주문내역 조회",
    "cancel": "주문 취소",
    "refund": "반품/환불",
    "exchange": "교환",
    "change_option": "옵션 변경"
}

# 계정 역할별 이메일 매핑 (dataset_v7 기준)
ROLE_EMAIL_MAP = {
    "pre_delivery": "test@example.com",
    "delivered": "test@example.com", # 실제 데이터에 맞게 조정 필요시 수정
    "mixed": "test@example.com"
}
# 실제 데이터셋 생성 시 사용된 이메일들이 다를 수 있으므로, 
# 만약 입력 데이터에 이미 user_email이 있다면 그것을 우선 사용합니다.

# 공통 도구 리스트 (Function Schema)
COMMON_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_user_orders",
            "description": "사용자의 주문 목록 및 상세 내역을 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "조회할 주문 개수"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel",
            "description": "배송 전 상태의 주문을 취소합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "취소할 주문 번호"},
                    "reason": {"type": "string", "description": "취소 사유"}
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "refund",
            "description": "배송 완료된 상품의 반품 및 환불을 요청합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "환불할 주문 번호"},
                    "reason": {"type": "string", "description": "환불 사유"}
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "exchange",
            "description": "배송 완료된 상품의 교환을 요청합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "교환할 주문 번호"},
                    "reason": {"type": "string", "description": "교환 사유"}
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "change_option",
            "description": "배송 전 상태인 주문의 상품 옵션(사이즈, 색상 등)을 변경합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "변경할 주문 번호"},
                    "new_option": {"type": "string", "description": "새로운 옵션 정보"}
                },
                "required": ["order_id"]
            }
        }
    }
]

def get_actual_user_info(email: str):
    db = SessionLocal()
    try:
        user = get_user_by_email(db, email)
        if user:
            return str(user.id), user.email
        return None, None
    finally:
        db.close()

def transform_to_bench_format(item: dict, idx: int) -> dict:
    tool = item.get("expected_tool")
    email = item.get("user_email") or ROLE_EMAIL_MAP.get(item.get("account_role"), "test@example.com")
    
    uid, uemail = get_actual_user_info(email)
    
    # task_id 생성
    task_id = f"eval_dialog_{idx+1:04d}"
    
    return {
        "task_id": task_id,
        "serial_num": idx + 1,
        "scenario_name": SCENARIO_MAP.get(tool, "기타"),
        "expected_tool": tool,
        "user_id": uid or "1", # 폴백
        "user_email": uemail or email,
        "tools": COMMON_TOOLS,
        "messages": [
            {
                "role": "system",
                "content": f"사용자 이메일은 {uemail or email} 이고 user_id는 {uid or '1'} 입니다."
            },
            {
                "role": "user",
                "content": item.get("question")
            }
        ],
        "ground_truth": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{task_id}",
                    "type": "function",
                    "function": {
                        "name": tool,
                        "arguments": "{}" # 아규먼트는 무시하므로 빈 객체 문자열
                    }
                }
            ]
        },
        "acceptable_arguments": json.dumps([{}], ensure_ascii=False),
        "type_of_output": "call",
        "prediction": {
            "tool_calls": None
        }
    }

def main():
    print("=" * 72)
    print("[최종 내보내기] dataset_selected_50.jsonl → my_eval_arg_accuracy_dialogs3.jsonl")
    print("=" * 72)

    if not INPUT_PATH.exists():
        print(f"[Error] 입력 파일이 없습니다: {INPUT_PATH}")
        return

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]

    print(f"변환 대상 문항: {len(items)}개")

    final_jsonl = []
    for i, item in enumerate(items):
        try:
            transformed = transform_to_bench_format(item, i)
            final_jsonl.append(transformed)
            print(f"  [{i+1}/{len(items)}] {transformed['expected_tool']} 변환 완료")
        except Exception as e:
            import traceback
            print(f"\n  [Error] {i+1}번 문항 변환 실패: {e}")
            traceback.print_exc()

    # 저장
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out_f:
        for entry in final_jsonl:
            out_f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print("\n\n" + "=" * 72)
    print(f"✅ 변환 완료!")
    print(f"   최종 파일: {OUTPUT_PATH}")
    print("=" * 72)

if __name__ == "__main__":
    main()
