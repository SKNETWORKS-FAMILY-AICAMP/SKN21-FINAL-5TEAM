#!/usr/bin/env python3
"""
API-Bank Benchmark — evaluate.py

이커머스 챗봇의 멀티턴 API 호출 능력을 평가합니다.

사용 예시:
  python evaluate.py \\
    --model gpt-4o-mini \\
    --input_path ../FunctionChat-Bench/data/my_eval_slot_filling_rate_dialogs.jsonl \\
    --api_key sk-... \\
    --system_prompt_path data/system_prompt.txt \\
    --temperature 0.0

평가 지표:
  - Slot Filling Rate (SFR)       : 역질문으로 슬롯을 수집하는 능력
  - API Call Accuracy (ACA)       : 올바른 API를 올바른 인자로 호출하는 능력
  - Response Completion Rate (RCR): 툴 결과를 자연스럽게 전달하는 능력
  - Task Completion Rate (TCR)    : 다이얼로그 전체 완료율
  - Overall Score                 : SFR·ACA·RCR 의 산술 평균
"""

import os
import sys

# evaluate.py 가 있는 API-Bank/ 를 모듈 탐색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import click
from dotenv import load_dotenv

from src.paths import BENCH_ROOT, DATA_DIR, OUTPUT_DIR, ENV_PATH

load_dotenv(ENV_PATH)

from src.dataset_loader import load_dialogs, count_turns_by_type
from src.model_caller import ModelCaller
from src.evaluator import DialogEvaluator
from src.metrics import compute_metrics, save_report


@click.command()
@click.option("--model", required=True, help="평가할 모델명 (예: gpt-4o-mini)")
@click.option(
    "--input_path",
    required=True,
    help="다이얼로그 JSONL 데이터셋 경로 (generate_slot_filling_rate_dialog_dataset.py 출력)",
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
@click.option(
    "--base_url",
    default=None,
    help="OpenAI 호환 API base URL (기본: None → OpenAI 공식)",
)
@click.option("--temperature", default=0.0, type=float, help="생성 온도 (기본값: 0.0)")
@click.option("--output_dir", default=None, help="결과 저장 디렉토리 (기본: output/{model})")
@click.option("--reset", is_flag=True, default=False, help="기존 캐시 결과 무시하고 재평가")
@click.option(
    "--num_samples",
    default=None,
    type=int,
    help="평가할 다이얼로그 수 제한 (기본: 전체)",
)
@click.option(
    "--only_exact",
    is_flag=True,
    default=False,
    help="Exact Match 만 사용 (LLM Judge 없이) — 비용 절감",
)
@click.option("--debug", is_flag=True, default=False, help="턴별 통과/실패 출력")
def evaluate(
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
    """API-Bank 벤치마크 평가를 실행합니다."""

    # ── API 키 확인 ──────────────────────────────────────────────────────────
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print(
            "❌ OpenAI API 키가 필요합니다.\n"
            "   --api_key 옵션 또는 OPENAI_API_KEY 환경변수를 설정하세요."
        )
        sys.exit(1)

    # ── 경로 기본값 설정 ─────────────────────────────────────────────────────
    if system_prompt_path is None:
        system_prompt_path = str(DATA_DIR / "system_prompt.txt")

    if output_dir is None:
        output_dir = str(OUTPUT_DIR / model)

    os.makedirs(output_dir, exist_ok=True)

    # ── 시작 메시지 ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  🚀 API-Bank 벤치마크 평가")
    print(f"{'=' * 60}")
    print(f"  모델        : {model}")
    print(f"  데이터셋    : {input_path}")
    print(f"  시스템 프롬프트: {system_prompt_path}")
    print(f"  결과 저장   : {output_dir}")
    print(f"  Only Exact  : {only_exact}")
    print(f"{'=' * 60}\n")

    # ── 1. 데이터셋 로드 ─────────────────────────────────────────────────────
    print("[1/4] 데이터셋 로드 중...")
    dialogs = load_dialogs(input_path)
    if num_samples:
        dialogs = dialogs[:num_samples]

    turn_counts = count_turns_by_type(dialogs)
    print(f"  ✓ 다이얼로그 {len(dialogs)}개 로드")
    print(
        f"     slot: {turn_counts['slot']}턴 / "
        f"call: {turn_counts['call']}턴 / "
        f"completion: {turn_counts['completion']}턴"
    )

    # ── 2. 모델 호출기 초기화 ────────────────────────────────────────────────
    print("\n[2/4] 모델 호출기 초기화 중...")
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
    evaluator = DialogEvaluator(
        target_model=model,
        judge_api_key=api_key,
        output_dir=output_dir,
        only_exact=only_exact,
        debug=debug,
    )
    results = evaluator.evaluate_dialogs(dialogs, caller, reset=reset)
    print(f"  ✓ {len(results)}개 다이얼로그 평가 완료")

    # ── 4. 메트릭 계산 및 보고서 저장 ────────────────────────────────────────
    print("\n[4/4] 메트릭 계산 및 보고서 저장 중...")
    metrics = compute_metrics(results)
    report_path = save_report(metrics, results, model, output_dir)
    print(f"  ✓ 보고서 저장: {report_path}")

    # ── 결과 출력 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  📊 API-Bank 평가 결과 — {model}")
    print(f"{'=' * 60}")
    print(
        f"  Slot Filling Rate     : "
        f"{metrics['slot_pass']}/{metrics['slot_total']} "
        f"({metrics['slot_filling_rate'] * 100:.1f}%)"
    )
    print(
        f"  API Call Accuracy     : "
        f"{metrics['call_pass']}/{metrics['call_total']} "
        f"({metrics['api_call_accuracy'] * 100:.1f}%)"
    )
    print(
        f"  Response Completion   : "
        f"{metrics['completion_pass']}/{metrics['completion_total']} "
        f"({metrics['response_completion_rate'] * 100:.1f}%)"
    )
    print(
        f"  Task Completion Rate  : "
        f"{metrics['dialog_pass']}/{metrics['dialog_total']} "
        f"({metrics['task_completion_rate'] * 100:.1f}%)"
    )
    print(f"  ─────────────────────────────────────────────")
    print(f"  Overall Score         : {metrics['overall_score'] * 100:.1f}%")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    evaluate()
