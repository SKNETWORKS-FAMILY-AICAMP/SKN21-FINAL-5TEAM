import csv
import os
from collections import Counter
from collections import defaultdict
from pathlib import Path

import boto3


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_PRODUCTS_CSV = ROOT_DIR / "food" / "backend" / "seed" / "products.csv"
OUTPUT_PATH = ROOT_DIR / "food" / "backend" / "seed" / "s3_image_candidates.csv"
ENV_PATHS = [
    ROOT_DIR / ".env",
    ROOT_DIR / "docker" / "AWS" / ".env",
]


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


def load_catalog_rows():
    load_env()
    products_csv = Path(os.environ.get("FOOD_PRODUCTS_SOURCE_CSV", DEFAULT_PRODUCTS_CSV))
    with products_csv.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_s3_candidates():
    client = get_s3_client()
    bucket = os.environ["AWS_STORAGE_BUCKET_NAME"]

    candidates = defaultdict(list)
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="products/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            base_name = Path(key).name
            suffix = base_name.split("_", 1)[1] if "_" in base_name else base_name
            candidates[suffix].append(
                {
                    "key": key,
                    "last_modified": obj["LastModified"].isoformat(),
                    "size": obj["Size"],
                }
            )

    for suffix in candidates:
        candidates[suffix].sort(key=lambda item: (item["last_modified"], item["key"]))

    return candidates


def main():
    rows = load_catalog_rows()
    candidates = load_s3_candidates()
    suffix_counts = Counter(Path(row["image"]).name for row in rows)

    max_candidates = max(
        (len(candidates[Path(row["image"]).name]) for row in rows),
        default=0,
    )

    fieldnames = [
        "product_id",
        "name",
        "expected_image",
        "suffix",
        "duplicate_suffix_count",
        "candidate_count",
        "selected_candidate",
        "selected_key",
        "selected_image_url",
        "notes",
    ]
    for idx in range(1, max_candidates + 1):
        fieldnames.extend(
            [
                f"candidate_{idx}_key",
                f"candidate_{idx}_last_modified",
                f"candidate_{idx}_size",
            ]
        )

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for row_data in rows:
            product_id = row_data["id"]
            name = row_data["name"]
            image = row_data["image"]
            suffix = Path(image).name
            suffix_candidate_list = candidates[suffix]
            duplicate_suffix_count = suffix_counts[suffix]

            row = {
                "product_id": product_id,
                "name": name,
                "expected_image": image,
                "suffix": suffix,
                "duplicate_suffix_count": duplicate_suffix_count,
                "candidate_count": len(suffix_candidate_list),
            }

            # If this suffix belongs to exactly one catalog product, picking the
            # latest uploaded S3 object is deterministic enough to prefill.
            if duplicate_suffix_count == 1 and suffix_candidate_list:
                row["selected_key"] = suffix_candidate_list[-1]["key"]
                row["notes"] = "auto-selected latest candidate for unique suffix"

            for idx, candidate in enumerate(suffix_candidate_list, start=1):
                row[f"candidate_{idx}_key"] = candidate["key"]
                row[f"candidate_{idx}_last_modified"] = candidate["last_modified"]
                row[f"candidate_{idx}_size"] = candidate["size"]
            writer.writerow(row)

    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
