import os
import sys
import threading
import time
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from qdrant_client.http import models
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.indexing import (
    HostExportContext,
    build_indexing_plan,
    chunk_faq_source,
    chunk_policy_source,
    execute_indexing_plan,
)
from chatbot.src.onboarding_v2.indexing.coordinator import (
    _IndexingDeps,
    _SharedHostRuntime,
    _embed_image_bytes_batch,
    _fetch_rows_from_host_python,
)
from chatbot.src.onboarding_v2.models.analysis import RagSourceRecord, RagSources
from chatbot.src.onboarding_v2.models.planning import RagCorpusPlan, RetrievalIndexPlan


class _FakeAliasInfo:
    def __init__(self, alias_name: str, collection_name: str) -> None:
        self.alias_name = alias_name
        self.collection_name = collection_name


class _FakeAliasResponse:
    def __init__(self, aliases: list[_FakeAliasInfo]) -> None:
        self.aliases = aliases


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, object]] = {}
        self.upserts: list[tuple[str, list[models.PointStruct]]] = []
        self.aliases: dict[str, str] = {}
        self.alias_updates: list[list[object]] = []
        self.payload_indexes: list[tuple[str, str, object]] = []

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name: str, **kwargs) -> None:
        self.collections[collection_name] = dict(kwargs)

    def delete_collection(self, collection_name: str) -> None:
        self.collections.pop(collection_name, None)

    def create_payload_index(self, collection_name: str, field_name: str, field_schema: object) -> None:
        self.payload_indexes.append((collection_name, field_name, field_schema))

    def upsert(self, collection_name: str, points: list[models.PointStruct]) -> None:
        self.upserts.append((collection_name, list(points)))

    def update_collection_aliases(self, change_aliases_operations: list[object], timeout: int | None = None, **kwargs) -> bool:
        del timeout, kwargs
        self.alias_updates.append(list(change_aliases_operations))
        for operation in change_aliases_operations:
            if isinstance(operation, models.DeleteAliasOperation):
                self.aliases.pop(operation.delete_alias.alias_name, None)
            elif isinstance(operation, models.CreateAliasOperation):
                self.aliases[operation.create_alias.alias_name] = operation.create_alias.collection_name
        return True

    def get_aliases(self) -> _FakeAliasResponse:
        return _FakeAliasResponse(
            [
                _FakeAliasInfo(alias_name=alias_name, collection_name=collection_name)
                for alias_name, collection_name in self.aliases.items()
            ]
        )


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
                    "image_field": "image_url",
                    "loader_candidates": ["public_url_fetch", "bucket_list_and_fetch"],
                },
            )
        ],
    )

    plan = build_indexing_plan(
        site="demo-shop",
        run_id="run-123",
        rag_sources=sources,
        product_search_endpoint="/api/products",
    )

    assert isinstance(plan, RetrievalIndexPlan)
    assert plan.site_slug == "demo-shop"
    assert {item.collection_alias for item in plan.corpora} == {
        "site_demo-shop__faq",
        "site_demo-shop__discovery_image",
    }
    assert all(item.build_collection.endswith("__run_run-123") for item in plan.corpora)
    discovery_plan = next(item for item in plan.corpora if item.corpus == "discovery_image")
    assert discovery_plan.loader_strategy == "public_url_fetch"
    assert discovery_plan.row_source_strategy == "host_api_fetch"
    assert discovery_plan.row_source_endpoint == "/api/products"
    assert discovery_plan.row_id_field == "product_id"
    assert discovery_plan.row_image_url_field == "image_url"


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


def test_execute_indexing_plan_upserts_dense_and_sparse_text_corpora(tmp_path: Path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(
        '[{"question":"배송은 얼마나 걸리나요?","answer":"2일"}]',
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.md"
    policy_path.write_text("# 환불 규정\n환불은 7일 이내 가능합니다.\n", encoding="utf-8")

    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="faq",
                chunking_strategy="qa_level",
                collection_alias="site_demo-shop__faq",
                build_collection="site_demo-shop__faq__run_demo",
                sources=["faq.json"],
                smoke_queries=["배송"],
                minimum_expected_documents=1,
                loader_strategy="faq_source_scan",
            ),
            RagCorpusPlan(
                corpus="policy",
                chunking_strategy="heading_sections",
                collection_alias="site_demo-shop__policy",
                build_collection="site_demo-shop__policy__run_demo",
                sources=["policy.md"],
                smoke_queries=["환불"],
                minimum_expected_documents=1,
                loader_strategy="policy_source_scan",
            ),
        ],
    )
    fake_client = _FakeQdrantClient()

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        qdrant_client=fake_client,
        dense_embedder=lambda texts: [[float(index + 1), float(index + 2)] for index, _ in enumerate(texts)],
        sparse_embedder=lambda texts: [
            models.SparseVector(indices=[0, 1], values=[1.0, float(len(text))])
            for text in texts
        ],
    )

    assert result["corpora"]["faq"]["status"] == "completed"
    assert result["corpora"]["policy"]["status"] == "completed"
    assert result["corpora"]["faq"]["alias_swapped"] is True
    assert result["corpora"]["policy"]["alias_swapped"] is True
    assert fake_client.aliases == {
        "site_demo-shop__faq": "site_demo-shop__faq__run_demo",
        "site_demo-shop__policy": "site_demo-shop__policy__run_demo",
    }
    assert sorted(collection for collection, _ in fake_client.upserts) == [
        "site_demo-shop__faq__run_demo",
        "site_demo-shop__policy__run_demo",
    ]
    for _collection, points in fake_client.upserts:
        for point in points:
            UUID(str(point.id))


