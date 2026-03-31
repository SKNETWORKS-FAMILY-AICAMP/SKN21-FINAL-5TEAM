from __future__ import annotations

import os
import sys
from pathlib import Path

from qdrant_client.http import models

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatbot.src.infrastructure import site_retrieval
from chatbot.src.core.config import settings


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
        self.aliases: dict[str, str] = {"site_demo__faq": "site_demo__faq__old"}
        self.deleted: list[str] = []
        self.payload_indexes: list[tuple[str, str, object]] = []
        self.alias_updates: list[list[object]] = []
        self.upserts: list[tuple[str, list[models.PointStruct]]] = []

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, collection_name: str, **kwargs) -> None:
        self.collections[collection_name] = dict(kwargs)

    def delete_collection(self, collection_name: str) -> None:
        self.deleted.append(collection_name)
        self.collections.pop(collection_name, None)

    def create_payload_index(self, collection_name: str, field_name: str, field_schema: object) -> None:
        self.payload_indexes.append((collection_name, field_name, field_schema))

    def get_aliases(self) -> _FakeAliasResponse:
        return _FakeAliasResponse(
            [_FakeAliasInfo(alias_name, collection_name) for alias_name, collection_name in self.aliases.items()]
        )

    def update_collection_aliases(self, change_aliases_operations: list[object], timeout: int | None = None, **kwargs) -> bool:
        del timeout, kwargs
        self.alias_updates.append(list(change_aliases_operations))
        for operation in change_aliases_operations:
            if isinstance(operation, models.DeleteAliasOperation):
                self.aliases.pop(operation.delete_alias.alias_name, None)
            elif isinstance(operation, models.CreateAliasOperation):
                self.aliases[operation.create_alias.alias_name] = operation.create_alias.collection_name
        return True

    def upsert(self, collection_name: str, points: list[models.PointStruct]) -> None:
        self.upserts.append((collection_name, list(points)))


def test_ensure_build_collection_creates_dense_sparse_text_collection():
    client = _FakeQdrantClient()

    site_retrieval.ensure_build_collection(
        collection_name="site_demo__faq__run_001",
        corpus="faq",
        vector_size=4,
        client=client,
    )

    created = client.collections["site_demo__faq__run_001"]
    assert isinstance(created["vectors_config"], models.VectorParams)
    assert created["vectors_config"].size == 4
    assert "text-sparse" in created["sparse_vectors_config"]
    assert ("site_demo__faq__run_001", "main_category", "keyword") in client.payload_indexes


def test_ensure_build_collection_creates_multimodal_image_collection():
    client = _FakeQdrantClient()

    site_retrieval.ensure_build_collection(
        collection_name="site_demo__discovery_image__run_001",
        corpus="discovery_image",
        vector_size=8,
        client=client,
    )

    created = client.collections["site_demo__discovery_image__run_001"]
    assert isinstance(created["vectors_config"], dict)
    assert created["vectors_config"][""].size == 8
    assert "text-sparse" in created["sparse_vectors_config"]
    assert ("site_demo__discovery_image__run_001", "product_id", "integer") in client.payload_indexes
    assert ("site_demo__discovery_image__run_001", "image_url", "keyword") in client.payload_indexes


def test_swap_alias_repoints_live_alias_atomically():
    client = _FakeQdrantClient()
    client.collections["site_demo__faq__run_002"] = {"vectors_config": "existing"}

    site_retrieval.swap_alias(
        alias_name="site_demo__faq",
        build_collection="site_demo__faq__run_002",
        client=client,
    )

    assert client.aliases["site_demo__faq"] == "site_demo__faq__run_002"
    operations = client.alias_updates[-1]
    assert any(isinstance(item, models.DeleteAliasOperation) for item in operations)
    assert any(isinstance(item, models.CreateAliasOperation) for item in operations)


def test_resolve_runtime_retrieval_capabilities_for_site_c_uses_global_defaults(monkeypatch):
    client = _FakeQdrantClient()
    client.collections[settings.COLLECTION_FAQ] = {}
    client.collections[settings.COLLECTION_TERMS] = {}
    client.collections[settings.COLLECTION_CLIP_IMAGE] = {}

    monkeypatch.setattr(site_retrieval, "_get_client", lambda: client)

    capability_profile, enabled, widget_features = site_retrieval.resolve_runtime_retrieval_capabilities(
        "site-c"
    )

    assert capability_profile == "order_cs_plus_retrieval"
    assert enabled == ["faq", "policy", "discovery_image"]
    assert widget_features == {"image_upload": True}
