import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.template_generator import generate_order_adapter_template


def test_generate_order_adapter_template_creates_python_file_with_detected_endpoint(tmp_path: Path):
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
                    "order_api": ["/api/orders/"],
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

    output_path = generate_order_adapter_template(run_root)

    assert output_path == run_root / "files" / "backend" / "order_adapter_client.py"
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "class GeneratedOrderAdapterClient" in content
    assert 'ORDER_API_BASE = "/api/orders/"' in content
    assert "def get_order" in content
    assert "def list_orders" in content
    assert 'response = await client.get(f"{self.base_url}{ORDER_API_BASE}"' in content
    assert 'response = await client.post(' in content
    assert 'f"{self.base_url}{ORDER_API_BASE}{order_id}/actions/"' in content


def test_generate_order_adapter_template_uses_fallback_when_no_order_api_detected(tmp_path: Path):
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
                    "order_api": [],
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

    output_path = generate_order_adapter_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert 'ORDER_API_BASE = "/orders"' in content


def test_generate_order_adapter_template_for_ecommerce_includes_user_id_paths(tmp_path: Path):
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
                    "order_api": ["/{user_id}/orders"],
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

    output_path = generate_order_adapter_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert "user_id: int" in content
    assert 'ORDER_API_BASE = "/{user_id}/orders"' in content
    assert '.format(user_id=user_id)' in content
    assert 'f"{self.base_url}{order_base}/{order_id}"' in content
    assert 'f"{self.base_url}{order_base}/{order_id}/cancel"' in content


def test_generate_order_adapter_template_exposes_list_get_and_action_contract(tmp_path: Path):
    run_root = tmp_path / "generated" / "shop" / "shop-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "shop-run-001",
                "site": "food",
                "source_root": "/workspace/shop",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {"order_api": ["/api/orders/"]},
                "generated_files": [],
                "patch_targets": [],
                "frontend_artifacts": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    content = generate_order_adapter_template(run_root).read_text(encoding="utf-8")

    assert "async def list_orders" in content
    assert "async def get_order" in content
    assert "async def submit_order_action" in content
    assert "headers: dict | None = None" in content