def test_execute_indexing_plan_discovery_image_uses_host_api_rows_and_allows_partial_success(tmp_path: Path):
    source_path = tmp_path / "product_crawling.py"
    source_path.write_text("IMAGE_URL = 'https://cdn.example.com/a.jpg'\n", encoding="utf-8")
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="entity_level",
                collection_alias="site_demo-shop__discovery_image",
                build_collection="site_demo-shop__discovery_image__run_demo",
                sources=["product_crawling.py"],
                smoke_queries=["검은색 자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_api_fetch",
                row_source_endpoint="/api/products",
                row_id_field="product_id",
                row_image_url_field="image_url",
                pagination_strategy={
                    "type": "page_number",
                    "page_param": "page",
                    "page_size_param": "page_size",
                    "page_size": 100,
                    "stop_on": "empty_or_repeated_ids",
                },
            )
        ],
    )
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()
    fake_client = _FakeQdrantClient()

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=fake_client,
        row_fetcher=lambda **kwargs: [
            {"product_id": 101, "image_url": "https://cdn.example.com/ok.jpg", "name": "jacket"},
            {"product_id": 102, "image_url": "https://cdn.example.com/fail.jpg", "name": "shirt"},
        ],
        image_fetcher=lambda url: b"ok" if url.endswith("ok.jpg") else (_ for _ in ()).throw(RuntimeError("download failed")),
        image_embedder=lambda payloads: [[0.1, 0.2] for _ in payloads],
        sparse_embedder=lambda texts: [
            models.SparseVector(indices=[0, 1], values=[1.0, float(len(texts[0]))])
            for _ in texts
        ],
    )

    discovery = result["corpora"]["discovery_image"]
    assert discovery["status"] == "completed"
    assert discovery["documents_indexed"] == 1
    assert discovery["alias_swapped"] is True
    assert "image_fetch_failed" in discovery["warning_codes"]
    assert fake_client.aliases["site_demo-shop__discovery_image"] == "site_demo-shop__discovery_image__run_demo"
    point = fake_client.upserts[0][1][0]
    assert "text-sparse" in dict(point.vector)
    assert point.payload["retrieval_text"]
    assert "jacket" in point.payload["retrieval_text"].lower()
    UUID(str(fake_client.upserts[0][1][0].id))


def test_execute_indexing_plan_marks_discovery_image_without_rows_as_skipped(tmp_path: Path):
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="product_image_rows",
                collection_alias="site_demo-shop__discovery_image",
                build_collection="site_demo-shop__discovery_image__run_demo",
                sources=["product_crawling.py"],
                smoke_queries=["검은색 자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_api_fetch",
                row_source_endpoint="/api/products",
                row_id_field="product_id",
                row_image_url_field="image_url",
                pagination_strategy={
                    "type": "page_number",
                    "page_param": "page",
                    "page_size_param": "page_size",
                    "page_size": 100,
                    "stop_on": "empty_or_repeated_ids",
                },
            )
        ],
    )
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=_FakeQdrantClient(),
        row_fetcher=lambda **kwargs: [],
    )

    discovery = result["corpora"]["discovery_image"]
    assert discovery["status"] == "skipped"
    assert discovery["enabled"] is False
    assert discovery["documents_indexed"] == 0
    assert discovery["reason"] == "no_product_rows"
    assert "no_product_rows" in discovery["warning_codes"]
    assert discovery["alias_swapped"] is False


