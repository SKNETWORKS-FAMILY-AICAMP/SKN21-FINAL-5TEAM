#!/usr/bin/env python3
"""
evaluate_json_valid_rate.py  (API-Bank Benchmark)

이커머스 챗봇의 JSON Valid Rate를 평가합니다.
generate_json_valid_rate_dialog_dataset.py 로 생성한 JSONL 데이터셋을 사용합니다.

[평가 지표]
  - JSON Valid Rate (JVR)   : tool_calls.arguments 가 json.loads() 로 파싱 가능한 비율
  - Schema Match Rate (SMR) : JSON 유효 + 함수명이 ground_truth 와 일치하는 비율 (pass 기준)
  - Response Completion Rate: completion 턴의 결과 전달 품질 (LLM Judge)
  - Task Completion Rate    : 다이얼로그 전체 완료율 (모든 턴 pass)

[사용 예시]
  python evaluate_json_valid_rate.py \\
    --model gpt-4o-mini \\
    --input_path ../FunctionChat-Bench/data/my_eval_json_valid_rate_dialogs.jsonl \\
    --api_key sk-...

[generate_slot_filling_rate_dialog_dataset.py 와의 차이]
  Slot Filling: 누락 슬롯 역질문 → tool_call 성공 여부 (LLM Judge)
  JSON Valid  : tool_call.arguments 의 JSON 형식·타입 정확성 (코드 검증)
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import click
from tqdm import tqdm
from dotenv import load_dotenv
from openai import OpenAI

from src.paths import BENCH_ROOT, DATA_DIR, OUTPUT_DIR, CONFIG_PATH, ENV_PATH
from src.dataset_loader import load_dialogs
from src.model_caller import ModelCaller
from src.json_validator import validate_call_turn, is_json_valid

# eval_data.jsonl 경로 (벤치마크 공통 평가 데이터)
EVAL_DATA_PATH = BENCH_ROOT.parent / "eval_data.jsonl"

load_dotenv(ENV_PATH)


def load_login_user_email() -> Optional[str]:
    """eval_data.jsonl에서 '로그인' 타입의 user_email을 읽어 반환합니다."""
    if not EVAL_DATA_PATH.exists():
        logging.warning(f"eval_data.jsonl 파일을 찾을 수 없습니다: {EVAL_DATA_PATH}")
        return None
    with open(EVAL_DATA_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("type") == "로그인":
                    return entry.get("data", {}).get("user_email")
            except json.JSONDecodeError:
                continue
    return None


# ── LLM Judge (completion 턴 전용) ──────────────────────────────────────────

def _load_rubric(name: str) -> Optional[str]:
    path = DATA_DIR / f"rubric_{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def llm_judge_completion(
    judge_client: OpenAI,
    judge_model: str,
    tools: List[Dict],
    query: List[Dict],
    ground_truth: Dict,
    prediction: Dict,
) -> bool:
    """completion 턴을 LLM Judge로 평가합니다."""
    rubric = _load_rubric("completion")
    if not rubric:
        return False
    prompt = rubric.format(
        tools=json.dumps(tools, ensure_ascii=False),
        query=json.dumps(query, ensure_ascii=False),
        ground_truth=json.dumps(ground_truth, ensure_ascii=False),
        response=json.dumps(prediction, ensure_ascii=False),
    )
    try:
        resp = judge_client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        last_line = resp.choices[0].message.content.strip().splitlines()[-1].lower().strip().rstrip(".")
        return last_line == "pass"
    except Exception as e:
        logging.error(f"LLM Judge 호출 실패: {e}")
        return False


# ── 단일 턴 평가 ─────────────────────────────────────────────────────────────

def evaluate_turn(
    turn: Dict,
    tools: List[Dict],
    caller: ModelCaller,
    judge_client: OpenAI,
    judge_model: str,
    only_exact: bool,
    debug: bool,
    prompt_variables: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    단일 턴을 평가합니다.

    "call"       → JSON 유효성 + 타입 정확도 (코드 검증, LLM Judge 불필요)
    "completion" → LLM Judge
    """
    query = turn["query"]
    ground_truth = turn["ground_truth"]
    turn_type = turn["type_of_output"]

    # 모델 호출 (dialog별 prompt_variables로 시스템 프롬프트 치환)
    try:
        prediction = caller.call(query, tools, prompt_variables=prompt_variables)
    except Exception as e:
        logging.error(f"모델 호출 실패 (turn {turn['turn_num']}): {e}")
        prediction = {"role": "assistant", "content": None}

    result = {
        "serial_num": turn["serial_num"],
        "turn_num": turn["turn_num"],
        "type_of_output": turn_type,
        "query": query,
        "ground_truth": ground_truth,
        "prediction": prediction,
        # "call" 턴 전용 필드
        "json_valid": None,
        "type_accurate": None,
        "func_name_match": None,
        "key_results": None,
        "fail_reason": None,
        # 통합 pass 여부
        "pass": False,
    }

    if turn_type == "call":
        validation = validate_call_turn(ground_truth, prediction)
        result.update({
            "json_valid": validation["json_valid"],
            "type_accurate": validation["type_accurate"],
            "func_name_match": validation["func_name_match"],
            "key_results": validation["key_results"],
            "fail_reason": validation["fail_reason"],
            "pass": validation["pass"],
        })
        if debug:
            j = "✅" if validation["json_valid"] else "❌"
            t = "✅" if validation["type_accurate"] else "❌"
            print(
                f"    Turn {turn['turn_num']} [call] "
                f"JSON:{j}  Type:{t}  "
                + (f"fail={validation['fail_reason']}" if validation["fail_reason"] else "")
            )

    elif turn_type == "completion":
        if only_exact:
            # only_exact 모드: completion 턴은 항상 pass (JSON 검증 목적에 집중)
            result["pass"] = True
        else:
            comp_pass = llm_judge_completion(
                judge_client, judge_model, tools, query, ground_truth, prediction
            )
            result["pass"] = comp_pass
        if debug:
            status = "✅" if result["pass"] else "❌"
            print(f"    Turn {turn['turn_num']} [completion] {status}")

    else:
        # slot 턴이 있을 경우: JSON Valid Rate 맥락에서는 pass 처리
        result["pass"] = True
        if debug:
            print(f"    Turn {turn['turn_num']} [{turn_type}] → pass (JSON 평가 비대상)")

    return result


