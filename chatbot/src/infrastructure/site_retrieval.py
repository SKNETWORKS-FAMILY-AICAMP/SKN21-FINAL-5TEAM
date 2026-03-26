from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

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
        from chatbot.src.infrastructure.qdrant import get_qdrant_client

        client = get_qdrant_client()
        for corpus, collection_name in (
            ("faq", collections.faq),
            ("policy", collections.policy),
            ("discovery_image", collections.discovery_image),
        ):
            try:
                exists = False
                if hasattr(client, "collection_exists"):
                    exists = bool(client.collection_exists(collection_name))
                if not exists:
                    client.get_collection(collection_name=collection_name)
                    exists = True
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