def test_execute_indexing_plan_preseeds_discovery_image_when_raw_product_rows_are_empty(
    tmp_path: Path,
    monkeypatch,
):
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="product_image_rows",
                collection_alias="site_demo-shop__discovery_image",
                build_collection="site_demo-shop__discovery_image__run_demo",
                sources=["product_crawling.py"],
                smoke_queries=["검은색 자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_api_fetch",
                row_source_endpoint="/api/products",
                row_id_field="product_id",
                row_image_url_field="image_url",
            )
        ],
    )
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()
    fake_client = _FakeQdrantClient()
    calls = {"row_fetch": 0, "seed": 0}

    def _fake_row_fetcher(**kwargs):
        del kwargs
        calls["row_fetch"] += 1
        if calls["row_fetch"] == 1:
            return []
        return [{"product_id": 101, "image_url": "https://cdn.example.com/ok.jpg", "name": "jacket"}]

    def _fake_seed_runner(**kwargs):
        del kwargs
        calls["seed"] += 1
        return {
            "preseed_attempted": True,
            "preseed_outcome": "seeded",
            "preseed_reason": "no_product_rows",
        }

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator._run_discovery_image_seed_script",
        _fake_seed_runner,
    )

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=fake_client,
        row_fetcher=_fake_row_fetcher,
        image_fetcher=lambda url: b"ok",
        image_embedder=lambda payloads: [[0.1, 0.2] for _ in payloads],
    )

    discovery = result["corpora"]["discovery_image"]
    assert discovery["status"] == "completed"
    assert discovery["documents_indexed"] == 1
    assert discovery["preseed_attempted"] is True
    assert discovery["preseed_outcome"] == "seeded"
    assert discovery["preseed_reason"] == "no_product_rows"
    assert calls == {"row_fetch": 2, "seed": 1}


def test_execute_indexing_plan_does_not_seed_when_raw_products_exist_but_images_are_missing(
    tmp_path: Path,
    monkeypatch,
):
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="product_image_rows",
                collection_alias="site_demo-shop__discovery_image",
                build_collection="site_demo-shop__discovery_image__run_demo",
                sources=["product_crawling.py"],
                smoke_queries=["검은색 자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_api_fetch",
                row_source_endpoint="/api/products",
                row_id_field="product_id",
                row_image_url_field="image_url",
            )
        ],
    )
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()
    seed_calls = {"count": 0}

    def _fake_seed_runner(**kwargs):
        del kwargs
        seed_calls["count"] += 1
        return {
            "preseed_attempted": True,
            "preseed_outcome": "seeded",
            "preseed_reason": "no_product_rows",
        }

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator._run_discovery_image_seed_script",
        _fake_seed_runner,
    )

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=_FakeQdrantClient(),
        row_fetcher=lambda **kwargs: [{"product_id": 101, "name": "jacket"}],
    )

    discovery = result["corpora"]["discovery_image"]
    assert discovery["status"] == "skipped"
    assert discovery["reason"] == "no_indexable_image_rows"
    assert "no_indexable_image_rows" in discovery["warning_codes"]
    assert discovery["preseed_attempted"] is False
    assert discovery["preseed_outcome"] == "raw_product_rows_present"
    assert seed_calls["count"] == 0


def test_execute_indexing_plan_batches_discovery_image_upserts_and_reports_partial_progress(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("ONBOARDING_DISCOVERY_IMAGE_UPSERT_BATCH_SIZE", "2")
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="product_image_rows",
                collection_alias="site_demo-shop__discovery_image",
                build_collection="site_demo-shop__discovery_image__run_demo",
                sources=["product_crawling.py"],
                smoke_queries=["검은색 자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_api_fetch",
                row_source_endpoint="/api/products",
                row_id_field="product_id",
                row_image_url_field="image_url",
            )
        ],
    )
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()

    class _FlakyClient(_FakeQdrantClient):
        def upsert(self, collection_name: str, points: list[models.PointStruct]) -> None:
            super().upsert(collection_name, points)
            if len(self.upserts) >= 2:
                raise TimeoutError("The write operation timed out")

    fake_client = _FlakyClient()
    rows = [
        {"product_id": 101, "image_url": "https://cdn.example.com/1.jpg", "name": "jacket-1"},
        {"product_id": 102, "image_url": "https://cdn.example.com/2.jpg", "name": "jacket-2"},
        {"product_id": 103, "image_url": "https://cdn.example.com/3.jpg", "name": "jacket-3"},
    ]

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=fake_client,
        row_fetcher=lambda **kwargs: rows,
        image_fetcher=lambda url: b"ok",
        image_embedder=lambda payloads: [[0.1, 0.2] for _ in payloads],
    )

    discovery = result["corpora"]["discovery_image"]
    assert discovery["status"] == "failed"
    assert discovery["reason"] == "worker_exception"
    assert discovery["documents_prepared"] == 3
    assert discovery["batches_attempted"] == 2
    assert discovery["batches_completed"] == 1
    assert discovery["last_successful_product_id"] == 102
    assert discovery["alias_swapped"] is False


