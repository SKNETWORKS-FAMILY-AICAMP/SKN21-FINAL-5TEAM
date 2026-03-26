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


def get_current_runtime_site_id() -> str | None:
    return _CURRENT_RUNTIME_SITE_ID.get()


@contextmanager
def use_runtime_site_id(site_id: str | None) -> Iterator[None]:
    token = _CURRENT_RUNTIME_SITE_ID.set(site_id)
    try:
        yield
    finally:
        _CURRENT_RUNTIME_SITE_ID.reset(token)
