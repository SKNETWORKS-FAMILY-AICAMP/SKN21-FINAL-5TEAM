#!/usr/bin/env python3

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

import torch
from langchain_core.tools import tool
from PIL import Image
from qdrant_client import models
from transformers import CLIPModel, CLIPProcessor

from ecommerce.chatbot.src.core.config import settings
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client


def _vector_store_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "vector_store"


def _load_clip(device: torch.device) -> Tuple[CLIPProcessor, CLIPModel]:
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    model.to(device)
    model.eval()
    return processor, model


def _to_unit_vector(tensor: torch.Tensor) -> torch.Tensor:
    normalized = tensor / tensor.norm(dim=-1, keepdim=True)
    return normalized.cpu().to(torch.float32).squeeze(0)


def _embed_image(image: Image.Image, device: torch.device, processor: CLIPProcessor, model: CLIPModel) -> torch.Tensor:
    inputs = processor(images=image, return_tensors="pt", padding=True)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        output = model.get_image_features(**inputs)
    if isinstance(output, torch.Tensor):
        image_features = output
    elif hasattr(output, "pooler_output"):
        image_features = output.pooler_output
    else:
        raise AttributeError("unexpected output from CLIP.get_image_features")
    return _to_unit_vector(image_features)


def _embed_text(text: str, device: torch.device, processor: CLIPProcessor, model: CLIPModel) -> torch.Tensor:
    inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        output = model.get_text_features(**inputs)
    if isinstance(output, torch.Tensor):
        text_features = output
    elif hasattr(output, "pooler_output"):
        text_features = output.pooler_output
    else:
        raise AttributeError("unexpected output from CLIP.get_text_features")
    return _to_unit_vector(text_features)


def _combine_query_embeddings(
    image_embedding: Optional[torch.Tensor],
    text_embedding: Optional[torch.Tensor],
    text_weight: float = 0.4,
) -> torch.Tensor:
    if image_embedding is None and text_embedding is None:
        raise ValueError("at least one embedding must be provided")
    if image_embedding is None:
        return text_embedding  # type: ignore[return-value]
    if text_embedding is None:
        return image_embedding

    alpha = min(0.9, max(0.1, float(text_weight)))
    mixed = (1.0 - alpha) * image_embedding + alpha * text_embedding
    norm = mixed.norm(p=2)
    if float(norm) == 0.0:
        return image_embedding
    return mixed / norm


_CLIP_RESOURCES: dict[str, object] = {}


def _get_clip_resources(device: torch.device) -> Tuple[CLIPProcessor, CLIPModel]:
    key = f"clip::{device.type}"
    if key not in _CLIP_RESOURCES:
        processor, model = _load_clip(device)
        _CLIP_RESOURCES[key] = (processor, model)
    return _CLIP_RESOURCES[key]  # type: ignore[return-value]


def _search_qdrant_by_embedding(
    embedding: torch.Tensor,
    top_k: int,
    search_mode: str = "similar",
) -> List[int]:
    bounded_top_k = max(1, min(20, int(top_k)))
    query_vector = embedding.tolist()

    if search_mode.lower() == "opposite":
        query_vector = [-v for v in query_vector]

    client = get_qdrant_client()
    result = client.query_points(
        collection_name=settings.COLLECTION_CLIP_IMAGE,
        query=query_vector,
        using="",
        limit=bounded_top_k,
        with_payload=True,
    )

    hits: List[int] = []
    seen: set[int] = set()
    for point in result.points:
        payload = point.payload or {}
        raw_id = payload.get("product_id") or payload.get("id")
        if raw_id is None:
            continue
        try:
            product_id = int(raw_id)
        except Exception:
            continue
        if product_id in seen:
            continue
        seen.add(product_id)
        hits.append(product_id)
    return hits


def _resolve_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    mps_backend = getattr(torch.backends, "mps", None)
    if mps_backend and mps_backend.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _search_clip(
    image: Optional[Image.Image] = None,
    text: Optional[str] = None,
    top_k: int = 5,
    search_mode: str = "similar",
    text_weight: float = 0.4,
) -> List[int]:
    if image is None and not text:
        raise ValueError("image 또는 text 중 하나는 필요합니다.")

    device = _resolve_device()
    processor, model = _get_clip_resources(device)

    image_embedding = None
    text_embedding = None
    if image is not None:
        image_embedding = _embed_image(image, device, processor, model)
    if text:
        text_embedding = _embed_text(text, device, processor, model)

    query_embedding = _combine_query_embeddings(
        image_embedding=image_embedding,
        text_embedding=text_embedding,
        text_weight=text_weight,
    )
    return _search_qdrant_by_embedding(query_embedding, top_k=top_k, search_mode=search_mode)


def search_similar_images(image_path: str, top_k: int = 5) -> List[int]:
    vector_store = _vector_store_dir()
    candidates = (Path(image_path) if Path(image_path).is_absolute() else vector_store / image_path).resolve()
    if not candidates.exists():
        raise FileNotFoundError(f"image to search not found at {candidates}")

    with Image.open(candidates) as handle:
        image = handle.convert("RGB")

    return _search_clip(image=image, top_k=top_k)


def search_similar_images_from_bytes(image_bytes: bytes, top_k: int = 5) -> List[int]:
    """Search similar images using in-memory bytes."""
    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError(f"이미지 로딩 실패: {exc}") from exc
    return _search_clip(image=image, top_k=top_k)


def search_similar_products_from_text(
    text: str,
    top_k: int = 5,
    search_mode: str = "similar",
) -> List[int]:
    query = (text or "").strip()
    if not query:
        raise ValueError("텍스트 질의가 비어 있습니다.")
    return _search_clip(text=query, top_k=top_k, search_mode=search_mode)


def search_similar_products_multimodal(
    image_bytes: bytes | None,
    text: str | None,
    top_k: int = 5,
    search_mode: str = "similar",
    text_weight: float = 0.4,
) -> List[int]:
    image = None
    if image_bytes is not None:
        try:
            image = Image.open(BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise ValueError(f"이미지 로딩 실패: {exc}") from exc
    query_text = (text or "").strip() or None
    return _search_clip(
        image=image,
        text=query_text,
        top_k=top_k,
        search_mode=search_mode,
        text_weight=text_weight,
    )


@tool
def search_similar_images_tool(image_bytes: bytes, top_k: int = 5) -> dict:
    """LangChain tool for CLIP+Qdrant image similarity search using raw bytes."""
    try:
        recommended = search_similar_images_from_bytes(image_bytes, top_k)
        return {"recommended_product_ids": recommended}
    except Exception as exc:
        return {"error": str(exc)}
