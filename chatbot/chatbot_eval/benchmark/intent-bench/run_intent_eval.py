"""
Intent 분류 평가 실행기.

intent_dataset.jsonl을 로드하여 planner_node를 직접 호출하고,
분류 정확도를 측정하여 result_intent_rate.json으로 저장합니다.
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ── 경로 설정 ──────────────────────────────────────────────
# [변경 포인트] 아래 DATASET_PATH를 변경하여 평가할 데이터셋을 전환할 수 있습니다.
# - 평가 데이터셋 사용 시: "intent_eval_dataset.jsonl"
# - 학습 데이터셋 사용 시: "intent_train_dataset.jsonl"
# 또는 CLI에서 --dataset 인자로 지정 가능:
#   python run_intent_eval.py --dataset intent_train_dataset.jsonl

BENCH_DIR = Path(__file__).resolve().parent
DATASET_PATH = BENCH_DIR / "intent_eval_dataset.jsonl"        # ← 학습용: "intent_train_dataset.jsonl"으로 변경
RESULT_PATH = BENCH_DIR / "result_intent_rate.json"


def _find_project_root(start: Path, marker: str = ".env") -> Path:
    for parent in [start] + list(start.parents):
        if (parent / marker).exists():
            return parent
    return start.parents[4]


_PROJECT_ROOT = _find_project_root(BENCH_DIR)
sys.path.insert(0, str(_PROJECT_ROOT))
load_dotenv(_PROJECT_ROOT / ".env")

# ── 프로젝트 import (dotenv 로드 이후) ─────────────────────

from langchain_core.messages import HumanMessage  # noqa: E402

from chatbot.benchmark.evaluator.metrics import EvaluationMetrics  # noqa: E402
from chatbot.src.graph.nodes.planner import planner_node  # noqa: E402
from chatbot.src.schemas.planner import TaskIntent  # noqa: E402


# ── 데이터셋 로드 ─────────────────────────────────────────


def load_dataset(path: Path) -> list[dict]:
    """JSONL 데이터셋 로드."""
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


# ── Planner 호출 ──────────────────────────────────────────


def call_planner(
    user_input: str,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
) -> list[str]:
    """planner_node를 최소 GlobalAgentState로 호출하여 predicted intents 반환."""
    state = {
        "messages": [HumanMessage(content=user_input)],
        "llm_provider": provider,
        "llm_model": model,
        "conversation_summary": None,
    }
    result = planner_node(state)
    predicted = result.get("pending_tasks", [])

    # TaskIntent enum일 수 있으므로 문자열로 통일
    return [
        t.value if isinstance(t, TaskIntent) else str(t)
        for t in predicted
    ]


# ── 평가 메트릭 계산 ──────────────────────────────────────


def evaluate_single_sample(
    predicted: list[str], expected: list[str],
) -> dict:
    """단일 샘플 평가 결과 반환."""
    # Exact match (순서 무관)
    exact_match = set(predicted) == set(expected)

    # Set 기반 precision/recall/f1
    pred_set = set(predicted)
    exp_set = set(expected)
    tp = len(pred_set & exp_set)
    fp = len(pred_set - exp_set)
    fn = len(exp_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "exact_match": exact_match,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def build_confusion_matrix(
    details: list[dict],
) -> dict[str, dict[str, int]]:
    """단일 의도 샘플에서 confusion matrix 생성."""
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for d in details:
        if d["category"] != "single":
            continue
        expected = d["expected"][0]
        # 예측이 단일이면 첫 번째, 아니면 첫 번째 사용
        predicted = d["predicted"][0] if d["predicted"] else "NONE"
        matrix[expected][predicted] += 1

    # defaultdict → 일반 dict 변환
    return {k: dict(v) for k, v in matrix.items()}


# ── 메인 평가 루프 ────────────────────────────────────────


def run_evaluation(
    dataset_path: Path = DATASET_PATH,
    result_path: Path = RESULT_PATH,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    num_samples: int | None = None,
) -> dict:
    """전체 평가 실행."""
    samples = load_dataset(dataset_path)
    if num_samples:
        samples = samples[:num_samples]

    print(f"=== Intent 분류 평가 시작 ===")
    print(f"  모델: {provider}/{model}")
    print(f"  샘플 수: {len(samples)}")
    print()

    details: list[dict] = []
    # F1 계산용: 단일 의도만
    all_predicted_single: list[str] = []
    all_expected_single: list[str] = []

    start_time = time.time()

    for i, sample in enumerate(samples):
        user_input = sample["input"]
        expected = sample["expected_intents"]
        category = sample.get("category", "single")

        try:
            predicted = call_planner(user_input, provider, model)
        except Exception as e:
            print(f"  [{i+1}/{len(samples)}] 오류: {e}")
            predicted = ["GENERAL_CHAT"]

        eval_result = evaluate_single_sample(predicted, expected)

        detail = {
            "input": user_input,
            "expected": expected,
            "predicted": predicted,
            "category": category,
            "correct": eval_result["exact_match"],
            "precision": eval_result["precision"],
            "recall": eval_result["recall"],
            "f1": eval_result["f1"],
        }
        details.append(detail)

        # 단일 의도용 F1 집계
        if category == "single":
            all_predicted_single.append(predicted[0] if predicted else "NONE")
            all_expected_single.append(expected[0])

        status = "O" if eval_result["exact_match"] else "X"
        print(
            f"  [{i+1}/{len(samples)}] {status}  "
            f"예상: {expected}  예측: {predicted}  "
            f"입력: {user_input[:40]}..."
        )

    elapsed = time.time() - start_time

    # ── 통계 계산 ──────────────────────────────────────────

    total = len(details)
    correct = sum(1 for d in details if d["correct"])

    # 카테고리별 분리
    single_details = [d for d in details if d["category"] == "single"]
    multi_details = [d for d in details if d["category"] == "multi"]

    single_correct = sum(1 for d in single_details if d["correct"])
    multi_correct = sum(1 for d in multi_details if d["correct"])

    # 기존 metrics.py의 intent_f1_score 활용
    per_intent_f1 = {}
    macro_f1 = 0.0
    if all_predicted_single and all_expected_single:
        per_intent_f1 = EvaluationMetrics.intent_f1_score(
            all_predicted_single, all_expected_single,
        )
        macro_f1 = per_intent_f1.get("macro_avg", {}).get("f1", 0.0)

    # Confusion matrix
    confusion = build_confusion_matrix(details)

    # ── 결과 조립 ──────────────────────────────────────────

    result = {
        "model": f"{provider}/{model}",
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "total_samples": total,
        "metrics": {
            "overall_accuracy": round(correct / total, 4) if total else 0.0,
            "single_intent_accuracy": (
                round(single_correct / len(single_details), 4)
                if single_details else 0.0
            ),
            "multi_intent_exact_match": (
                round(multi_correct / len(multi_details), 4)
                if multi_details else 0.0
            ),
            "per_intent_f1": per_intent_f1,
            "macro_f1": round(macro_f1, 4),
            "confusion_matrix": confusion,
        },
        "summary": {
            "total": total,
            "correct": correct,
            "single_total": len(single_details),
            "single_correct": single_correct,
            "multi_total": len(multi_details),
            "multi_correct": multi_correct,
        },
        "details": details,
    }

    # 저장
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ── 결과 출력 ──────────────────────────────────────────

    print(f"\n{'='*50}")
    print(f"=== 평가 결과 ===")
    print(f"{'='*50}")
    print(f"  모델: {provider}/{model}")
    print(f"  소요 시간: {elapsed:.1f}초")
    print(f"  전체 정확도: {result['metrics']['overall_accuracy']:.2%} ({correct}/{total})")
    print(f"  단일 의도 정확도: {result['metrics']['single_intent_accuracy']:.2%} ({single_correct}/{len(single_details)})")
    print(f"  복합 의도 Exact Match: {result['metrics']['multi_intent_exact_match']:.2%} ({multi_correct}/{len(multi_details)})")
    print(f"  Macro F1: {macro_f1:.4f}")

    if per_intent_f1:
        print(f"\n  [Intent별 F1]")
        for intent, scores in sorted(per_intent_f1.items()):
            if intent == "macro_avg":
                continue
            if isinstance(scores, dict):
                print(
                    f"    {intent}: "
                    f"P={scores.get('precision', 0):.3f} "
                    f"R={scores.get('recall', 0):.3f} "
                    f"F1={scores.get('f1', 0):.3f} "
                    f"(n={scores.get('support', 0)})"
                )

    if confusion:
        print(f"\n  [Confusion Matrix]")
        all_intents = sorted(set(
            list(confusion.keys()) +
            [p for row in confusion.values() for p in row.keys()]
        ))
        # 헤더
        header = f"{'실제\\예측':>25s}"
        for intent in all_intents:
            short = intent[:8]
            header += f" {short:>8s}"
        print(f"    {header}")
        # 행
        for actual in all_intents:
            row = f"{actual:>25s}"
            for pred in all_intents:
                count = confusion.get(actual, {}).get(pred, 0)
                row += f" {count:>8d}"
            print(f"    {row}")

    print(f"\n  결과 저장: {result_path}")

    return result


# ── CLI ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Intent 분류 평가 실행")
    parser.add_argument(
        "--provider", type=str, default="openai",
        help="LLM provider (기본: openai)",
    )
    parser.add_argument(
        "--model", type=str, default="gpt-4o-mini",
        help="LLM 모델 (기본: gpt-4o-mini)",
    )
    parser.add_argument(
        "--dataset", type=str, default=None,
        help="평가 데이터셋 경로 (기본: intent_dataset.jsonl)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="결과 저장 경로 (기본: result_intent_rate.json)",
    )
    parser.add_argument(
        "--num-samples", type=int, default=None,
        help="평가할 샘플 수 (기본: 전체)",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset) if args.dataset else DATASET_PATH
    result_path = Path(args.output) if args.output else RESULT_PATH

    if not dataset_path.exists():
        print(f"[오류] {dataset_path} 파일을 찾을 수 없습니다.")
        print("  먼저 generate_intent_rate.py를 실행하여 데이터셋을 생성하세요.")
        sys.exit(1)

    run_evaluation(
        dataset_path=dataset_path,
        result_path=result_path,
        provider=args.provider,
        model=args.model,
        num_samples=args.num_samples,
    )


if __name__ == "__main__":
    main()
