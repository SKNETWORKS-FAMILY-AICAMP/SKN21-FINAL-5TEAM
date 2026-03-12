#!/usr/bin/env python3
"""Build a CLIP-powered FAISS index for the product image catalogue."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sys

import faiss
import numpy as np
import pandas as pd
import torch
from PIL import Image
from tqdm import tqdm
from transformers import CLIPModel, CLIPProcessor


@dataclass
class ProductImage:
    product_id: int
    image_url: str
    absolute_path: Path


def project_root() -> Path:
    try:
        return Path(__file__).resolve().parents[4]
    except IndexError as exc:
        raise RuntimeError(
            "unable to automatically determine the project root from build_image_index.py"
        ) from exc


def load_image_catalog(csv_path: Path, image_root: Path) -> list[ProductImage]:
    if not csv_path.exists():
        raise FileNotFoundError(f"image CSV not found at {csv_path}")
    df = pd.read_csv(csv_path, usecols=["product_id", "image_url"])
    resolved_root = image_root.resolve()
    missing: list[tuple[int | str, Path]] = []
    results: list[ProductImage] = []
    for _, row in df.iterrows():
        image_url = str(row["image_url"]).strip()
        if not image_url:
            continue
        candidate = (image_root / image_url.lstrip("/")).resolve()
        if not str(candidate).startswith(str(resolved_root)):
            raise ValueError(f"resolved image path {candidate} is outside {image_root}")
        if not candidate.exists():
            missing.append((row["product_id"], candidate))
            continue
        results.append(
            ProductImage(
                product_id=int(row["product_id"]),
                image_url=image_url,
                absolute_path=candidate,
            )
        )
    if missing:
        report = "\n".join(f"{pid}: {path}" for pid, path in missing[:10])
        plural = "images remain" if len(missing) > 1 else "image remains"
        raise FileNotFoundError(
            f"{len(missing)} {plural} missing; examples:\n{report}"
        )
    if not results:
        raise ValueError("no valid product images were parsed from the CSV")
    return results


def load_clip_model(model_name: str, device: torch.device) -> tuple[CLIPProcessor, CLIPModel]:
    processor = CLIPProcessor.from_pretrained(model_name)
    model = CLIPModel.from_pretrained(model_name)
    model.to(device)
    model.eval()
    return processor, model


def encode_images(
    images: list[ProductImage],
    processor: CLIPProcessor,
    model: CLIPModel,
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, list[dict[str, int | str]]]:
    embeddings: list[np.ndarray] = []
    metadata: list[dict[str, int | str]] = []
    global_index = 0
    for start in tqdm(range(0, len(images), batch_size), desc="encoding images", unit="batch"):
        batch = images[start : start + batch_size]
        pil_images: list[Image.Image] = []
        for entry in batch:
            with Image.open(entry.absolute_path) as handle:
                pil_images.append(handle.convert("RGB"))
        inputs = processor(images=pil_images, return_tensors="pt", padding=True)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            output = model.get_image_features(**inputs)
        image_features = output.pooler_output
        normalized = image_features / image_features.norm(dim=-1, keepdim=True)
        numpy_embeddings = normalized.cpu().to(torch.float32).numpy()
        embeddings.append(numpy_embeddings)
        for i, entry in enumerate(batch):
            metadata.append(
                {
                    "index": global_index + i,
                    "product_id": entry.product_id,
                    "image_url": entry.image_url,
                }
            )
        global_index += len(batch)
    combined = np.vstack(embeddings)
    return combined, metadata


def build_faiss_index(embeddings: np.ndarray) -> faiss.IndexFlatIP:
    if embeddings.ndim != 2:
        raise ValueError("embeddings must be a 2D array")
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    return index


def main() -> None:
    root = project_root()
    csv_path = root / "scripts" / "data" / "productimages.csv"
    image_root = root / "ecommerce" / "platform" / "frontend" / "public"
    output_dir = Path(__file__).resolve().parent
    faiss_path = output_dir / "image_index.faiss"
    metadata_path = output_dir / "metadata.json"

    images = load_image_catalog(csv_path, image_root)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    processor, model = load_clip_model("openai/clip-vit-base-patch32", device)
    embeddings, metadata = encode_images(images, processor, model, device, batch_size=32)
    index = build_faiss_index(embeddings)

    faiss_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(faiss_path))
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))

    print(f"saved FAISS index ({embeddings.shape[0]} vectors) to {faiss_path}")
    print(f"saved metadata ({len(metadata)} entries) to {metadata_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - top level guard
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
