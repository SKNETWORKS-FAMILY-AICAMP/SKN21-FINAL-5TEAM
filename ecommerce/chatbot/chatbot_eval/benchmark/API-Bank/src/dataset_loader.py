"""
dataset_loader.py

generate_slot_filling_rate_dialog_dataset.py 로 생성한 JSONL 파일을 로드합니다.

다이얼로그 JSONL 포맷:
{
  "dialog_num": 1,
  "dialog_name": "주문 취소",
  "tools_count": N,
  "tools": [...],
  "turns": [
    {
      "turn_num": 1,
      "serial_num": 1,
      "query": [{"role": "user", "content": "..."}],
      "ground_truth": {"role": "assistant", "content": "..."},
      "type_of_output": "slot" | "call" | "completion",
      "acceptable_arguments": null
    },
    ...
  ]
}
"""

import json
from pathlib import Path
from typing import List, Dict


def load_dialogs(path: str) -> List[Dict]:
    """JSONL 파일에서 다이얼로그 목록을 로드합니다."""
    dialogs = []
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"데이터셋 파일을 찾을 수 없습니다: {path}")

    with open(file_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                dialogs.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  ⚠ {line_no}행 JSON 파싱 오류 (건너뜀): {e}")

    return dialogs


def count_turns_by_type(dialogs: List[Dict]) -> Dict[str, int]:
    """다이얼로그 전체에서 턴 타입별 개수를 반환합니다."""
    counts = {"slot": 0, "call": 0, "completion": 0}
    for dialog in dialogs:
        for turn in dialog.get("turns", []):
            t = turn.get("type_of_output", "")
            if t in counts:
                counts[t] += 1
    return counts


def group_dialogs_by_user(dialogs: List[Dict]) -> Dict[str, List[Dict]]:
    """다이얼로그를 user_email 기준으로 그룹핑합니다.

    generate 스크립트에서 각 dialog에 user_id, user_email을 설정하므로
    이를 기준으로 user row별 다이얼로그 목록을 반환합니다.

    Returns:
        {user_email: [dialog, ...], ...}
    """
    grouped: Dict[str, List[Dict]] = {}
    for dialog in dialogs:
        email = dialog.get("user_email", "unknown")
        if email not in grouped:
            grouped[email] = []
        grouped[email].append(dialog)
    return grouped


def get_user_info(dialogs: List[Dict]) -> List[Dict[str, str]]:
    """다이얼로그에서 고유한 user 정보(user_id, user_email)를 추출합니다."""
    seen = set()
    users = []
    for dialog in dialogs:
        email = dialog.get("user_email")
        if email and email not in seen:
            seen.add(email)
            users.append({
                "user_id": str(dialog.get("user_id", "")),
                "user_email": email,
            })
    return users
