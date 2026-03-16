"""Policy RAG evaluation entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


CURRENT_FILE = Path(__file__).resolve()
REPO_ROOT = CURRENT_FILE.parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chatbot.chatbot_eval.benchmark.rags.policy_rag.src.evaluator import evaluate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Policy RAG evaluation.")
    parser.add_argument(
        "--dataset",
        default=str(CURRENT_FILE.parent / "data" / "eval_dataset.jsonl"),
        help="Path to the evaluation dataset JSONL file.",
    )
    parser.add_argument(
        "--provider",
        default="openai",
        choices=["openai", "vllm"],
        help="LLM provider used for query transformation.",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="Model name used for query transformation.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for the number of evaluation rows.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to save the JSON report.",
    )
    return parser.parse_args()


def default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return CURRENT_FILE.parent / "reports" / f"policy_rag_eval_{timestamp}.json"


def main() -> None:
    args = parse_args()
    report = evaluate(
        dataset_path=args.dataset,
        provider=args.provider,
        model=args.model,
        limit=args.limit,
    )

    output_path = Path(args.output) if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Dataset size: {report['dataset_size']}")
    print(f"Query pass rate: {report['query_pass_rate']:.2%}")
    print(f"Retrieval pass rate: {report['retrieval_pass_rate']:.2%}")
    print(f"Retrieval Hit@1: {report['retrieval_hit_at_1']:.2%}")
    print(f"Retrieval Hit@3: {report['retrieval_hit_at_3']:.2%}")
    print(f"Retrieval Hit@5: {report['retrieval_hit_at_5']:.2%}")
    print(f"Saved report: {output_path}")


if __name__ == "__main__":
    main()
