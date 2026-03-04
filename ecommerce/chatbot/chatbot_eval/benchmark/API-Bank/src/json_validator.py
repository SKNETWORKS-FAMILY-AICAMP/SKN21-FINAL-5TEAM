"""
json_validator.py

JSON Valid Rate 평가를 위한 유효성 검증 모듈입니다.

[검증 항목]
1. json_valid   : arguments 문자열이 json.loads()로 파싱 가능한지 여부
2. type_accurate: ground_truth 대비 각 인자의 타입이 일치하는지 여부
   - int    : 정수형 (float 아닌 순수 int)
   - bool   : boolean (문자열 "true"/"false" 불가)
   - null   : None 값 (JSON null)
   - list   : 배열 (파이썬 list)
   - str    : 문자열

[json_edge_case 별 핵심 검증 포인트]
  quote_escape    : 큰따옴표 포함 문자열 → \" 이스케이프 처리
  array_argument  : list 타입 인자
  empty_object    : {} 빈 arguments
  boolean_false   : False → JSON false
  boolean_true    : True  → JSON true
  null_value      : None  → JSON null
  integer_argument: int 타입 (float 아닌 순수 정수)
  url_string      : URL 포함 문자열 (특수문자 포함)
  long_string     : 100자 이상 장문
  unicode_mixed   : 한글+영문 혼합 Unicode
"""

import json
from typing import Any, Dict, Optional, Tuple


# ── 기본 유효성 검사 ─────────────────────────────────────────────────────────

def is_json_valid(arguments: Any) -> Tuple[bool, Optional[dict]]:
    """
    arguments 가 유효한 JSON 문자열인지 검사합니다.

    Returns:
        (valid: bool, parsed: dict | None)
    """
    if arguments is None:
        return False, None
    if isinstance(arguments, dict):
        return True, arguments
    if not isinstance(arguments, str):
        return False, None
    try:
        parsed = json.loads(arguments)
        return True, parsed
    except (json.JSONDecodeError, ValueError):
        return False, None


# ── 타입 정확도 검사 ─────────────────────────────────────────────────────────

