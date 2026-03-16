"""Policy RAG evaluation metrics."""

from __future__ import annotations

import re


_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w가-힣]+")


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = _NON_WORD_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def keyword_matches(text: str, expected_phrases: list[str]) -> list[str]:
    normalized_text = normalize_text(text)
    matches: list[str] = []

    for phrase in expected_phrases:
        normalized_phrase = normalize_text(phrase)
        if normalized_phrase and normalized_phrase in normalized_text:
            matches.append(phrase)

    return matches


def phrase_recall(text: str, expected_phrases: list[str]) -> float:
    if not expected_phrases:
        return 0.0
    return len(keyword_matches(text, expected_phrases)) / len(expected_phrases)


def token_recall(expected_query: str, transformed_query: str) -> float:
    expected_tokens = set(normalize_text(expected_query).split())
    actual_tokens = set(normalize_text(transformed_query).split())

    if not expected_tokens:
        return 0.0

    return len(expected_tokens & actual_tokens) / len(expected_tokens)


def score_query_transformation(
    expected_query: str,
    expected_phrases: list[str],
    transformed_query: str,
) -> dict:
    matched_keywords = keyword_matches(transformed_query, expected_phrases)
    keyword_recall = (
        len(matched_keywords) / len(expected_phrases) if expected_phrases else 0.0
    )
    expected_token_recall = token_recall(expected_query, transformed_query)
    passed = keyword_recall >= 0.5 or expected_token_recall >= 0.6

    return {
        "passed": passed,
        "matched_keywords": matched_keywords,
        "keyword_recall": round(keyword_recall, 4),
        "expected_token_recall": round(expected_token_recall, 4),
    }


def score_retrieval_by_phrases(documents: list[str], expected_phrases: list[str]) -> dict:
    joined_documents = "\n".join(documents)
    matched_keywords = keyword_matches(joined_documents, expected_phrases)
    recall = len(matched_keywords) / len(expected_phrases) if expected_phrases else 0.0
    passed = bool(documents) and recall >= 0.5

    return {
        "mode": "phrase",
        "passed": passed,
        "matched_keywords": matched_keywords,
        "keyword_recall": round(recall, 4),
        "document_count": len(documents),
    }


def hit_at_k(expected_doc_keys: list[str], retrieved_doc_keys: list[str], k: int) -> int:
    expected = set(expected_doc_keys)
    if not expected:
        return 0
    return int(any(doc_key in expected for doc_key in retrieved_doc_keys[:k]))


def reciprocal_rank(expected_doc_keys: list[str], retrieved_doc_keys: list[str]) -> float:
    expected = set(expected_doc_keys)
    if not expected:
        return 0.0

    for index, doc_key in enumerate(retrieved_doc_keys, start=1):
        if doc_key in expected:
            return 1.0 / index
    return 0.0


def score_retrieval_by_doc_keys(
    expected_doc_keys: list[str],
    retrieved_doc_keys: list[str],
) -> dict:
    expected = set(expected_doc_keys)
    matched_doc_keys = [doc_key for doc_key in retrieved_doc_keys if doc_key in expected]
    hit1 = hit_at_k(expected_doc_keys, retrieved_doc_keys, 1)
    hit3 = hit_at_k(expected_doc_keys, retrieved_doc_keys, 3)
    hit5 = hit_at_k(expected_doc_keys, retrieved_doc_keys, 5)

    return {
        "mode": "doc_key",
        "passed": bool(hit5),
        "matched_doc_keys": matched_doc_keys,
        "hit_at_1": hit1,
        "hit_at_3": hit3,
        "hit_at_5": hit5,
        "mrr": round(reciprocal_rank(expected_doc_keys, retrieved_doc_keys), 4),
        "document_count": len(retrieved_doc_keys),
    }
