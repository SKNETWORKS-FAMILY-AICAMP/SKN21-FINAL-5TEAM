import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.overlay_generator import generate_overlay_scaffold


def test_generate_overlay_scaffold_creates_bundle_structure_and_report(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "food-run-001",
        "site": "food",
        "source_root": "/workspace/food",
        "created_at": "2026-03-15T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "auth": {
                "login_entrypoints": ["backend/users/views.py:login"],
                "me_entrypoints": ["backend/users/views.py:me"],
            },
            "product_api": ["/api/products/"],
            "order_api": ["/api/orders/"],
            "frontend_mount_points": ["frontend/src/App.js"],
        },
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root)

    assert (run_root / "files").is_dir()
    assert (run_root / "patches").is_dir()
    assert (run_root / "reports").is_dir()

    plan_path = run_root / "reports" / "generation-plan.json"
    assert plan_path.exists()

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert "chat_auth_endpoint" in plan["recommended_outputs"]
    assert "frontend_widget_mount_patch" in plan["recommended_outputs"]
    assert plan["detected"]["auth"]["login_entrypoints"] == ["backend/users/views.py:login"]

    refreshed_manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    smoke_steps = refreshed_manifest["tests"]["smoke"]
    assert smoke_steps[0]["id"] == "login"
    assert smoke_steps[0]["script"] == "smoke-tests/login.sh"
    assert smoke_steps[0]["required"] is True
    assert smoke_steps[0]["category"] == "auth"