def _type_name(value: Any) -> str:
    """값의 JSON 타입명을 반환합니다."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def check_type_accuracy(
    gt_arguments: Any,
    pred_arguments: Any,
    edge_case: Optional[str] = None,
) -> Dict:
    """
    ground_truth arguments 와 예측 arguments 의 타입 정확도를 검사합니다.

    Args:
        gt_arguments  : ground_truth 의 arguments (str 또는 dict)
        pred_arguments: 예측 모델의 arguments (str 또는 dict)
        edge_case     : json_edge_case 값 (검증 포커스 힌트)

    Returns:
        {
          "type_accurate": bool,          # 모든 키 타입이 일치하면 True
          "key_results"  : {key: {...}},  # 키별 상세 결과
          "fail_reason"  : str | None,    # 실패 이유
        }
    """
    _, gt_parsed = is_json_valid(gt_arguments)
    _, pred_parsed = is_json_valid(pred_arguments)

    if gt_parsed is None:
        return {"type_accurate": True, "key_results": {}, "fail_reason": None}

    if pred_parsed is None:
        return {
            "type_accurate": False,
            "key_results": {},
            "fail_reason": "arguments 가 유효한 JSON이 아닙니다.",
        }

    # 빈 객체 엣지케이스: gt가 {} 이면 pred도 {} (또는 추가 키 없음) 이어야 함
    if edge_case == "empty_object" and gt_parsed == {}:
        if pred_parsed == {}:
            return {"type_accurate": True, "key_results": {}, "fail_reason": None}
        else:
            return {
                "type_accurate": False,
                "key_results": {},
                "fail_reason": f"빈 객체여야 하지만 인자가 존재함: {list(pred_parsed.keys())}",
            }

    key_results: Dict[str, dict] = {}
    all_pass = True

    for key, gt_val in gt_parsed.items():
        pred_val = pred_parsed.get(key)
        gt_type = _type_name(gt_val)
        pred_type = _type_name(pred_val)

        # 타입 일치 여부
        type_match = (gt_type == pred_type)

        # 값이 존재하지 않는 경우
        if key not in pred_parsed:
            key_results[key] = {
                "gt_type": gt_type,
                "pred_type": "missing",
                "pass": False,
                "note": "키 누락",
            }
            all_pass = False
            continue

        # 특수 타입 검증 강화
        note = ""
        if gt_type == "boolean" and not isinstance(pred_val, bool):
            type_match = False
            note = f"boolean 이어야 하지만 {pred_type} 전달"
        elif gt_type == "integer" and isinstance(pred_val, float) and pred_val == int(pred_val):
            # 75000.0 → 75000 처럼 의미상 동일한 경우 허용
            type_match = True
            note = "float → int 변환 허용"
        elif gt_type == "null" and pred_val is not None:
            type_match = False
            note = f"null 이어야 하지만 {pred_type} 전달"
        elif gt_type == "array" and not isinstance(pred_val, list):
            type_match = False
            note = f"array 이어야 하지만 {pred_type} 전달"

        key_results[key] = {
            "gt_type": gt_type,
            "pred_type": pred_type,
            "pass": type_match,
            "note": note,
        }
        if not type_match:
            all_pass = False

    fail_keys = [k for k, v in key_results.items() if not v["pass"]]
    fail_reason = f"타입 불일치 키: {fail_keys}" if fail_keys else None

    return {
        "type_accurate": all_pass,
        "key_results": key_results,
        "fail_reason": fail_reason,
    }


# ── 통합 검증 ────────────────────────────────────────────────────────────────

def validate_call_turn(
    ground_truth: Dict,
    prediction: Dict,
    edge_case: Optional[str] = None,
) -> Dict:
    """
    "call" 타입 턴에 대한 JSON 유효성 + 타입 정확도 통합 검증을 수행합니다.

    Args:
        ground_truth: 데이터셋 ground_truth 딕셔너리
        prediction  : 모델 예측 딕셔너리
        edge_case   : json_edge_case 값

    Returns:
        {
          "json_valid"    : bool,
          "type_accurate" : bool,
          "pass"          : bool,   # json_valid AND type_accurate
          "fail_reason"   : str | None,
          "key_results"   : dict,
          "gt_func_name"  : str,
          "pred_func_name": str,
          "func_name_match": bool,
        }
    """
    gt_tools = ground_truth.get("tool_calls") or []
    pred_tools = prediction.get("tool_calls") or []

    gt_tc = gt_tools[0] if gt_tools else {}
    pred_tc = pred_tools[0] if pred_tools else {}

    gt_func_name = gt_tc.get("name", "")
    pred_func_name = pred_tc.get("name", "")
    func_name_match = (gt_func_name == pred_func_name)

    # 모델이 tool_call 을 하지 않은 경우
    if not pred_tools:
        return {
            "json_valid": False,
            "type_accurate": False,
            "pass": False,
            "fail_reason": "모델이 tool_call 을 생성하지 않았습니다.",
            "key_results": {},
            "gt_func_name": gt_func_name,
            "pred_func_name": "",
            "func_name_match": False,
        }

    pred_args_raw = pred_tc.get("arguments", "{}")
    json_valid, pred_parsed = is_json_valid(pred_args_raw)

    if not json_valid:
        return {
            "json_valid": False,
            "type_accurate": False,
            "pass": False,
            "fail_reason": f"arguments 가 유효하지 않은 JSON: {repr(pred_args_raw)[:80]}",
            "key_results": {},
            "gt_func_name": gt_func_name,
            "pred_func_name": pred_func_name,
            "func_name_match": func_name_match,
        }

    gt_args_raw = gt_tc.get("arguments", "{}")
    type_result = check_type_accuracy(gt_args_raw, pred_args_raw, edge_case)

    overall_pass = json_valid and type_result["type_accurate"]
    fail_reason = None if overall_pass else type_result.get("fail_reason")

    return {
        "json_valid": json_valid,
        "type_accurate": type_result["type_accurate"],
        "pass": overall_pass,
        "fail_reason": fail_reason,
        "key_results": type_result["key_results"],
        "gt_func_name": gt_func_name,
        "pred_func_name": pred_func_name,
        "func_name_match": func_name_match,
    }
