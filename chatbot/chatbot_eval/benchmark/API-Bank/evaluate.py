#!/usr/bin/env python3
"""
API-Bank Benchmark — evaluate.py

이커머스 챗봇의 JSON Valid Rate를 평가합니다.

사용 예시:
  python evaluate.py \\
    --model gpt-4o-mini \\
    --input_path data/my_eval_json_valid_rate_dialogs.jsonl \\
    --api_key sk-...
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evaluate_json_valid_rate import evaluate_json_valid_rate

if __name__ == "__main__":
    evaluate_json_valid_rate()