# ── 전체 다이얼로그 평가 ──────────────────────────────────────────────────────

def evaluate_dialogs(
    dialogs: List[Dict],
    caller: ModelCaller,
    judge_client: OpenAI,
    judge_model: str,
    target_model: str,
    output_dir: str,
    only_exact: bool,
    reset: bool,
    debug: bool,
) -> List[Dict]:
    """모든 다이얼로그를 평가하고 결과를 저장합니다."""
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"json_valid_{target_model}.eval.jsonl")

    if not reset and os.path.exists(output_path):
        cached: List[Dict] = []
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    cached.append(json.loads(line))
        if len(cached) == len(dialogs):
            print(f"[[캐시된 결과 로드]] {len(cached)}개 다이얼로그 (reset=False)")
            return cached
        print(f"[[캐시 불완전 ({len(cached)}/{len(dialogs)}), 재평가 시작]]")

    all_results: List[Dict] = []
    with open(output_path, "w", encoding="utf-8") as fw:
        for dialog in tqdm(dialogs, desc="다이얼로그 평가"):
            if debug:
                print(f"\n▶ Dialog {dialog['dialog_num']}: {dialog.get('dialog_name', '')}")

            tools = dialog["tools"]
            # dialog별 user_id/user_email을 시스템 프롬프트에 주입
            dialog_vars = {}
            if "user_id" in dialog:
                dialog_vars["user_id"] = str(dialog["user_id"])
            if "user_email" in dialog:
                dialog_vars["user_email"] = dialog["user_email"]

            turn_results = [
                evaluate_turn(
                    turn, tools, caller,
                    judge_client, judge_model,
                    only_exact, debug,
                    prompt_variables=dialog_vars if dialog_vars else None,
                )
                for turn in dialog["turns"]
            ]
            dialog_pass = all(t["pass"] for t in turn_results)

            dialog_result = {
                "dialog_num": dialog["dialog_num"],
                "dialog_name": dialog.get("dialog_name", ""),
                "turns": turn_results,
                "dialog_pass": dialog_pass,
            }
            all_results.append(dialog_result)
            fw.write(json.dumps(dialog_result, ensure_ascii=False) + "\n")

    return all_results


