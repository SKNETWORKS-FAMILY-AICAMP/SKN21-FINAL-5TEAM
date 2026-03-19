"""Policy RAG evaluation entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from math import ceil


CURRENT_FILE = Path(__file__).resolve()
REPO_ROOT = CURRENT_FILE.parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chatbot.chatbot_eval.benchmark.rags.policy_rag.src.evaluator import evaluate
from chatbot.chatbot_eval.benchmark.rags.policy_rag.src.dataset_loader import load_jsonl


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
        "--offset",
        type=int,
        default=0,
        help="Optional dataset row offset for partial evaluation.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="If set, evaluate the dataset in chunks of this size and merge the results.",
    )
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=None,
        help="Optional worker count for parallel chunk evaluation. Defaults to up to 4 workers when chunking is enabled.",
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


def _merge_reports(
    dataset_path: str,
    provider: str,
    model: str,
    chunk_size: int,
    chunk_reports: list[dict],
) -> dict:
    results: list[dict] = []
    total = 0
    query_pass_count = 0
    retrieval_pass_count = 0
    retrieval_hit_at_1 = 0
    retrieval_hit_at_3 = 0
    retrieval_hit_at_5 = 0

    for report in chunk_reports:
        results.extend(report.get("results", []))
        total += int(report.get("dataset_size", 0))
        query_pass_count += sum(1 for row in report.get("results", []) if row["query_eval"]["passed"])
        retrieval_pass_count += sum(1 for row in report.get("results", []) if row["retrieval_eval"]["passed"])
        retrieval_hit_at_1 += sum(row["retrieval_eval"].get("hit_at_1", 0) for row in report.get("results", []))
        retrieval_hit_at_3 += sum(row["retrieval_eval"].get("hit_at_3", 0) for row in report.get("results", []))
        retrieval_hit_at_5 += sum(row["retrieval_eval"].get("hit_at_5", 0) for row in report.get("results", []))

    return {
        "dataset_path": str(dataset_path),
        "provider": provider,
        "model": model,
        "dataset_size": total,
        "query_pass_rate": round(query_pass_count / total, 4) if total else 0.0,
        "retrieval_pass_rate": round(retrieval_pass_count / total, 4) if total else 0.0,
        "retrieval_hit_at_1": round(retrieval_hit_at_1 / total, 4) if total else 0.0,
        "retrieval_hit_at_3": round(retrieval_hit_at_3 / total, 4) if total else 0.0,
        "retrieval_hit_at_5": round(retrieval_hit_at_5 / total, 4) if total else 0.0,
        "chunk_size": chunk_size,
        "chunk_reports": chunk_reports,
        "results": results,
    }


def _evaluate_chunk(
    *,
    dataset_path: str,
    provider: str,
    model: str,
    chunk_index: int,
    chunk_offset: int,
    chunk_limit: int,
) -> dict:
    chunk_report = evaluate(
        dataset_path=dataset_path,
        provider=provider,
        model=model,
        limit=chunk_limit,
        offset=chunk_offset,
    )
    return {
        "chunk_index": chunk_index,
        "offset": chunk_offset,
        "limit": chunk_limit,
        **chunk_report,
    }


def main() -> None:
    args = parse_args()
    if args.chunk_size and args.chunk_size > 0:
        dataset = load_jsonl(args.dataset)
        if args.offset:
            dataset = dataset[args.offset:]
        if args.limit is not None:
            dataset = dataset[: args.limit]

        total_rows = len(dataset)
        chunk_reports: list[dict] = []
        chunk_count = ceil(total_rows / args.chunk_size) if total_rows else 0
        chunk_jobs: list[dict[str, int]] = []
        for chunk_index in range(chunk_count):
            chunk_offset = args.offset + (chunk_index * args.chunk_size)
            chunk_limit = min(args.chunk_size, total_rows - (chunk_index * args.chunk_size))
            chunk_jobs.append(
                {
                    "chunk_index": chunk_index + 1,
                    "chunk_offset": chunk_offset,
                    "chunk_limit": chunk_limit,
                    "start_row": chunk_index * args.chunk_size + 1,
                    "end_row": chunk_index * args.chunk_size + chunk_limit,
                }
            )

        worker_count = args.parallel_workers
        if worker_count is None:
            worker_count = min(4, chunk_count) if chunk_count else 1
        worker_count = max(1, min(worker_count, chunk_count)) if chunk_count else 1

        if chunk_count:
            print(f"Running {chunk_count} chunks with {worker_count} worker(s)...")

        if worker_count == 1:
            for job in chunk_jobs:
                print(
                    f"Running chunk {job['chunk_index']}/{chunk_count} "
                    f"(rows {job['start_row']}-{job['end_row']})..."
                )
                chunk_reports.append(
                    _evaluate_chunk(
                        dataset_path=args.dataset,
                        provider=args.provider,
                        model=args.model,
                        chunk_index=job["chunk_index"],
                        chunk_offset=job["chunk_offset"],
                        chunk_limit=job["chunk_limit"],
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="policy-eval") as executor:
                future_to_job = {
                    executor.submit(
                        _evaluate_chunk,
                        dataset_path=args.dataset,
                        provider=args.provider,
                        model=args.model,
                        chunk_index=job["chunk_index"],
                        chunk_offset=job["chunk_offset"],
                        chunk_limit=job["chunk_limit"],
                    ): job
                    for job in chunk_jobs
                }
                for future in as_completed(future_to_job):
                    job = future_to_job[future]
                    print(
                        f"Completed chunk {job['chunk_index']}/{chunk_count} "
                        f"(rows {job['start_row']}-{job['end_row']})"
                    )
                    chunk_reports.append(future.result())

        chunk_reports.sort(key=lambda report: int(report["chunk_index"]))

        report = _merge_reports(
            dataset_path=args.dataset,
            provider=args.provider,
            model=args.model,
            chunk_size=args.chunk_size,
            chunk_reports=chunk_reports,
        )
    else:
        report = evaluate(
            dataset_path=args.dataset,
            provider=args.provider,
            model=args.model,
            limit=args.limit,
            offset=args.offset,
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
