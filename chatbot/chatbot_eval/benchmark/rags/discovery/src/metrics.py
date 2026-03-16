"""Discovery 평가 지표 뼈대."""


def hit_at_k(expected_ids: list[str], predicted_ids: list[str], k: int = 5) -> int:
    expected = set(expected_ids)
    top_k = set(predicted_ids[:k])
    return int(bool(expected & top_k))


def grounding_placeholder() -> dict:
    return {
        "status": "todo",
        "message": "Grounding metric will be added after response format is fixed.",
    }
