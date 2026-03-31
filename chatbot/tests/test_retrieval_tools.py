from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatbot.src.tools import retrieval_tools


class _UnexpectedQueryClient:
    def __init__(self) -> None:
        self.query_calls = 0

    def query_points(self, **kwargs):  # pragma: no cover - should never be reached
        self.query_calls += 1
        raise AssertionError(f"query_points should not be called when collection is missing: {kwargs}")


def test_search_knowledge_base_skips_missing_site_collections(monkeypatch) -> None:
    client = _UnexpectedQueryClient()

    monkeypatch.setattr(retrieval_tools, "ensure_retrieval_models", lambda: None)
    monkeypatch.setattr(retrieval_tools, "embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    monkeypatch.setattr(retrieval_tools, "SPARSE_MODEL", None)
    monkeypatch.setattr(retrieval_tools, "RANKER", None)
    monkeypatch.setattr(retrieval_tools, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(retrieval_tools, "collection_exists", lambda collection_name, client=None: False)

    result = retrieval_tools.search_knowledge_base.invoke(
        {
            "query": "환불 정책이 어떻게 되나요?",
            "category": "취소/반품/교환",
            "site_id": "site-c",
        }
    )

    assert result == {"documents": [], "message": "관련된 정보를 찾을 수 없습니다."}
    assert client.query_calls == 0
