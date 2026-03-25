import argparse
import csv
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath

import boto3


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_PRODUCTS_CSV = ROOT_DIR / "food" / "backend" / "seed" / "products.csv"
ENV_PATHS = [
    ROOT_DIR / ".env",
    ROOT_DIR / "docker" / "AWS" / ".env",
]


CATEGORY_LABEL_SCORES = {
    "apple": {"apple": 100},
    "banana": {"banana": 100},
    "beetroot": {"beetroot": 100, "beet": 95, "turnip": 80, "radish": 70},
    "bell_pepper": {"bell pepper": 100, "pepper": 80, "capsicum": 80},
    "cabbage": {"cabbage": 100, "leafy green vegetable": 60},
    "capsicum": {"bell pepper": 100, "pepper": 80, "capsicum": 80},
    "carrot": {"carrot": 100},
    "cauliflower": {"cauliflower": 100},
    "chilli pepper": {"chili pepper": 100, "jalapeno": 95, "pepper": 70},
    "corn": {"corn": 100, "maize": 90},
    "cucumber": {"cucumber": 100},
    "eggplant": {"eggplant": 100, "aubergine": 90},
    "garlic": {"garlic": 100},
    "ginger": {"ginger": 100},
    "grapes": {"grapes": 100, "grape": 95},
    "jalepeno": {"jalapeno": 100, "chili pepper": 95, "pepper": 70},
    "kiwi": {"kiwi": 100},
    "lemon": {"lemon": 100, "citrus fruit": 80},
    "lettuce": {"lettuce": 100, "leafy green vegetable": 70},
    "mango": {"mango": 100},
    "onion": {"onion": 100},
    "orange": {"orange": 100, "citrus fruit": 80},
    "paprika": {"bell pepper": 100, "pepper": 80, "paprika": 80},
    "pear": {"pear": 100},
    "peas": {"pea": 100, "peas": 95, "bean": 70, "legume": 70},
    "pineapple": {"pineapple": 100},
    "pomegranate": {"pomegranate": 100},
    "potato": {"potato": 100},
    "raddish": {"radish": 100, "turnip": 85},
    "soy_beans": {"soybean": 100, "bean": 80, "legume": 80, "peas": 50},
    "spinach": {"spinach": 100, "leafy green vegetable": 70},
    "sweetcorn": {"corn": 100, "maize": 90},
    "sweetpotato": {"sweet potato": 100, "yam": 95, "potato": 80},
    "tomato": {"tomato": 100},
    "turnip": {"turnip": 100, "radish": 85},
    "watermelon": {"watermelon": 100},
}


def load_env():
    for env_path in ENV_PATHS:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_s3_client():
    load_env()
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_S3_REGION_NAME"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def get_rekognition_client():
    load_env()
    return boto3.client(
        "rekognition",
        region_name=os.environ.get("AWS_S3_REGION_NAME"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def load_catalog_rows(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_bucket_objects(s3_client, bucket: str):
    exact_keys = set()
    suffix_index = defaultdict(list)
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="products/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            exact_keys.add(key)
            base_name = PurePosixPath(key).name
            suffix = base_name.split("_", 1)[1] if "_" in base_name else base_name
            suffix_index[suffix].append(
                {
                    "key": key,
                    "last_modified": obj["LastModified"].isoformat(),
                    "size": int(obj["Size"]),
                }
            )

    for suffix, items in suffix_index.items():
        items.sort(key=lambda item: (parse_iso_datetime(item["last_modified"]), item["key"]))

    return exact_keys, suffix_index


def normalize_labels(labels):
    return {str(label.get("Name") or "").strip().lower() for label in labels if label.get("Name")}


def detect_labels(rekognition_client, bucket: str, key: str, cache: dict[str, set[str]]):
    cached = cache.get(key)
    if cached is not None:
        return cached

    response = rekognition_client.detect_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        MaxLabels=12,
    )
    labels = normalize_labels(response.get("Labels", []))
    cache[key] = labels
    return labels


def score_candidate(category: str, labels: set[str]) -> int:
    score_map = CATEGORY_LABEL_SCORES.get(category, {})
    return max((score_map[label] for label in labels if label in score_map), default=0)


def choose_source_key(category: str, candidates: list[dict], rekognition_client, bucket: str, cache):
    unique_candidates = []
    seen = set()
    for item in candidates:
        key = item["key"]
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(item)

    if len(unique_candidates) == 1:
        return unique_candidates[0]["key"], "single suffix candidate"

    scored = []
    for item in unique_candidates:
        labels = detect_labels(rekognition_client, bucket, item["key"], cache)
        scored.append((score_candidate(category, labels), item, labels))

    best_score = max((score for score, _, _ in scored), default=0)
    if best_score <= 0:
        return None, "no recognizable category label"

    top_matches = [(item, labels) for score, item, labels in scored if score == best_score]
    top_matches.sort(key=lambda pair: (parse_iso_datetime(pair[0]["last_modified"]), pair[0]["key"]))
    selected_item, selected_labels = top_matches[-1]
    note = f"rekognition labels: {', '.join(sorted(selected_labels)[:5])}"
    return selected_item["key"], note


def sync_catalog(args):
    load_env()
    products_csv = Path(args.products_csv)
    bucket = os.environ["AWS_STORAGE_BUCKET_NAME"]
    s3_client = get_s3_client()
    rekognition_client = get_rekognition_client()
    rows = load_catalog_rows(products_csv)
    exact_keys, suffix_index = list_bucket_objects(s3_client, bucket)
    label_cache = {}

    copied = 0
    skipped = 0
    unresolved = []

    for row in rows:
        target_key = str(row.get("image") or "").strip().lstrip("/")
        if not target_key:
            continue

        if target_key in exact_keys:
            skipped += 1
            continue

        parts = target_key.split("/")
        if len(parts) < 3:
            unresolved.append((row.get("id"), row.get("name"), "invalid image path"))
            continue

        category = parts[1]
        suffix = PurePosixPath(target_key).name
        candidates = [item for item in suffix_index.get(suffix, []) if item["key"] != target_key]

        source_key, reason = choose_source_key(
            category=category,
            candidates=candidates,
            rekognition_client=rekognition_client,
            bucket=bucket,
            cache=label_cache,
        )

        if not source_key:
            unresolved.append((row.get("id"), row.get("name"), reason))
            continue

        print(f"{row.get('id')} {row.get('name')}: {source_key} -> {target_key} ({reason})")
        if not args.dry_run:
            s3_client.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": source_key},
                Key=target_key,
            )
            exact_keys.add(target_key)
        copied += 1

    print(f"canonical keys already present: {skipped}")
    print(f"copied canonical keys: {copied}")
    print(f"unresolved rows: {len(unresolved)}")
    for product_id, name, reason in unresolved[:20]:
        print(f"  - {product_id}:{name} ({reason})")

    if unresolved:
        raise SystemExit(1)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Ensure S3 contains canonical keys from products.csv."
    )
    parser.add_argument(
        "--products-csv",
        default=str(DEFAULT_PRODUCTS_CSV),
        help="Path to products.csv",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview copies without writing to S3",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    sync_catalog(args)


if __name__ == "__main__":
    main()