def test_execute_indexing_plan_can_ingest_faq_rows_via_host_python_fetch(tmp_path: Path):
    backend_model = tmp_path / "backend" / "models"
    backend_model.mkdir(parents=True)
    (backend_model / "faq.py").write_text("def get_all_faq():\n    return []\n", encoding="utf-8")

    plan = RetrievalIndexPlan(
        site_id="bilyeo",
        site_slug="bilyeo",
        corpora=[
            RagCorpusPlan(
                corpus="faq",
                chunking_strategy="qa_level",
                collection_alias="site_bilyeo__faq",
                build_collection="site_bilyeo__faq__run_demo",
                sources=["backend/models/faq.py"],
                smoke_queries=["배송"],
                minimum_expected_documents=1,
                loader_strategy="faq_source_scan",
                row_source_strategy="host_python_fetch",
                row_source_module="models.faq",
                row_source_callable="get_all_faq",
            )
        ],
    )
    fake_client = _FakeQdrantClient()
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()
    captured: dict[str, object] = {}

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=fake_client,
        dense_embedder=lambda texts: [[float(index + 1), float(index + 2)] for index, _ in enumerate(texts)],
        sparse_embedder=lambda texts: [
            models.SparseVector(indices=[0, 1], values=[1.0, float(len(text))])
            for text in texts
        ],
        row_fetcher=lambda **kwargs: captured.update(kwargs) or [
            {"faq_id": 1, "category": "배송", "question": "배송은 얼마나 걸리나요?", "answer": "2일"},
            {"faq_id": 2, "category": "환불", "question": "환불은 언제 되나요?", "answer": "3일"},
        ],
    )

    faq = result["corpora"]["faq"]
    assert faq["status"] == "completed"
    assert faq["documents_indexed"] == 2
    assert faq["alias_swapped"] is True
    assert captured["corpus_plan"].row_source_module == "models.faq"
    assert captured["corpus_plan"].row_source_callable == "get_all_faq"
    for point in fake_client.upserts[0][1]:
        UUID(str(point.id))


def test_execute_indexing_plan_emits_live_worker_progress_events(tmp_path: Path):
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="faq",
                chunking_strategy="qa_level",
                collection_alias="site_demo-shop__faq",
                build_collection="site_demo-shop__faq__run_demo",
                sources=["faq.json"],
                smoke_queries=["배송"],
                minimum_expected_documents=1,
                loader_strategy="faq_source_scan",
            )
        ],
    )
    events: list[dict[str, object]] = []

    def _slow_worker(**kwargs):
        del kwargs
        time.sleep(0.12)
        return {
            "status": "completed",
            "enabled": True,
            "documents_indexed": 1,
            "collection_alias": "site_demo-shop__faq",
            "build_collection": "site_demo-shop__faq__run_demo",
            "loader_strategy": "faq_source_scan",
            "warning_codes": [],
            "alias_swapped": True,
            "smoke_passed": True,
        }

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        worker=_slow_worker,
        event_callback=events.append,
        heartbeat_interval_s=0.05,
    )

    assert result["corpora"]["faq"]["status"] == "completed"
    event_types = [str(event["event_type"]) for event in events]
    assert "retrieval_worker_started" in event_types
    assert "retrieval_worker_progress" in event_types
    assert "retrieval_worker_completed" in event_types


def test_execute_indexing_plan_coerces_late_worker_completion_to_aborted_when_cancelled(
    tmp_path: Path,
):
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="policy",
                chunking_strategy="heading_sections",
                collection_alias="site_demo-shop__policy",
                build_collection="site_demo-shop__policy__run_demo",
                sources=["policy.md"],
                smoke_queries=["환불"],
                minimum_expected_documents=1,
                loader_strategy="policy_source_scan",
            )
        ],
    )
    cancel_event = threading.Event()
    worker_started = threading.Event()
    events: list[dict[str, object]] = []

    def _slow_worker(**kwargs):
        del kwargs
        worker_started.set()
        while not cancel_event.is_set():
            time.sleep(0.01)
        return {
            "status": "completed",
            "enabled": True,
            "documents_indexed": 7,
            "collection_alias": "site_demo-shop__policy",
            "build_collection": "site_demo-shop__policy__run_demo",
            "loader_strategy": "policy_source_scan",
            "warning_codes": [],
            "alias_swapped": True,
            "smoke_passed": True,
        }

    def _cancel_after_start() -> None:
        worker_started.wait(timeout=1)
        cancel_event.set()

    canceller = threading.Thread(target=_cancel_after_start, daemon=True)
    canceller.start()

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        worker=_slow_worker,
        cancel_event=cancel_event,
        event_callback=events.append,
        heartbeat_interval_s=0.05,
    )

    canceller.join(timeout=1)
    policy = result["corpora"]["policy"]
    assert policy["status"] == "aborted_by_host_failure"
    assert policy["alias_swapped"] is False
    event_types = [str(event["event_type"]) for event in events]
    assert "retrieval_worker_cancelled" in event_types
    assert "retrieval_worker_completed" not in event_types


