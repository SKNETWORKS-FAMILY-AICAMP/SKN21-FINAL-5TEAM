"""Policy RAG evaluator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from chatbot.src.graph.nodes.policy_rag_subagent import run_policy_rag_pipeline

from .dataset_loader import load_jsonl
from .metrics import (
    score_query_transformation,
    score_retrieval_by_doc_keys,
    score_retrieval_by_phrases,
)


def evaluate(
    dataset_path: str | Path,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    limit: int | None = None,
) -> dict[str, Any]:
    dataset = load_jsonl(dataset_path)
    if limit is not None:
        dataset = dataset[:limit]

    results: list[dict[str, Any]] = []

    for case in dataset:
        result = evaluate_case(case=case, provider=provider, model=model)
        results.append(result)

    total = len(results)
    query_pass_count = sum(1 for row in results if row["query_eval"]["passed"])
    retrieval_pass_count = sum(1 for row in results if row["retrieval_eval"]["passed"])
    retrieval_hit_at_1 = sum(row["retrieval_eval"].get("hit_at_1", 0) for row in results)
    retrieval_hit_at_3 = sum(row["retrieval_eval"].get("hit_at_3", 0) for row in results)
    retrieval_hit_at_5 = sum(row["retrieval_eval"].get("hit_at_5", 0) for row in results)

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
        "results": results,
    }


def evaluate_case(
    case: dict[str, Any],
    provider: str,
    model: str,
) -> dict[str, Any]:
    user_query = str(case["user_query"])
    expected_query = str(case.get("expected_query", ""))
    expected_phrases = list(case.get("expected_phrases", []))
    expected_doc_keys = list(case.get("expected_doc_keys", []))
    category = case.get("category")

    pipeline_result = run_policy_rag_pipeline(
        messages=[HumanMessage(content=user_query)],
        provider=provider,
        model=model,
    )

    transformed_query = pipeline_result["optimized_query"]
    retrieval_result = pipeline_result["retrieval_result"]
    documents = retrieval_result.get("documents", [])
    retrieval_error = retrieval_result.get("error")
    retrieval_items = retrieval_result.get("items", [])
    retrieved_doc_keys = [
        item.get("doc_key", "")
        for item in retrieval_items
        if item.get("doc_key")
    ]

    query_eval = score_query_transformation(
        expected_query=expected_query,
        expected_phrases=expected_phrases,
        transformed_query=transformed_query,
    )
    if expected_doc_keys:
        retrieval_eval = score_retrieval_by_doc_keys(
            expected_doc_keys=expected_doc_keys,
            retrieved_doc_keys=retrieved_doc_keys,
        )
    else:
        retrieval_eval = score_retrieval_by_phrases(
            documents=documents,
            expected_phrases=expected_phrases,
        )

    return {
        "id": case.get("id"),
        "category": category,
        "user_query": user_query,
        "expected_query": expected_query,
        "expected_doc_keys": expected_doc_keys,
        "transformed_query": transformed_query,
        "expected_phrases": expected_phrases,
        "query_eval": query_eval,
        "retrieval_eval": retrieval_eval,
        "retrieval_error": retrieval_error,
        "used_fallback": pipeline_result.get("used_fallback", False),
        "retrieved_doc_keys": retrieved_doc_keys,
        "retrieval_items": retrieval_items,
        "documents": documents,
        "answer": pipeline_result.get("answer_content", ""),
    }
