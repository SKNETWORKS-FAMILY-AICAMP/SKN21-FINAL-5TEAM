import csv
import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_PRODUCTS_CSV = ROOT_DIR / "food" / "backend" / "seed" / "products.csv"
DEFAULT_CANDIDATES_CSV = ROOT_DIR / "food" / "backend" / "seed" / "s3_image_candidates.csv"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "food" / "backend" / "seed" / "products.csv"
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


def get_default_public_base_url():
    base_url = os.environ.get("FOOD_IMAGE_BASE_URL", "").strip().rstrip("/")
    if base_url:
        return base_url

    bucket = os.environ.get("AWS_STORAGE_BUCKET_NAME", "").strip()
    region = os.environ.get("AWS_S3_REGION_NAME", "").strip()
    if bucket and region:
        return f"https://{bucket}.s3.{region}.amazonaws.com"

    return ""


def resolve_selected_image(candidate_row, public_base_url):
    explicit_url = (candidate_row.get("selected_image_url") or "").strip()
    if explicit_url:
        return explicit_url

    explicit_key = (candidate_row.get("selected_key") or "").strip()
    if explicit_key:
        return f"{public_base_url}/{explicit_key.lstrip('/')}" if public_base_url else explicit_key

    selected_candidate = (candidate_row.get("selected_candidate") or "").strip()
    if not selected_candidate:
        return ""

    if not selected_candidate.isdigit():
        raise ValueError(
            f"product_id={candidate_row.get('product_id')} selected_candidate must be a number"
        )

    candidate_key = candidate_row.get(f"candidate_{selected_candidate}_key", "").strip()
    if not candidate_key:
        raise ValueError(
            f"product_id={candidate_row.get('product_id')} candidate_{selected_candidate}_key is empty"
        )

    return f"{public_base_url}/{candidate_key.lstrip('/')}" if public_base_url else candidate_key


def load_candidate_rows(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["product_id"]: row for row in csv.DictReader(fh)}


def main():
    load_env()

    products_csv = Path(os.environ.get("FOOD_PRODUCTS_SOURCE_CSV", DEFAULT_PRODUCTS_CSV))
    candidates_csv = Path(os.environ.get("FOOD_S3_CANDIDATES_CSV", DEFAULT_CANDIDATES_CSV))
    output_csv = Path(os.environ.get("FOOD_PRODUCTS_OUTPUT_CSV", DEFAULT_OUTPUT_CSV))
    public_base_url = get_default_public_base_url()

    candidate_rows = load_candidate_rows(candidates_csv)
    unresolved = []
    resolved_count = 0

    with products_csv.open(encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames or ["id", "name", "description", "price", "image", "stock"]
        rows = []
        for row in reader:
            candidate_row = candidate_rows.get(row["id"])
            if not candidate_row:
                rows.append(row)
                continue

            resolved_image = resolve_selected_image(candidate_row, public_base_url)
            if resolved_image:
                row["image"] = resolved_image
                resolved_count += 1
            else:
                unresolved.append((row["id"], row["name"]))
            rows.append(row)

    if unresolved:
        preview = ", ".join(f"{pid}:{name}" for pid, name in unresolved[:10])
        raise SystemExit(
            f"{len(unresolved)} products are still missing a selected S3 image. "
            f"Fill selected_candidate, selected_key, or selected_image_url in "
            f"{candidates_csv}. Examples: {preview}"
        )

    with output_csv.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"updated {output_csv}")
    print(f"resolved {resolved_count} product images")


if __name__ == "__main__":
    main()
