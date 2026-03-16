"""
Supervisor 라우팅 평가 실행기.

supervisor_eval_dataset.jsonl을 로드하여 planner_node를 호출하고,
supervisor의 _INTENT_TO_NODE 매핑으로 라우팅 결과를 시뮬레이션하여
4개 subagent(order_intent_router, discovery_subagent, policy_rag_subagent,
form_action_subagent)로 정확하게 라우팅되는지 평가합니다.

단일 의도만 평가하며, result.json에는 details 없이 메트릭만 누적 저장합니다.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ── 경로 설정 ──────────────────────────────────────────────

BENCH_DIR = Path(__file__).resolve().parent
DATASET_PATH = BENCH_DIR / "supervisor_eval_dataset.jsonl"
_RESULT_BASE_DIR = BENCH_DIR.parent / "result"

# TaskIntent → 평가용 노드 이름 매핑
# supervisor.py의 _INTENT_TO_NODE 기반, order_entry → order_intent_router로 표기
INTENT_TO_NODE: dict[str, str] = {
    "ORDER_CS":             "order_intent_router",
    "SEARCH_SIMILAR_TEXT":  "discovery_subagent",
    "SEARCH_SIMILAR_IMAGE": "discovery_subagent",
    "POLICY_RAG":           "policy_rag_subagent",
    "REGISTER_USED_ITEM":   "form_action_subagent",
    "WRITE_REVIEW":         "form_action_subagent",
    "REGISTER_GIFT_CARD":   "form_action_subagent",
    "GENERAL_CHAT":         "final_generator",
}


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


# ── Planner 호출 → 노드 라우팅 시뮬레이션 ─────────────────


def predict_nodes(
    user_input: str,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
) -> list[str]:
    """planner_node 호출 → intent → INTENT_TO_NODE 매핑으로 예측 노드 반환."""
    state = {
        "messages": [HumanMessage(content=user_input)],
        "llm_provider": provider,
        "llm_model": model,
        "conversation_summary": None,
    }
    result = planner_node(state)
    predicted_intents = result.get("pending_tasks", [])

    nodes = []
    for intent in predicted_intents:
        intent_str = intent.value if isinstance(intent, TaskIntent) else str(intent)
        node = INTENT_TO_NODE.get(intent_str, "final_generator")
        nodes.append(node)
    return nodes


# ── 샘플별 평가 ──────────────────────────────────────────


def evaluate_sample(
    sample: dict,
    predicted_nodes: list[str],
) -> bool:
    """예측 노드가 기대 노드와 일치하는지 반환."""
    exp_node = sample["expected_node"]
    pred_node = predicted_nodes[0] if predicted_nodes else "NONE"
    return pred_node == exp_node


# ── Confusion Matrix ────────────────────────────────────


def build_confusion(details: list[dict]) -> dict[str, dict[str, int]]:
    """confusion matrix 생성."""
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in details:
        expected = d["expected_node"]
        predicted = d["predicted_node"]
        matrix[expected][predicted] += 1
    return {k: dict(v) for k, v in matrix.items()}


# ── 메인 평가 루프 ────────────────────────────────────────


def run_evaluation(
    dataset_path: Path = DATASET_PATH,
    result_path: Path | None = None,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    num_samples: int | None = None,
) -> dict:
    """전체 평가 실행."""
    if result_path is None:
        result_dir = _RESULT_BASE_DIR / "supervisor_eval"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / "result.json"

    samples = load_dataset(dataset_path)
    if num_samples:
        samples = samples[:num_samples]

    print("=== Supervisor 라우팅 평가 시작 ===")
    print(f"  모델: {provider}/{model}")
    print(f"  샘플 수: {len(samples)}")
    print()

    details: list[dict] = []
    all_pred_nodes: list[str] = []
    all_exp_nodes: list[str] = []

    start_time = time.time()

    for i, sample in enumerate(samples):
        user_input = sample["input"]

        # planner → supervisor 라우팅 시뮬레이션
        try:
            predicted_nodes = predict_nodes(user_input, provider, model)
        except Exception as e:
            print(f"  [{i+1}/{len(samples)}] 오류: {e}")
            predicted_nodes = ["final_generator"]

        correct = evaluate_sample(sample, predicted_nodes)

        pred_node = predicted_nodes[0] if predicted_nodes else "NONE"
        all_pred_nodes.append(pred_node)
        all_exp_nodes.append(sample["expected_node"])

        details.append({
            "input": user_input,
            "predicted_node": pred_node,
            "expected_node": sample["expected_node"],
            "correct": correct,
        })

        # 콘솔 출력
        status = "O" if correct else "X"
        print(
            f"  [{i+1}/{len(samples)}] {status}  "
            f"기대: {sample['expected_node']}  예측: {pred_node}  "
            f"입력: {user_input[:50]}..."
        )

    elapsed = time.time() - start_time

    # ── 통계 계산 ──────────────────────────────────────────

    total = len(details)
    correct_total = sum(1 for d in details if d["correct"])

    # 노드별 F1 (단일 샘플 기준)
    per_node_f1: dict = {}
    macro_f1 = 0.0
    if all_pred_nodes and all_exp_nodes:
        all_labels = sorted(set(all_pred_nodes + all_exp_nodes))
        for label in all_labels:
            tp = sum(1 for p, e in zip(all_pred_nodes, all_exp_nodes) if p == label and e == label)
            fp = sum(1 for p, e in zip(all_pred_nodes, all_exp_nodes) if p == label and e != label)
            fn = sum(1 for p, e in zip(all_pred_nodes, all_exp_nodes) if p != label and e == label)
            support = tp + fn
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            per_node_f1[label] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "support": support,
            }

        node_f1s = [v["f1"] for v in per_node_f1.values()]
        macro_f1 = sum(node_f1s) / len(node_f1s)
        per_node_f1["macro_avg"] = {
            "precision": round(sum(v["precision"] for v in per_node_f1.values() if "support" in v) / len(node_f1s), 4),
            "recall": round(sum(v["recall"] for v in per_node_f1.values() if "support" in v) / len(node_f1s), 4),
            "f1": round(macro_f1, 4),
        }

    # Confusion matrix
    confusion = build_confusion(details)

    # ── 결과 조립 ──────────────────────────────────────────

    result = {
        "model": f"{provider}/{model}",
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "total_samples": total,
        "metrics": {
            "accuracy": round(correct_total / total, 4) if total else 0.0,
            "per_node_f1": per_node_f1,
            "macro_f1": round(macro_f1, 4),
            "confusion_matrix": confusion,
        },
        "summary": {
            "total": total,
            "correct": correct_total,
        },
    }

    # 결과 누적 저장 (메트릭만)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if result_path.exists():
        with open(result_path, encoding="utf-8") as f:
            history = json.load(f)
    history.append(result)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    # 상세 예측 데이터 누적 저장 (result_data.json)
    result_data_path = result_path.parent / "result_data.json"
    result_data = {
        "model": f"{provider}/{model}",
        "timestamp": result["timestamp"],
        "total_samples": total,
        "details": details,
    }
    data_history: list[dict] = []
    if result_data_path.exists():
        with open(result_data_path, encoding="utf-8") as f:
            data_history = json.load(f)
    data_history.append(result_data)
    with open(result_data_path, "w", encoding="utf-8") as f:
        json.dump(data_history, f, ensure_ascii=False, indent=2)

    # ── 결과 출력 ──────────────────────────────────────────

    print(f"\n{'='*55}")
    print("=== Supervisor 라우팅 평가 결과 ===")
    print(f"{'='*55}")
    print(f"  모델: {provider}/{model}")
    print(f"  소요 시간: {elapsed:.1f}초")
    print(f"\n  [라우팅 정확도]")
    print(f"    정확도: {result['metrics']['accuracy']:.2%} ({correct_total}/{total})")
    print(f"    Macro F1: {macro_f1:.4f}")

    if per_node_f1:
        print(f"\n  [노드별 F1]")
        for node, scores in sorted(per_node_f1.items()):
            if node == "macro_avg":
                continue
            print(
                f"    {node}: "
                f"P={scores['precision']:.3f} "
                f"R={scores['recall']:.3f} "
                f"F1={scores['f1']:.3f} "
                f"(n={scores.get('support', '-')})"
            )

    if confusion:
        print(f"\n  [Confusion Matrix]")
        all_nodes = sorted(set(
            list(confusion.keys()) +
            [p for row in confusion.values() for p in row.keys()]
        ))
        header = f"{'실제\\예측':>22s}"
        for n in all_nodes:
            header += f" {n[:14]:>14s}"
        print(f"    {header}")
        for actual in all_nodes:
            row = f"{actual[:14]:>22s}"
            for pred in all_nodes:
                count = confusion.get(actual, {}).get(pred, 0)
                row += f" {count:>14d}"
            print(f"    {row}")

    print(f"\n  결과 저장: {result_path}")
    print(f"  상세 데이터 저장: {result_data_path}")

    return result


# ── CLI ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Supervisor 라우팅 평가 실행")
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
        help="평가 데이터셋 경로 (기본: supervisor_eval_dataset.jsonl)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="결과 저장 경로",
    )
    parser.add_argument(
        "--num-samples", type=int, default=None,
        help="평가할 샘플 수 (기본: 전체)",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset) if args.dataset else DATASET_PATH
    result_path = Path(args.output) if args.output else None

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
