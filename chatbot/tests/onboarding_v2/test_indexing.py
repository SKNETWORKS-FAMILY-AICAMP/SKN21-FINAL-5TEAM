import os
import sys
from pathlib import Path
from uuid import UUID

from qdrant_client.http import models

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
    assert [collection for collection, _ in fake_client.upserts] == [
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
    )

    discovery = result["corpora"]["discovery_image"]
    assert discovery["status"] == "completed"
    assert discovery["documents_indexed"] == 1
    assert discovery["alias_swapped"] is True
    assert "image_fetch_failed" in discovery["warning_codes"]
    assert fake_client.aliases["site_demo-shop__discovery_image"] == "site_demo-shop__discovery_image__run_demo"
    UUID(str(fake_client.upserts[0][1][0].id))


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