# ── 메트릭 계산 ───────────────────────────────────────────────────────────────

def compute_metrics(results: List[Dict]) -> Dict:
    """JSON Valid Rate 전용 메트릭을 계산합니다."""
    call_total: int = 0
    json_valid_total: int = 0
    schema_match_total: int = 0  # json_valid AND func_name_match
    completion_total: int = 0
    completion_pass: int = 0
    dialog_pass_count: int = 0

    for dialog in results:
        for turn in dialog.get("turns", []):
            t = turn["type_of_output"]
            if t == "call":
                call_total += 1
                jv = bool(turn.get("json_valid"))
                fm = bool(turn.get("func_name_match"))
                if jv:
                    json_valid_total += 1
                if jv and fm:
                    schema_match_total += 1
            elif t == "completion":
                completion_total += 1
                if turn.get("pass"):
                    completion_pass += 1

        dialog_pass_count += int(bool(dialog.get("dialog_pass", False)))

    def safe_div(a: int, b: int) -> float:
        return a / b if b > 0 else 0.0

    jvr = safe_div(json_valid_total, call_total)
    smr = safe_div(schema_match_total, call_total)
    rcr = safe_div(completion_pass, completion_total)
    tcr = safe_div(dialog_pass_count, len(results))

    return {
        "json_valid_rate": jvr,
        "json_valid_pass": json_valid_total,
        "call_total": call_total,
        "schema_match_rate": smr,
        "schema_match_pass": schema_match_total,
        "response_completion_rate": rcr,
        "completion_pass": completion_pass,
        "completion_total": completion_total,
        "task_completion_rate": tcr,
        "dialog_pass": dialog_pass_count,
        "dialog_total": len(results),
        "overall_score": smr,
    }


# ── 보고서 저장 ───────────────────────────────────────────────────────────────

def save_report(metrics: Dict, results: List[Dict], model: str, output_dir: str) -> str:
    """JSON 점수 파일과 Markdown 보고서를 저장합니다."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # JSON 점수
    score_path = os.path.join(output_dir, f"json_valid_{model}.eval_score.json")
    with open(score_path, "w", encoding="utf-8") as f:
        json.dump({"model": model, "timestamp": timestamp, "metrics": metrics}, f, ensure_ascii=False, indent=2)

    # Markdown 보고서
    md_path = os.path.join(output_dir, f"json_valid_{model}.report.md")

    # 다이얼로그별 결과 행
    dialog_rows = ""
    for d in results:
        status = "✅" if d["dialog_pass"] else "❌"
        call_turns = [t for t in d.get("turns", []) if t["type_of_output"] == "call"]
        jv_pass = sum(1 for t in call_turns if t.get("json_valid"))
        sm_pass = sum(1 for t in call_turns if t.get("json_valid") and t.get("func_name_match"))
        dialog_rows += (
            f"| {d['dialog_num']} | {d['dialog_name']} | {status} "
            f"| {jv_pass}/{len(call_turns)} | {sm_pass}/{len(call_turns)} |\n"
        )

    md_content = f"""# 🧪 API-Bank — JSON Valid Rate 평가 보고서

- **생성 일시**: {timestamp}
- **평가 모델**: {model}
- **총 다이얼로그**: {metrics['dialog_total']}개
- **평가 대상 턴**: call {metrics['call_total']}턴 / completion {metrics['completion_total']}턴

