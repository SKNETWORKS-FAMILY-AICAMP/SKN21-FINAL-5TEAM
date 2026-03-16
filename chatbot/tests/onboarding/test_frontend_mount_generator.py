import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.template_generator import generate_frontend_mount_patch


def test_generate_frontend_mount_patch_creates_patch_for_detected_mount_file(tmp_path: Path):
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
                    "frontend_mount_points": ["frontend/src/App.js"],
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

    patch_path = generate_frontend_mount_patch(run_root)

    assert patch_path == run_root / "patches" / "frontend_widget_mount.patch"
    assert patch_path.exists()
    content = patch_path.read_text(encoding="utf-8")
    assert "--- a/frontend/src/App.js" in content
    assert "+++ b/frontend/src/App.js" in content
    assert "SharedChatbotWidget" in content


def test_generate_frontend_mount_patch_uses_default_app_file_when_no_mount_detected(tmp_path: Path):
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
                    "frontend_mount_points": [],
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

    patch_path = generate_frontend_mount_patch(run_root)

    content = patch_path.read_text(encoding="utf-8")
    assert "--- a/frontend/src/App.js" in content
