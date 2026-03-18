"""Discovery 평가 지표."""

from __future__ import annotations

import re
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w가-힣]+")


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = _NON_WORD_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def normalize_product_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def keyword_matches(text: str, expected_keywords: list[str]) -> list[str]:
    normalized_text = normalize_text(text)
    matches: list[str] = []

    for keyword in expected_keywords:
        normalized_keyword = normalize_text(keyword)
        if normalized_keyword and normalized_keyword in normalized_text:
            matches.append(keyword)

    return matches


def hit_at_k(expected_ids: list[str], predicted_ids: list[str], k: int = 5) -> int:
    expected = {normalize_product_id(item) for item in expected_ids if normalize_product_id(item)}
    top_k = {
        normalize_product_id(item)
        for item in predicted_ids[:k]
        if normalize_product_id(item)
    }
    return int(bool(expected & top_k))


def reciprocal_rank(expected_ids: list[str], predicted_ids: list[str]) -> float:
    expected = {normalize_product_id(item) for item in expected_ids if normalize_product_id(item)}
    if not expected:
        return 0.0

    for index, item in enumerate(predicted_ids, start=1):
        if normalize_product_id(item) in expected:
            return 1.0 / index
    return 0.0


def score_retrieval(expected_ids: list[str], predicted_ids: list[str]) -> dict[str, Any]:
    normalized_expected = [
        normalize_product_id(item) for item in expected_ids if normalize_product_id(item)
    ]
    normalized_predicted = [
        normalize_product_id(item) for item in predicted_ids if normalize_product_id(item)
    ]
    expected = set(normalized_expected)
    matched_ids = [item for item in normalized_predicted if item in expected]

    hit1 = hit_at_k(normalized_expected, normalized_predicted, 1)
    hit3 = hit_at_k(normalized_expected, normalized_predicted, 3)
    hit5 = hit_at_k(normalized_expected, normalized_predicted, 5)

    return {
        "passed": bool(hit5),
        "matched_product_ids": matched_ids,
        "hit_at_1": hit1,
        "hit_at_3": hit3,
        "hit_at_5": hit5,
        "mrr": round(reciprocal_rank(normalized_expected, normalized_predicted), 4),
        "retrieved_count": len(normalized_predicted),
    }


def _product_text(products: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for product in products:
        chunks.append(
            " ".join(
                str(product.get(field) or "")
                for field in ("name", "category", "color", "season")
            ).strip()
        )
    return "\n".join(chunk for chunk in chunks if chunk)


def score_grounding(
    answer_text: str,
    retrieved_products: list[dict[str, Any]],
    expected_keywords: list[str],
) -> dict[str, Any]:
    if not expected_keywords:
        return {
            "passed": True,
            "matched_keywords": [],
            "keyword_recall": 1.0,
        }

    combined_text = "\n".join(
        chunk for chunk in [answer_text or "", _product_text(retrieved_products)] if chunk
    )
    matched_keywords = keyword_matches(combined_text, expected_keywords)
    recall = len(matched_keywords) / len(expected_keywords)

    return {
        "passed": recall >= 0.5,
        "matched_keywords": matched_keywords,
        "keyword_recall": round(recall, 4),
    }