---

## 📊 핵심 지표

| 지표 | 통과 | 전체 | 비율 |
|:---|:---:|:---:|:---:|
| **JSON Valid Rate** (arguments 파싱 성공) | {metrics['json_valid_pass']} | {metrics['call_total']} | {metrics['json_valid_rate']*100:.1f}% |
| **Schema Match Rate** (함수명 + JSON 형식 일치) | {metrics['schema_match_pass']} | {metrics['call_total']} | {metrics['schema_match_rate']*100:.1f}% |
| **Response Completion Rate** (결과 전달 품질) | {metrics['completion_pass']} | {metrics['completion_total']} | {metrics['response_completion_rate']*100:.1f}% |
| **Task Completion Rate** (다이얼로그 완료율) | {metrics['dialog_pass']} | {metrics['dialog_total']} | {metrics['task_completion_rate']*100:.1f}% |
| **Overall Score** (Schema Match Rate) | — | — | **{metrics['overall_score']*100:.1f}%** |

---

## 📋 다이얼로그별 결과

| # | 다이얼로그 | 결과 | JSON Valid | Schema Match |
|:---:|:---|:---:|:---:|:---:|
{dialog_rows}
---

## 📖 지표 설명

| 지표 | 설명 | 측정 방법 |
|:---|:---|:---|
| **JSON Valid Rate** | tool_calls.arguments 가 `json.loads()` 로 파싱 가능한 비율 | 코드 검증 |
| **Schema Match Rate** | JSON 유효 + 함수명이 ground_truth 와 일치하는 비율 | 코드 검증 |
| **Response Completion** | 툴 결과를 자연스럽게 전달하는 능력 | LLM Judge |
| **Task Completion Rate** | 다이얼로그 전체에서 모든 턴이 pass 된 비율 | 집계 |

---