def test_execute_indexing_plan_aborts_text_corpus_before_qdrant_commit_when_cancelled(
    tmp_path: Path,
):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(
        '[{"question":"배송은 얼마나 걸리나요?","answer":"2일"}]',
        encoding="utf-8",
    )
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="faq",
                chunking_strategy="qa_level",
                collection_alias="site_demo-shop__faq",
                build_collection="site_demo-shop__faq__run_demo",
                sources=["faq.json"],
                smoke_queries=["배송"],
                minimum_expected_documents=1,
                loader_strategy="faq_source_scan",
            )
        ],
    )
    fake_client = _FakeQdrantClient()
    cancel_event = threading.Event()
    embed_started = threading.Event()

    def _dense_embedder(texts):
        del texts
        embed_started.set()
        time.sleep(0.05)
        return [[1.0, 2.0]]

    def _cancel_after_embed_start() -> None:
        embed_started.wait(timeout=1)
        cancel_event.set()

    canceller = threading.Thread(target=_cancel_after_embed_start, daemon=True)
    canceller.start()

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        cancel_event=cancel_event,
        qdrant_client=fake_client,
        dense_embedder=_dense_embedder,
        sparse_embedder=lambda texts: [
            models.SparseVector(indices=[0, 1], values=[1.0, float(len(text))])
            for text in texts
        ],
    )

    canceller.join(timeout=1)
    faq = result["corpora"]["faq"]
    assert faq["status"] == "aborted_by_host_failure"
    assert fake_client.upserts == []
    assert fake_client.aliases == {}


def test_execute_indexing_plan_emits_waiting_on_export_before_host_backed_worker_starts(
    tmp_path: Path,
    monkeypatch,
):
    source_path = tmp_path / "product_crawling.py"
    source_path.write_text("IMAGE_URL = 'https://cdn.example.com/a.jpg'\n", encoding="utf-8")
    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="entity_level",
                collection_alias="site_demo-shop__discovery_image",
                build_collection="site_demo-shop__discovery_image__run_demo",
                sources=["product_crawling.py"],
                smoke_queries=["검은색 자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_api_fetch",
                row_source_endpoint="/api/products",
                row_id_field="product_id",
                row_image_url_field="image_url",
                pagination_strategy={
                    "type": "page_number",
                    "page_param": "page",
                    "page_size_param": "page_size",
                    "page_size": 100,
                    "stop_on": "empty_or_repeated_ids",
                },
            )
        ],
    )
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.integration_plan = object()
    fake_client = _FakeQdrantClient()
    events: list[dict[str, object]] = []

    class _Prep:
        passed = True
        failure_summary = None
        python_executable = sys.executable

    class _RuntimePlan:
        listen_port = 8129

    class _RuntimeState:
        passed = True
        failure_summary = None

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.prepare_backend_runtime",
        lambda **kwargs: _Prep(),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.build_backend_runtime_plan",
        lambda **kwargs: _RuntimePlan(),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.launch_backend_runtime",
        lambda *args, **kwargs: _RuntimeState(),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.stop_backend_runtime",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator._paginate_product_rows",
        lambda **kwargs: [
            {"product_id": 101, "resolved_image_url": "https://cdn.example.com/ok.jpg", "name": "jacket"}
        ],
    )

    def _release_export() -> None:
        time.sleep(0.12)
        host_context.export_ready.set()

    release_thread = threading.Thread(target=_release_export, daemon=True)
    release_thread.start()

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=fake_client,
        event_callback=events.append,
        heartbeat_interval_s=0.05,
        image_fetcher=lambda url: b"ok",
        image_embedder=lambda payloads: [[0.1, 0.2] for _ in payloads],
    )

    release_thread.join(timeout=1)
    assert result["corpora"]["discovery_image"]["status"] == "completed"
    event_types = [str(event["event_type"]) for event in events]
    assert "retrieval_worker_waiting_on_export" in event_types
    assert "retrieval_worker_started" in event_types
    assert "retrieval_worker_completed" in event_types
    waiting_index = event_types.index("retrieval_worker_waiting_on_export")
    started_index = event_types.index("retrieval_worker_started")
    assert waiting_index < started_index


