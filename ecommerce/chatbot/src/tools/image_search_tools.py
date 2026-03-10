#!/usr/bin/env python3

from __future__ import annotations

import re
from io import BytesIO
from dataclasses import dataclass
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


@dataclass
class SearchHit:
    product_id: int
    dense_score: float
    payload: dict


def _get_clip_resources(device: torch.device) -> Tuple[CLIPProcessor, CLIPModel]:
    key = f"clip::{device.type}"
    if key not in _CLIP_RESOURCES:
        processor, model = _load_clip(device)
        _CLIP_RESOURCES[key] = (processor, model)
    return _CLIP_RESOURCES[key]  # type: ignore[return-value]


def preload_clip_resources() -> None:
    """서버 시작 시 CLIP 모델/프로세서를 1회 미리 로드합니다."""
    device = _resolve_device()
    _get_clip_resources(device)


def _search_qdrant_by_embedding(
    embedding: torch.Tensor,
    top_k: int,
    candidate_k: int,
    search_mode: str = "similar",
) -> List[SearchHit]:
    bounded_top_k = max(1, min(20, int(top_k)))
    bounded_candidate_k = max(bounded_top_k, min(300, int(candidate_k)))
    query_vector = embedding.tolist()

    if search_mode.lower() == "opposite":
        query_vector = [-v for v in query_vector]

    client = get_qdrant_client()
    result = client.query_points(
        collection_name=settings.COLLECTION_CLIP_IMAGE,
        query=query_vector,
        using="",
        limit=bounded_candidate_k,
        with_payload=True,
    )

    hits_by_product: dict[int, SearchHit] = {}
    for point in result.points:
        payload = point.payload or {}
        raw_id = payload.get("product_id") or payload.get("id")
        if raw_id is None:
            continue
        try:
            product_id = int(raw_id)
        except Exception:
            continue
        score = float(getattr(point, "score", 0.0) or 0.0)
        existing = hits_by_product.get(product_id)
        if existing is not None and existing.dense_score >= score:
            continue
        hits_by_product[product_id] = SearchHit(
            product_id=product_id,
            dense_score=score,
            payload=dict(payload),
        )

    sorted_hits = sorted(hits_by_product.values(), key=lambda h: h.dense_score, reverse=True)
    return sorted_hits


def _normalize_dense_scores(hits: List[SearchHit]) -> dict[int, float]:
    if not hits:
        return {}
    scores = [h.dense_score for h in hits]
    min_score = min(scores)
    max_score = max(scores)
    if max_score - min_score < 1e-9:
        return {h.product_id: 1.0 for h in hits}
    return {
        h.product_id: (h.dense_score - min_score) / (max_score - min_score)
        for h in hits
    }


def _extract_query_tokens(query: str) -> set[str]:
    text = (query or "").lower().strip()
    if not text:
        return set()
    tokens = re.findall(r"[a-z0-9가-힣]+", text)
    return {t for t in tokens if len(t) >= 2}


def _payload_text(payload: dict) -> str:
    fields = [
        payload.get("product_display_name") or payload.get("name") or "",
        payload.get("article_type") or "",
        payload.get("sub_category") or "",
        payload.get("usage") or "",
        payload.get("season") or "",
        payload.get("base_colour") or "",
        payload.get("gender") or "",
    ]
    return " ".join(str(v).lower() for v in fields if v)


def _compute_soft_keyword_boost(query_text: str | None, payload: dict) -> float:
    query = (query_text or "").strip()
    if not query:
        return 0.0

    q_tokens = _extract_query_tokens(query)
    if not q_tokens:
        return 0.0

    text = _payload_text(payload)
    if not text:
        return 0.0

    token_hits = sum(1 for t in q_tokens if t in text)
    token_boost = min(0.8, token_hits * 0.16)

    query_lower = query.lower()
    explicit_boost = 0.0

    usage_value = str(payload.get("usage") or "").lower()
    season_value = str(payload.get("season") or "").lower()
    color_value = str(payload.get("base_colour") or "").lower()

    usage_synonyms = {
        "party": ["party", "파티", "데이트", "모임"],
        "sports": ["sports", "sport", "운동", "스포츠", "헬스"],
        "formal": ["formal", "포멀", "정장", "오피스"],
        "casual": ["casual", "캐주얼", "데일리"],
        "ethnic": ["ethnic", "전통", "한복", "에스닉"],
    }
    season_synonyms = {
        "summer": ["summer", "여름", "썸머"],
        "winter": ["winter", "겨울"],
        "spring": ["spring", "봄"],
        "fall": ["fall", "autumn", "가을"],
    }
    color_synonyms = {
        "black": ["black", "블랙", "검정", "검은"],
        "white": ["white", "화이트", "흰", "하얀"],
        "blue": ["blue", "블루", "파랑", "네이비"],
        "red": ["red", "레드", "빨강"],
    }

    for canonical, variants in usage_synonyms.items():
        if any(v in query_lower for v in variants) and canonical in usage_value:
            explicit_boost += 0.12

    for canonical, variants in season_synonyms.items():
        if any(v in query_lower for v in variants) and canonical in season_value:
            explicit_boost += 0.10

    for canonical, variants in color_synonyms.items():
        if any(v in query_lower for v in variants) and canonical in color_value:
            explicit_boost += 0.08

    return min(1.0, token_boost + explicit_boost)


def _rerank_hits_with_soft_boost(
    hits: List[SearchHit],
    query_text: str | None,
    top_k: int,
    dense_weight: float = 0.8,
    boost_weight: float = 0.2,
) -> List[int]:
    bounded_top_k = max(1, min(20, int(top_k)))
    if not hits:
        return []

    query = (query_text or "").strip()
    if not query:
        return [h.product_id for h in hits[:bounded_top_k]]

    dense_norm = _normalize_dense_scores(hits)
    alpha = min(0.95, max(0.55, float(dense_weight)))
    beta = min(0.45, max(0.05, float(boost_weight)))

    scored: list[tuple[float, int]] = []
    for hit in hits:
        boost = _compute_soft_keyword_boost(query, hit.payload)
        final_score = alpha * dense_norm.get(hit.product_id, 0.0) + beta * boost
        scored.append((final_score, hit.product_id))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [pid for _, pid in scored[:bounded_top_k]]


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
    candidate_k = max(top_k * 10, 80)
    hits = _search_qdrant_by_embedding(
        query_embedding,
        top_k=top_k,
        candidate_k=candidate_k,
        search_mode=search_mode,
    )
    return _rerank_hits_with_soft_boost(
        hits=hits,
        query_text=text,
        top_k=top_k,
        dense_weight=0.8,
        boost_weight=0.2,
    )


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
