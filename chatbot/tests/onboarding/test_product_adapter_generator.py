import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.template_generator import generate_product_adapter_template


def test_generate_product_adapter_template_creates_python_file_with_detected_endpoint(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "product_api": ["/api/products/"],
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_product_adapter_template(run_root)

    assert output_path == run_root / "files" / "backend" / "product_adapter_client.py"
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "class GeneratedProductAdapterClient" in content
    assert 'PRODUCT_API_BASE = "/api/products/"' in content
    assert "def list_products" in content
    assert "def get_product" in content
    assert 'params=params or {}' in content
    assert 'f"{self.base_url}{PRODUCT_API_BASE}{product_id}/"' in content


def test_generate_product_adapter_template_uses_fallback_when_no_product_api_detected(tmp_path: Path):
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "bilyeo-run-001",
                "site": "bilyeo",
                "source_root": "/workspace/bilyeo",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "product_api": [],
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_product_adapter_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert 'PRODUCT_API_BASE = "/products"' in content


def test_generate_product_adapter_template_for_bilyeo_includes_category_and_search_filters(tmp_path: Path):
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "bilyeo-run-001",
                "site": "bilyeo",
                "source_root": "/workspace/bilyeo",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "product_api": ["/products"],
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_product_adapter_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert 'PRODUCT_API_BASE = "/products"' in content
    assert '"category": category' in content
    assert '"search": search' in content
    assert "if value is not None and value != \"\"" in content


def test_generate_product_adapter_template_for_ecommerce_uses_new_product_routes(tmp_path: Path):
    run_root = tmp_path / "generated" / "ecommerce" / "ecommerce-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "ecommerce-run-001",
                "site": "ecommerce",
                "source_root": "/workspace/ecommerce",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "product_api": ["/new"],
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_product_adapter_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert 'PRODUCT_API_BASE = "/new"' in content
    assert '"keyword": keyword' in content
    assert '"min_price": min_price' in content
    assert '"max_price": max_price' in content
