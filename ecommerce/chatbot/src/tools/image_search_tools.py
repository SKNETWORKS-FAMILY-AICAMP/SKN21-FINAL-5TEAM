#!/usr/bin/env python3

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple

import faiss
import torch
from langchain_core.tools import tool
from PIL import Image
from transformers import CLIPModel, CLIPProcessor


def _vector_store_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "vector_store"


def _load_clip(device: torch.device) -> Tuple[CLIPProcessor, CLIPModel]:
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    model.to(device)
    model.eval()
    return processor, model


def _load_faiss_index() -> Tuple[faiss.IndexFlatIP, Dict[int, int]]:
    vector_store = _vector_store_dir()
    faiss_path = vector_store / "image_index.faiss"
    metadata_path = vector_store / "metadata.json"

    if not faiss_path.exists():
        raise FileNotFoundError(f"FAISS index not found at {faiss_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata not found at {metadata_path}")

    metadata = json.loads(metadata_path.read_text())
    index_to_product = {entry["index"]: int(entry["product_id"]) for entry in metadata}
    index = faiss.read_index(str(faiss_path))
    return index, index_to_product


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
    normalized = image_features / image_features.norm(dim=-1, keepdim=True)
    return normalized.cpu().to(torch.float32).squeeze(0)


def _search_by_embedding(embedding: torch.Tensor, index: faiss.IndexFlatIP, index_to_product: Dict[int, int], top_k: int) -> List[int]:
    distances, indices = index.search(embedding.numpy().reshape(1, -1), top_k)
    hits: List[int] = []
    for idx in indices[0]:
        if idx == -1:
            continue
        product_id = index_to_product.get(int(idx))
        if product_id is not None:
            hits.append(product_id)
    return hits


_CLIP_RESOURCES: Dict[str, object] = {}


def _get_clip_resources(device: torch.device) -> Tuple[CLIPProcessor, CLIPModel]:
    key = f"clip::{device.type}"
    if key not in _CLIP_RESOURCES:
        processor, model = _load_clip(device)
        _CLIP_RESOURCES[key] = (processor, model)
    return _CLIP_RESOURCES[key]  # type: ignore[return-value]


def _search_image(image: Image.Image, top_k: int) -> List[int]:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    processor, model = _get_clip_resources(device)
    index, index_to_product = _load_faiss_index()
    embedding = _embed_image(image, device, processor, model)
    return _search_by_embedding(embedding, index, index_to_product, top_k)


def search_similar_images(image_path: str, top_k: int = 5) -> List[int]:
    vector_store = _vector_store_dir()
    candidates = (Path(image_path) if Path(image_path).is_absolute() else vector_store / image_path).resolve()
    if not candidates.exists():
        raise FileNotFoundError(f"image to search not found at {candidates}")

    with Image.open(candidates) as handle:
        image = handle.convert("RGB")

    return _search_image(image, top_k)


def search_similar_images_from_bytes(image_bytes: bytes, top_k: int = 5) -> List[int]:
    """Search similar images using in-memory bytes."""
    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError(f"이미지 로딩 실패: {exc}") from exc
    return _search_image(image, top_k)


@tool
def search_similar_images_tool(image_bytes: bytes, top_k: int = 5) -> dict:
    """LangChain tool for FAISS-based image similarity search using raw bytes."""
    try:
        recommended = search_similar_images_from_bytes(image_bytes, top_k)
        return {"recommended_product_ids": recommended}
    except Exception as exc:
        return {"error": str(exc)}