def test_execute_indexing_plan_reuses_shared_host_runtime_for_host_backed_corpora(
    tmp_path: Path, monkeypatch
):
    backend_model = tmp_path / "backend" / "models"
    backend_model.mkdir(parents=True)
    (backend_model / "faq.py").write_text("def get_all_faq():\n    return []\n", encoding="utf-8")

    plan = RetrievalIndexPlan(
        site_id="bilyeo",
        site_slug="bilyeo",
        corpora=[
            RagCorpusPlan(
                corpus="faq",
                chunking_strategy="qa_level",
                collection_alias="site_bilyeo__faq",
                build_collection="site_bilyeo__faq__run_demo",
                sources=["backend/models/faq.py"],
                smoke_queries=["배송"],
                minimum_expected_documents=1,
                loader_strategy="faq_source_scan",
                row_source_strategy="host_python_fetch",
                row_source_module="models.faq",
                row_source_callable="get_all_faq",
            ),
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="entity_level",
                collection_alias="site_bilyeo__discovery_image",
                build_collection="site_bilyeo__discovery_image__run_demo",
                sources=["backend/routes/product.py"],
                smoke_queries=["검은색 자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_api_fetch",
                row_source_endpoint="/api/products",
                row_id_field="product_id",
                row_image_url_field="image_url",
                pagination_strategy={
                    "type": "page_number",
                    "page_param": "page",
                    "page_size_param": "page_size",
                    "page_size": 100,
                    "stop_on": "empty_or_repeated_ids",
                },
            ),
        ],
    )
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.integration_plan = object()
    host_context.export_ready.set()
    fake_client = _FakeQdrantClient()
    calls = {"prepare": 0, "build": 0, "launch": 0, "stop": 0}

    class _Prep:
        passed = True
        failure_summary = None
        python_executable = sys.executable

    class _RuntimePlan:
        listen_port = 8129

    class _RuntimeState:
        passed = True
        failure_summary = None

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.prepare_backend_runtime",
        lambda **kwargs: calls.__setitem__("prepare", calls["prepare"] + 1) or _Prep(),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.build_backend_runtime_plan",
        lambda **kwargs: calls.__setitem__("build", calls["build"] + 1) or _RuntimePlan(),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.launch_backend_runtime",
        lambda *args, **kwargs: calls.__setitem__("launch", calls["launch"] + 1) or _RuntimeState(),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.stop_backend_runtime",
        lambda *args, **kwargs: calls.__setitem__("stop", calls["stop"] + 1) or None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator._paginate_product_rows",
        lambda **kwargs: [
            {"product_id": 101, "resolved_image_url": "https://cdn.example.com/ok.jpg", "name": "jacket"}
        ],
    )

    class _CompletedProcess:
        returncode = 0
        stdout = (
            '[{"faq_id": 1, "category": "배송", "question": "배송은 얼마나 걸리나요?", "answer": "2일"}]'
        )
        stderr = ""

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.subprocess.run",
        lambda *args, **kwargs: _CompletedProcess(),
    )

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=fake_client,
        dense_embedder=lambda texts: [[float(index + 1), float(index + 2)] for index, _ in enumerate(texts)],
        sparse_embedder=lambda texts: [
            models.SparseVector(indices=[0, 1], values=[1.0, float(len(text))])
            for text in texts
        ],
        image_embedder=lambda payloads: [[0.1, 0.2] for _ in payloads],
        image_fetcher=lambda url: b"ok",
    )

    assert result["corpora"]["faq"]["status"] == "completed"
    assert result["corpora"]["discovery_image"]["status"] == "completed"
    assert calls == {"prepare": 1, "build": 1, "launch": 1, "stop": 1}


def test_execute_indexing_plan_marks_shared_host_runtime_failures_explicitly(tmp_path: Path, monkeypatch):
    backend_model = tmp_path / "backend" / "models"
    backend_model.mkdir(parents=True)
    (backend_model / "faq.py").write_text("def get_all_faq():\n    return []\n", encoding="utf-8")

    plan = RetrievalIndexPlan(
        site_id="bilyeo",
        site_slug="bilyeo",
        corpora=[
            RagCorpusPlan(
                corpus="faq",
                chunking_strategy="qa_level",
                collection_alias="site_bilyeo__faq",
                build_collection="site_bilyeo__faq__run_demo",
                sources=["backend/models/faq.py"],
                smoke_queries=["배송"],
                minimum_expected_documents=1,
                loader_strategy="faq_source_scan",
                row_source_strategy="host_python_fetch",
                row_source_module="models.faq",
                row_source_callable="get_all_faq",
            ),
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="entity_level",
                collection_alias="site_bilyeo__discovery_image",
                build_collection="site_bilyeo__discovery_image__run_demo",
                sources=["backend/routes/product.py"],
                smoke_queries=["검은색 자켓"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_api_fetch",
                row_source_endpoint="/api/products",
                row_id_field="product_id",
                row_image_url_field="image_url",
            ),
        ],
    )
    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.integration_plan = object()
    host_context.export_ready.set()

    class _Prep:
        passed = False
        failure_summary = "oracle unavailable"
        python_executable = sys.executable

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.prepare_backend_runtime",
        lambda **kwargs: _Prep(),
    )

    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=_FakeQdrantClient(),
    )

    assert result["corpora"]["faq"]["status"] == "failed"
    assert "host_runtime_prep_failed" in result["corpora"]["faq"]["warning_codes"]
    assert result["corpora"]["discovery_image"]["status"] == "failed"
    assert "host_runtime_prep_failed" in result["corpora"]["discovery_image"]["warning_codes"]


