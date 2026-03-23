"""Discovery 평가 실행기."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chatbot.src.graph.nodes.discovery_subagent import run_discovery_pipeline

from .dataset_loader import load_jsonl
from .metrics import normalize_product_id, score_grounding, score_retrieval


def _normalize_product_id_list(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, str):
        candidates = [item.strip() for item in raw_value.split(",")]
    elif isinstance(raw_value, (list, tuple, set)):
        candidates = list(raw_value)
    else:
        candidates = [raw_value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        product_id = normalize_product_id(item)
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        normalized.append(product_id)
    return normalized


def _collect_gold_product_ids(case: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    primary_ids = _normalize_product_id_list(case.get("expected_product_ids", []))

    alternate_ids: list[str] = []
    for field_name in ("acceptable_product_ids", "alternative_product_ids", "alternate_product_ids"):
        for product_id in _normalize_product_id_list(case.get(field_name, [])):
            if product_id not in primary_ids and product_id not in alternate_ids:
                alternate_ids.append(product_id)

    gold_ids = [*primary_ids, *alternate_ids]
    return primary_ids, alternate_ids, gold_ids


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
        try:
            result = evaluate_case(case=case, provider=provider, model=model)
        except Exception as exc:
            result = build_error_result(case=case, error=str(exc))
        results.append(result)

    total = len(results)
    retrieval_pass_count = sum(1 for row in results if row["retrieval_eval"]["passed"])
    grounding_pass_count = sum(1 for row in results if row["grounding_eval"]["passed"])
    retrieval_hit_at_1 = sum(row["retrieval_eval"].get("hit_at_1", 0) for row in results)
    retrieval_hit_at_3 = sum(row["retrieval_eval"].get("hit_at_3", 0) for row in results)
    retrieval_hit_at_5 = sum(row["retrieval_eval"].get("hit_at_5", 0) for row in results)
    avg_grounding_keyword_recall = sum(
        row["grounding_eval"].get("keyword_recall", 0.0) for row in results
    )

    return {
        "dataset_path": str(dataset_path),
        "provider": provider,
        "model": model,
        "dataset_size": total,
        "retrieval_pass_rate": round(retrieval_pass_count / total, 4) if total else 0.0,
        "retrieval_hit_at_1": round(retrieval_hit_at_1 / total, 4) if total else 0.0,
        "retrieval_hit_at_3": round(retrieval_hit_at_3 / total, 4) if total else 0.0,
        "retrieval_hit_at_5": round(retrieval_hit_at_5 / total, 4) if total else 0.0,
        "grounding_pass_rate": round(grounding_pass_count / total, 4) if total else 0.0,
        "grounding_keyword_recall": (
            round(avg_grounding_keyword_recall / total, 4) if total else 0.0
        ),
        "results": results,
    }


def evaluate_case(
    case: dict[str, Any],
    provider: str,
    model: str,
) -> dict[str, Any]:
    user_query = str(case.get("user_query", ""))
    image_url = case.get("image_url") or case.get("image_path")
    expected_product_ids, acceptable_product_ids, gold_product_ids = _collect_gold_product_ids(case)
    expected_keywords = list(case.get("expected_keywords", []))

    pipeline_result = run_discovery_pipeline(
        user_query=user_query,
        image_url=str(image_url) if image_url else None,
        provider=provider,
        model=model,
    )

    retrieved_products = list(pipeline_result.get("retrieved_products", []))
    predicted_product_ids = [
        normalize_product_id(product.get("id"))
        for product in retrieved_products
        if normalize_product_id(product.get("id"))
    ]
    answer_text = str(pipeline_result.get("answer_content", "") or "")

    retrieval_eval = score_retrieval(
        expected_ids=gold_product_ids,
        predicted_ids=predicted_product_ids,
    )
    grounding_eval = score_grounding(
        answer_text=answer_text,
        retrieved_products=retrieved_products,
        expected_keywords=expected_keywords,
    )

    return {
        "id": case.get("id"),
        "task": str(pipeline_result.get("task", "")),
        "user_query": user_query,
        "image_url": image_url,
        "expected_product_ids": expected_product_ids,
        "acceptable_product_ids": acceptable_product_ids,
        "gold_product_ids": gold_product_ids,
        "expected_keywords": expected_keywords,
        "retrieval_eval": retrieval_eval,
        "grounding_eval": grounding_eval,
        "retrieved_product_ids": predicted_product_ids,
        "retrieved_products": retrieved_products,
        "answer": answer_text,
        "ui_action_required": pipeline_result.get("ui_action_required"),
    }


def build_error_result(case: dict[str, Any], error: str) -> dict[str, Any]:
    expected_product_ids, acceptable_product_ids, gold_product_ids = _collect_gold_product_ids(case)
    return {
        "id": case.get("id"),
        "task": "ERROR",
        "user_query": str(case.get("user_query", "")),
        "image_url": case.get("image_url") or case.get("image_path"),
        "expected_product_ids": expected_product_ids,
        "acceptable_product_ids": acceptable_product_ids,
        "gold_product_ids": gold_product_ids,
        "expected_keywords": list(case.get("expected_keywords", [])),
        "retrieval_eval": {
            "passed": False,
            "matched_product_ids": [],
            "hit_at_1": 0,
            "hit_at_3": 0,
            "hit_at_5": 0,
            "mrr": 0.0,
            "retrieved_count": 0,
        },
        "grounding_eval": {
            "passed": False,
            "matched_keywords": [],
            "keyword_recall": 0.0,
        },
        "retrieved_product_ids": [],
        "retrieved_products": [],
        "answer": "",
        "ui_action_required": None,
        "error": error,
    }
