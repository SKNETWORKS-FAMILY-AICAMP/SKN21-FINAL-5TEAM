from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chatbot.chatbot_eval.benchmark.rags.policy_rag import run as policy_run
from chatbot.chatbot_eval.benchmark.rags.policy_rag.run import _evaluate_chunk, _merge_reports
from chatbot.chatbot_eval.benchmark.rags.policy_rag.src.evaluator import evaluate


def test_policy_evaluate_supports_offset(monkeypatch, tmp_path: Path) -> None:
    dataset_path = tmp_path / "policy_eval.jsonl"
    rows = [
        {"id": "p1", "user_query": "q1", "expected_query": "eq1", "expected_phrases": ["a"]},
        {"id": "p2", "user_query": "q2", "expected_query": "eq2", "expected_phrases": ["b"]},
        {"id": "p3", "user_query": "q3", "expected_query": "eq3", "expected_phrases": ["c"]},
    ]
    dataset_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )

    def fake_evaluate_case(case, provider, model):
        return {
            "id": case["id"],
            "query_eval": {"passed": True},
            "retrieval_eval": {"passed": True, "hit_at_1": 1, "hit_at_3": 1, "hit_at_5": 1},
        }

    monkeypatch.setattr(
        "chatbot.chatbot_eval.benchmark.rags.policy_rag.src.evaluator.evaluate_case",
        fake_evaluate_case,
    )

    report = evaluate(dataset_path=dataset_path, offset=1, limit=1)

    assert report["dataset_size"] == 1
    assert report["results"][0]["id"] == "p2"


def test_merge_reports_aggregates_chunk_metrics() -> None:
    chunk_reports = [
        {
            "dataset_size": 2,
            "results": [
                {"query_eval": {"passed": True}, "retrieval_eval": {"passed": True, "hit_at_1": 1, "hit_at_3": 1, "hit_at_5": 1}},
                {"query_eval": {"passed": False}, "retrieval_eval": {"passed": True, "hit_at_1": 0, "hit_at_3": 1, "hit_at_5": 1}},
            ],
        },
        {
            "dataset_size": 1,
            "results": [
                {"query_eval": {"passed": True}, "retrieval_eval": {"passed": False, "hit_at_1": 0, "hit_at_3": 0, "hit_at_5": 0}},
            ],
        },
    ]

    report = _merge_reports(
        dataset_path="dataset.jsonl",
        provider="openai",
        model="gpt-4o-mini",
        chunk_size=10,
        chunk_reports=chunk_reports,
    )

    assert report["dataset_size"] == 3
    assert report["query_pass_rate"] == 0.6667
    assert report["retrieval_pass_rate"] == 0.6667
    assert report["retrieval_hit_at_1"] == 0.3333
    assert report["retrieval_hit_at_3"] == 0.6667
    assert report["retrieval_hit_at_5"] == 0.6667
    assert len(report["results"]) == 3


def test_evaluate_chunk_wraps_metadata(monkeypatch) -> None:
    def fake_evaluate(*, dataset_path, provider, model, limit, offset):
        return {
            "dataset_size": 1,
            "results": [{"id": f"case-{offset}"}],
            "query_pass_rate": 1.0,
            "retrieval_pass_rate": 1.0,
            "retrieval_hit_at_1": 1.0,
            "retrieval_hit_at_3": 1.0,
            "retrieval_hit_at_5": 1.0,
        }

    monkeypatch.setattr(policy_run, "evaluate", fake_evaluate)

    chunk_report = _evaluate_chunk(
        dataset_path="dataset.jsonl",
        provider="openai",
        model="gpt-4o-mini",
        chunk_index=2,
        chunk_offset=10,
        chunk_limit=10,
    )

    assert chunk_report["chunk_index"] == 2
    assert chunk_report["offset"] == 10
    assert chunk_report["limit"] == 10
    assert chunk_report["results"][0]["id"] == "case-10"


def test_parallel_chunk_reports_are_sorted_before_merge() -> None:
    report = _merge_reports(
        dataset_path="dataset.jsonl",
        provider="openai",
        model="gpt-4o-mini",
        chunk_size=10,
        chunk_reports=[
            {
                "chunk_index": 2,
                "dataset_size": 1,
                "results": [
                    {
                        "id": "p2",
                        "query_eval": {"passed": True},
                        "retrieval_eval": {"passed": True, "hit_at_1": 1, "hit_at_3": 1, "hit_at_5": 1},
                    }
                ],
            },
            {
                "chunk_index": 1,
                "dataset_size": 1,
                "results": [
                    {
                        "id": "p1",
                        "query_eval": {"passed": True},
                        "retrieval_eval": {"passed": True, "hit_at_1": 1, "hit_at_3": 1, "hit_at_5": 1},
                    }
                ],
            },
        ],
    )

    assert report["dataset_size"] == 2
    assert {row["id"] for row in report["results"]} == {"p1", "p2"}