def test_fetch_rows_from_host_python_serializes_lob_like_values(tmp_path: Path, monkeypatch):
    backend_model = tmp_path / "backend" / "models"
    backend_model.mkdir(parents=True)
    (backend_model / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "backend" / "oracledb.py").write_text(
        "class _Defaults:\n"
        "    fetch_lobs = True\n\n"
        "defaults = _Defaults()\n",
        encoding="utf-8",
    )
    (backend_model / "faq.py").write_text(
        "import oracledb\n\n"
        "class FakeLob:\n"
        "    def __init__(self, value):\n"
        "        self._value = value\n"
        "    def read(self):\n"
        "        return self._value\n\n"
        "def get_all_faq():\n"
        "    answer = '2일' if getattr(oracledb.defaults, 'fetch_lobs', None) is False else FakeLob('2일')\n"
        "    return [{\"faq_id\": 1, \"category\": \"배송\", \"question\": \"배송은 얼마나 걸리나요?\", \"answer\": answer}] \n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.prepare_backend_runtime",
        lambda **kwargs: type(
            "PrepResult",
            (),
            {
                "passed": True,
                "failure_summary": None,
                "python_executable": sys.executable,
            },
        )(),
    )

    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()

    rows = _fetch_rows_from_host_python(
        corpus_plan=RagCorpusPlan(
            corpus="faq",
            chunking_strategy="qa_level",
            collection_alias="site_bilyeo__faq",
            build_collection="site_bilyeo__faq__run_demo",
            sources=["backend/models/faq.py"],
            smoke_queries=["배송"],
            minimum_expected_documents=1,
            loader_strategy="faq_source_scan",
            row_source_strategy="host_python_fetch",
            row_source_module="models.faq",
            row_source_callable="get_all_faq",
        ),
        host_context=host_context,
        cancel_event=None,
        deps=_IndexingDeps(
            shared_host_runtime=_SharedHostRuntime(host_context=host_context, cancel_event=None)
        ),
    )

    assert rows == [
        {
            "faq_id": 1,
            "category": "배송",
            "question": "배송은 얼마나 걸리나요?",
            "answer": "2일",
        }
    ]


def test_execute_indexing_plan_discovery_image_can_ingest_via_host_python_fetch(tmp_path: Path, monkeypatch):
    backend_model = tmp_path / "backend" / "models"
    backend_model.mkdir(parents=True)
    (backend_model / "__init__.py").write_text("", encoding="utf-8")
    (backend_model / "product.py").write_text(
        "def get_all_products(category=None, search=None):\n"
        "    return [{\"product_id\": 1, \"image_url\": \"https://cdn.example.com/item.jpg\", \"name\": \"텐트\", "
        "\"product_info\": {\"ingredients\": \"판테놀\", \"review\": \"촉촉해요\"}}]\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.prepare_backend_runtime",
        lambda **kwargs: type(
            "PrepResult",
            (),
            {
                "passed": True,
                "failure_summary": None,
                "python_executable": sys.executable,
                "seed_source_path": None,
            },
        )(),
    )

    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()

    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="image_level",
                collection_alias="site_demo_shop__discovery_image",
                build_collection="site_demo_shop__discovery_image__run_demo",
                sources=["backend/models/product.py"],
                smoke_queries=["텐트"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_python_fetch",
                row_source_module="models.product",
                row_source_callable="get_all_products",
                row_id_field="product_id",
                row_image_url_field="image_url",
            )
        ],
    )

    fake_client = _FakeQdrantClient()
    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=fake_client,
        image_fetcher=lambda _url: b"fake-image-bytes",
        image_embedder=lambda images: [[0.25, 0.75] for _ in images],
    )

    assert result["corpora"]["discovery_image"]["status"] == "completed"
    assert result["corpora"]["discovery_image"]["documents_indexed"] == 1
    point = fake_client.upserts[0][1][0]
    assert "판테놀" in point.payload["retrieval_text"]
    assert "촉촉해요" in point.payload["retrieval_text"]


