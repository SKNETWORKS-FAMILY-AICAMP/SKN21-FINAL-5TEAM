import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.indexing import (
    build_indexing_plan,
    chunk_faq_source,
    chunk_policy_source,
)
from chatbot.src.onboarding_v2.models.analysis import RagSourceRecord, RagSources
from chatbot.src.onboarding_v2.models.planning import RetrievalIndexPlan


def test_build_indexing_plan_uses_site_scoped_aliases():
    sources = RagSources(
        faq=[
            RagSourceRecord(
                path="scripts/faq_seed.json",
                kind="json_file",
                corpus="faq",
                reason="faq data",
            )
        ],
        discovery_image=[
            RagSourceRecord(
                path="scripts/product_crawling.py",
                kind="crawl_script",
                corpus="discovery_image",
                reason="remote image data",
                details={
                    "loader_candidates": ["public_url_fetch", "bucket_list_and_fetch"],
                },
            )
        ],
    )

    plan = build_indexing_plan(site="demo-shop", run_id="run-123", rag_sources=sources)

    assert isinstance(plan, RetrievalIndexPlan)
    assert plan.site_slug == "demo-shop"
    assert {item.collection_alias for item in plan.corpora} == {
        "site_demo-shop__faq",
        "site_demo-shop__discovery_image",
    }
    assert all(item.build_collection.endswith("__run_run-123") for item in plan.corpora)
    discovery_plan = next(item for item in plan.corpora if item.corpus == "discovery_image")
    assert discovery_plan.loader_strategy == "public_url_fetch"


def test_chunk_faq_source_emits_one_chunk_per_qa_pair(tmp_path: Path):
    source_path = tmp_path / "faq.json"
    source_path.write_text(
        '[{"question":"배송은 얼마나 걸리나요?","answer":"2일"},{"question":"환불은 언제 되나요?","answer":"3일"}]',
        encoding="utf-8",
    )

    chunks = chunk_faq_source(source_path)

    assert [chunk["question"] for chunk in chunks] == [
        "배송은 얼마나 걸리나요?",
        "환불은 언제 되나요?",
    ]


def test_chunk_policy_source_preserves_heading_blocks(tmp_path: Path):
    source_path = tmp_path / "policy.md"
    source_path.write_text(
        "# 환불 규정\n환불은 7일 이내 가능합니다.\n\n## 배송비\n반품 배송비는 고객 부담입니다.\n",
        encoding="utf-8",
    )

    chunks = chunk_policy_source(source_path)

    assert len(chunks) == 2
    assert chunks[0]["heading"] == "환불 규정"
    assert "7일 이내" in chunks[0]["text"]
    assert chunks[1]["heading"] == "배송비"
