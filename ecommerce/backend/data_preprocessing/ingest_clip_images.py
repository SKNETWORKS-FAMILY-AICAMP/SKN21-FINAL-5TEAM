#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import torch
from PIL import Image
from qdrant_client.http import models
from tqdm import tqdm
from transformers import CLIPModel, CLIPProcessor

from ecommerce.backend.app.core.config import settings
from ecommerce.backend.app.infrastructure.qdrant import get_qdrant_client


@dataclass
class ProductImage:
    product_id: int
    image_url: str
    absolute_path: Path
    product_display_name: str | None = None
    article_type: str | None = None
    sub_category: str | None = None
    usage: str | None = None
    season: str | None = None
    base_colour: str | None = None
    gender: str | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_catalog(csv_path: Path, image_root: Path) -> list[ProductImage]:
    if not csv_path.exists():
        raise FileNotFoundError(f"image csv not found: {csv_path}")

    df = pd.read_csv(csv_path, usecols=["product_id", "image_url"])

    styles_csv_path = (
        _project_root()
        / "ecommerce"
        / "backend"
        / "data"
        / "processed"
        / "fashion-1000-balanced"
        / "sampled_styles.csv"
    )
    styles_by_id: dict[int, dict[str, Any]] = {}
    if styles_csv_path.exists():
        styles_df = pd.read_csv(
            styles_csv_path,
            usecols=[
                "id",
                "gender",
                "subCategory",
                "articleType",
                "baseColour",
                "season",
                "usage",
                "productDisplayName",
            ],
        )
        for _, s in styles_df.iterrows():
            try:
                pid = int(s["id"])
            except Exception:
                continue
            styles_by_id[pid] = {
                "product_display_name": str(s.get("productDisplayName") or "").strip() or None,
                "article_type": str(s.get("articleType") or "").strip() or None,
                "sub_category": str(s.get("subCategory") or "").strip() or None,
                "usage": str(s.get("usage") or "").strip() or None,
                "season": str(s.get("season") or "").strip() or None,
                "base_colour": str(s.get("baseColour") or "").strip() or None,
                "gender": str(s.get("gender") or "").strip() or None,
            }
    image_root_resolved = image_root.resolve()

    rows: list[ProductImage] = []
    for _, row in df.iterrows():
        image_url = str(row["image_url"]).strip()
        if not image_url:
            continue

        image_path = (image_root / image_url.lstrip("/")).resolve()
        if not str(image_path).startswith(str(image_root_resolved)):
            continue
        if not image_path.exists():
            continue

        style_meta = styles_by_id.get(int(row["product_id"]), {})
        rows.append(
            ProductImage(
                product_id=int(row["product_id"]),
                image_url=image_url,
                absolute_path=image_path,
                product_display_name=style_meta.get("product_display_name"),
                article_type=style_meta.get("article_type"),
                sub_category=style_meta.get("sub_category"),
                usage=style_meta.get("usage"),
                season=style_meta.get("season"),
                base_colour=style_meta.get("base_colour"),
                gender=style_meta.get("gender"),
            )
        )

    if not rows:
        raise ValueError("no valid image rows found")
    return rows


def _load_clip(device: torch.device) -> tuple[CLIPProcessor, CLIPModel]:
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    model.to(device)  # type: ignore[arg-type]
    model.eval()
    return processor, model


def _embed_batch(
    batch: list[ProductImage],
    processor: CLIPProcessor,
    model: CLIPModel,
    device: torch.device,
) -> list[list[float]]:
    images: list[Image.Image] = []
    for item in batch:
        with Image.open(item.absolute_path) as handle:
            images.append(handle.convert("RGB"))

    inputs = processor(images=images, return_tensors="pt", padding=True)  # type: ignore[call-arg]
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        output: Any = model.get_image_features(**inputs)

    if isinstance(output, torch.Tensor):
        features = output
    elif hasattr(output, "pooler_output"):
        features = output.pooler_output
    else:
        raise AttributeError("unexpected output from CLIP.get_image_features")

    normalized = features / features.norm(dim=-1, keepdim=True)
    return normalized.cpu().to(torch.float32).tolist()


def ingest_clip_images(batch_size: int = 64) -> None:
    root = _project_root()
    csv_path = root / "scripts" / "data" / "productimages.csv"
    image_root = root / "ecommerce" / "platform" / "frontend" / "public"

    print("Loading image catalog...")
    rows = _load_catalog(csv_path, image_root)
    print(f"Catalog size: {len(rows)}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    processor, model = _load_clip(device)
    embedding_dim = int(model.config.projection_dim)

    client = get_qdrant_client()
    collection = settings.COLLECTION_CLIP_IMAGE

    try:
        client.get_collection(collection_name=collection)
        print(f"Collection {collection} exists. Recreating...")
        client.delete_collection(collection_name=collection)
    except Exception:
        pass

    client.create_collection(
        collection_name=collection,
        vectors_config={
            "": models.VectorParams(size=embedding_dim, distance=models.Distance.COSINE)
        },
    )

    point_id = 1
    for i in tqdm(range(0, len(rows), batch_size), desc="Ingesting CLIP image vectors"):
        batch = rows[i : i + batch_size]
        vectors = _embed_batch(batch, processor, model, device)
        points: list[models.PointStruct] = []

        for j, item in enumerate(batch):
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={"": vectors[j]},
                    payload={
                        "product_id": item.product_id,
                        "image_url": item.image_url,
                        "product_display_name": item.product_display_name,
                        "article_type": item.article_type,
                        "sub_category": item.sub_category,
                        "usage": item.usage,
                        "season": item.season,
                        "base_colour": item.base_colour,
                        "gender": item.gender,
                    },
                )
            )
            point_id += 1

        client.upsert(collection_name=collection, points=points)

    print(f"Done. Upserted {point_id - 1} image vectors into {collection}")


if __name__ == "__main__":
    ingest_clip_images()