*본 보고서는 API-Bank JSON Valid Rate 벤치마크에 의해 자동으로 생성되었습니다.*
"""

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return md_path


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--model", default="gpt-4o-mini", show_default=True, help="평가할 모델명 (예: gpt-4o-mini)")
@click.option(
    "--input_path",
    default=str(DATA_DIR / "my_eval_json_valid_rate_dialogs.jsonl"),
    show_default=True,
    help="JSON Valid Rate 다이얼로그 JSONL 경로 "
         "(generate_json_valid_rate_dialog_dataset.py 출력)",
)
@click.option(
    "--system_prompt_path",
    default=None,
    help="챗봇 시스템 프롬프트 파일 경로 (미지정 시 data/system_prompt.txt 사용)",
)
@click.option(
    "--api_key",
    default=None,
    help="OpenAI API 키 (미지정 시 OPENAI_API_KEY 환경변수 사용)",
)
@click.option("--base_url", default=None, help="OpenAI 호환 API base URL")
@click.option("--temperature", default=0.0, type=float, help="생성 온도 (기본값: 0.0)")
@click.option("--output_dir", default=None, help="결과 저장 디렉토리 (기본: output/{model})")
@click.option("--reset", is_flag=True, default=False, help="기존 캐시 결과 무시하고 재평가")
@click.option("--num_samples", default=None, type=int, help="평가할 다이얼로그 수 제한")
@click.option(
    "--only_exact",
    is_flag=True,
    default=False,
    help="completion 턴 LLM Judge 생략 (JSON Valid Rate 측정에만 집중)",
)
@click.option("--debug", is_flag=True, default=False, help="턴별 JSON 검증 결과 출력")
def evaluate_json_valid_rate(
    model,
    input_path,
    system_prompt_path,
    api_key,
    base_url,
    temperature,
    output_dir,
    reset,
    num_samples,
    only_exact,
    debug,
):
    """API-Bank JSON Valid Rate 벤치마크 평가를 실행합니다."""

    # ── API 키 확인 ──────────────────────────────────────────────────────────
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print(
            "❌ OpenAI API 키가 필요합니다.\n"
            "   --api_key 옵션 또는 OPENAI_API_KEY 환경변수를 설정하세요."
        )
        sys.exit(1)

    # ── 기본 경로 설정 ───────────────────────────────────────────────────────
    if system_prompt_path is None:
        system_prompt_path = str(DATA_DIR / "system_prompt.txt")
    if output_dir is None:
        output_dir = str(OUTPUT_DIR / model)

    # ── LLM Judge 설정 ───────────────────────────────────────────────────────
    judge_model = "gpt-4o-mini"
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if cfg.get("api_version"):
                judge_model = cfg["api_version"]
        except Exception:
            pass
    judge_client = OpenAI(api_key=api_key)

    # ── 시작 메시지 ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  🧪 API-Bank — JSON Valid Rate 평가")
    print(f"{'=' * 60}")
    print(f"  모델          : {model}")
    print(f"  데이터셋      : {input_path}")
    print(f"  LLM Judge     : {judge_model}")
    print(f"  결과 저장     : {output_dir}")
    print(f"  Only Exact    : {only_exact}")
    print(f"{'=' * 60}\n")

    # ── 1. 데이터셋 로드 ─────────────────────────────────────────────────────
    print("[1/4] 데이터셋 로드 중...")
    dialogs = load_dialogs(input_path)
    if num_samples:
        dialogs = dialogs[:num_samples]

    call_turns = sum(
        1 for d in dialogs for t in d.get("turns", []) if t["type_of_output"] == "call"
    )
    print(f"  ✓ 다이얼로그 {len(dialogs)}개 / call 턴 {call_turns}개")

    # ── 2. 모델 초기화 ───────────────────────────────────────────────────────
    print("\n[2/4] 모델 초기화 중...")
    # dialog별 user_id/user_email은 evaluate_dialogs에서 per-call로 주입됨
    caller = ModelCaller(
        model=model,
        api_key=api_key,
        temperature=temperature,
        base_url=base_url,
        system_prompt_path=system_prompt_path,
    )
    print(f"  ✓ {model} 준비 완료")

    # ── 3. 평가 실행 ─────────────────────────────────────────────────────────
    print("\n[3/4] 평가 실행 중...")
    results = evaluate_dialogs(
        dialogs=dialogs,
        caller=caller,
        judge_client=judge_client,
        judge_model=judge_model,
        target_model=model,
        output_dir=output_dir,
        only_exact=only_exact,
        reset=reset,
        debug=debug,
    )
    print(f"  ✓ {len(results)}개 다이얼로그 평가 완료")

    # ── 4. 메트릭 계산 및 보고서 저장 ────────────────────────────────────────
    print("\n[4/4] 메트릭 계산 및 보고서 저장 중...")
    metrics = compute_metrics(results)
    report_path = save_report(metrics, results, model, output_dir)
    print(f"  ✓ 보고서 저장: {report_path}")

    # ── 결과 출력 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  📊 JSON Valid Rate 평가 결과 — {model}")
    print(f"{'=' * 60}")
    print(
        f"  JSON Valid Rate    : "
        f"{metrics['json_valid_pass']}/{metrics['call_total']} "
        f"({metrics['json_valid_rate']*100:.1f}%)"
    )
    print(
        f"  Schema Match Rate  : "
        f"{metrics['schema_match_pass']}/{metrics['call_total']} "
        f"({metrics['schema_match_rate']*100:.1f}%)"
    )
    print(
        f"  Response Completion: "
        f"{metrics['completion_pass']}/{metrics['completion_total']} "
        f"({metrics['response_completion_rate']*100:.1f}%)"
    )
    print(
        f"  Task Completion    : "
        f"{metrics['dialog_pass']}/{metrics['dialog_total']} "
        f"({metrics['task_completion_rate']*100:.1f}%)"
    )
    print(f"  ─────────────────────────────────────────────")
    print(f"  Overall Score      : {metrics['overall_score']*100:.1f}%")
    print(f"{'=' * 60}\n")


