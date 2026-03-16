"""Discovery 평가 실행기 뼈대."""

from .dataset_loader import load_jsonl


def evaluate(dataset_path: str) -> dict:
    dataset = load_jsonl(dataset_path)
    return {
        "dataset_size": len(dataset),
        "status": "scaffold",
        "message": "Connect Discovery Subagent inference and retrieval scoring here.",
    }