def test_execute_indexing_plan_discovery_image_host_python_wrapper_merges_auxiliary_text(tmp_path: Path, monkeypatch):
    backend_model = tmp_path / "backend" / "models"
    backend_model.mkdir(parents=True)
    db_path = tmp_path / "backend" / "products.sqlite3"
    (backend_model / "__init__.py").write_text(
        "import sqlite3\n"
        f"DB_PATH = {str(db_path)!r}\n"
        "def get_connection():\n"
        "    return sqlite3.connect(DB_PATH)\n",
        encoding="utf-8",
    )
    (backend_model / "product.py").write_text(
        "def get_all_products(category=None, search=None):\n"
        "    return [{\"product_id\": 1, \"image_url\": \"https://cdn.example.com/item.jpg\", \"name\": \"로션\", \"brand\": \"브랜드A\"}]\n",
        encoding="utf-8",
    )

    import sqlite3

    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE product_info (product_id INTEGER, ingredients TEXT, review TEXT)")
    cursor.execute("INSERT INTO product_info (product_id, ingredients, review) VALUES (1, '판테놀', '촉촉해요')")
    connection.commit()
    cursor.close()
    connection.close()

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.indexing.coordinator.prepare_backend_runtime",
        lambda **kwargs: type(
            "PrepResult",
            (),
            {
                "passed": True,
                "failure_summary": None,
                "python_executable": sys.executable,
                "seed_source_path": None,
            },
        )(),
    )

    host_context = HostExportContext()
    host_context.host_runtime_workspace = tmp_path
    host_context.snapshot = object()
    host_context.export_ready.set()

    plan = RetrievalIndexPlan(
        site_id="demo-shop",
        site_slug="demo-shop",
        corpora=[
            RagCorpusPlan(
                corpus="discovery_image",
                chunking_strategy="image_level",
                collection_alias="site_demo_shop__discovery_image",
                build_collection="site_demo_shop__discovery_image__run_demo",
                sources=["backend/models/product.py"],
                smoke_queries=["로션"],
                minimum_expected_documents=1,
                loader_strategy="public_url_fetch",
                row_source_strategy="host_python_fetch",
                row_source_module="models.product",
                row_source_callable="get_all_products",
                row_id_field="product_id",
                row_image_url_field="image_url",
                dense_image_field="image_url",
                sparse_text_paths=["name", "brand", "product_info.ingredients", "product_info.review"],
                payload_paths=["product_id", "name", "brand", "product_info"],
                row_enrichment_strategy="host_python_wrapper",
                auxiliary_relation_hints=[
                    {
                        "table_name": "product_info",
                        "key_field": "product_id",
                        "merge_as": "product_info",
                        "text_fields": ["ingredients", "review"],
                    }
                ],
            )
        ],
    )

    fake_client = _FakeQdrantClient()
    result = execute_indexing_plan(
        plan=plan,
        root=tmp_path,
        host_context=host_context,
        qdrant_client=fake_client,
        image_fetcher=lambda _url: b"fake-image-bytes",
        image_embedder=lambda images: [[0.25, 0.75] for _ in images],
    )

    assert result["corpora"]["discovery_image"]["status"] == "completed"
    point = fake_client.upserts[0][1][0]
    assert point.payload["product_info"]["ingredients"] == "판테놀"
    assert point.payload["product_info"]["review"] == "촉촉해요"
    assert "판테놀" in point.payload["retrieval_text"]
    assert "촉촉해요" in point.payload["retrieval_text"]


def test_embed_image_bytes_batch_accepts_pooler_output(monkeypatch):
    import torch

    class _FakeProcessor:
        def __call__(self, *, images, return_tensors, padding):
            del images, return_tensors, padding
            return {"pixel_values": torch.ones((1, 3, 2, 2), dtype=torch.float32)}

    class _FakeOutput:
        def __init__(self):
            self.pooler_output = torch.tensor([[3.0, 4.0]], dtype=torch.float32)

    class _FakeModel:
        def get_image_features(self, **kwargs):
            del kwargs
            return _FakeOutput()

    monkeypatch.setattr(
        "chatbot.src.tools.image_search_tools._resolve_device",
        lambda: torch.device("cpu"),
    )
    monkeypatch.setattr(
        "chatbot.src.tools.image_search_tools._get_clip_resources",
        lambda device: (_FakeProcessor(), _FakeModel()),
    )

    image = Image.new("RGB", (1, 1), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    vectors = _embed_image_bytes_batch([buffer.getvalue()])

    assert vectors == [pytest.approx([0.6, 0.8], rel=1e-5)]
