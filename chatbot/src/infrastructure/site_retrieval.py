from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from qdrant_client.http import models

from chatbot.src.core.config import settings

_CURRENT_RUNTIME_SITE_ID: ContextVar[str | None] = ContextVar(
    "current_runtime_site_id",
    default=None,
)


@dataclass(frozen=True)
class SiteCollections:
    faq: str
    policy: str
    discovery_image: str


def collection_exists(collection_name: str, *, client: object | None = None) -> bool:
    if not collection_name:
        return False
    client = client or _get_client()
    try:
        if hasattr(client, "collection_exists"):
            return bool(client.collection_exists(collection_name))
    except Exception:
        pass
    try:
        client.get_collection(collection_name=collection_name)
        return True
    except Exception:
        return False


def ensure_build_collection(
    *,
    collection_name: str,
    corpus: str,
    vector_size: int,
    client: object | None = None,
) -> None:
    client = client or _get_client()
    if collection_exists(collection_name, client=client):
        client.delete_collection(collection_name=collection_name)

    if corpus in {"faq", "policy"}:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=max(1, int(vector_size)),
                distance=models.Distance.COSINE,
            ),
            sparse_vectors_config={
                "text-sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False)
                )
            },
        )
        if corpus == "faq":
            client.create_payload_index(
                collection_name=collection_name,
                field_name="main_category",
                field_schema="keyword",
            )
            client.create_payload_index(
                collection_name=collection_name,
                field_name="sub_category",
                field_schema="keyword",
            )
        else:
            client.create_payload_index(
                collection_name=collection_name,
                field_name="clause_title",
                field_schema=models.TextIndexParams(
                    type=models.TextIndexType.TEXT,
                    tokenizer=models.TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=20,
                    lowercase=True,
                ),
            )
            client.create_payload_index(
                collection_name=collection_name,
                field_name="category",
                field_schema="keyword",
            )
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "": models.VectorParams(
                size=max(1, int(vector_size)),
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            "text-sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=False)
            )
        },
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="product_id",
        field_schema="integer",
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="image_url",
        field_schema="keyword",
    )


def upsert_points(
    *,
    collection_name: str,
    points: list[models.PointStruct],
    client: object | None = None,
) -> None:
    client = client or _get_client()
    client.upsert(collection_name=collection_name, points=points)


def swap_alias(
    *,
    alias_name: str,
    build_collection: str,
    client: object | None = None,
) -> None:
    client = client or _get_client()
    if not collection_exists(build_collection, client=client):
        raise ValueError(f"build collection does not exist: {build_collection}")

    operations: list[object] = []
    for alias in list(getattr(client.get_aliases(), "aliases", []) or []):
        if str(getattr(alias, "alias_name", "")).strip() == alias_name:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=alias_name)
                )
            )
            break
    operations.append(
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(
                collection_name=build_collection,
                alias_name=alias_name,
            )
        )
    )
    client.update_collection_aliases(change_aliases_operations=operations)


def normalize_site_slug(site_id: str | None) -> str | None:
    normalized = str(site_id or "").strip().lower().replace(" ", "_")
    if not normalized:
        return None
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in normalized)


def resolve_site_collections(site_id: str | None) -> SiteCollections:
    site_slug = normalize_site_slug(site_id)
    if not site_slug:
        return SiteCollections(
            faq=settings.COLLECTION_FAQ,
            policy=settings.COLLECTION_TERMS,
            discovery_image=settings.COLLECTION_CLIP_IMAGE,
        )
    return SiteCollections(
        faq=f"site_{site_slug}__faq",
        policy=f"site_{site_slug}__policy",
        discovery_image=f"site_{site_slug}__discovery_image",
    )


def resolve_runtime_retrieval_capabilities(site_id: str | None) -> tuple[str, list[str], dict[str, bool]]:
    enabled: list[str] = []
    widget_features = {"image_upload": False}
    collections = resolve_site_collections(site_id)

    try:
        client = _get_client()
        for corpus, collection_name in (
            ("faq", collections.faq),
            ("policy", collections.policy),
            ("discovery_image", collections.discovery_image),
        ):
            try:
                exists = collection_exists(collection_name, client=client)
                if exists:
                    enabled.append(corpus)
            except Exception:
                continue
    except Exception:
        enabled = []

    if "discovery_image" in enabled:
        widget_features["image_upload"] = True
    capability_profile = "order_cs_plus_retrieval" if enabled else "order_cs_only"
    return capability_profile, enabled, widget_features


def get_current_runtime_site_id() -> str | None:
    return _CURRENT_RUNTIME_SITE_ID.get()


@contextmanager
def use_runtime_site_id(site_id: str | None) -> Iterator[None]:
    token = _CURRENT_RUNTIME_SITE_ID.set(site_id)
    try:
        yield
    finally:
        _CURRENT_RUNTIME_SITE_ID.reset(token)


def _get_client():
    from chatbot.src.infrastructure.qdrant import get_qdrant_client

    return get_qdrant_client()
