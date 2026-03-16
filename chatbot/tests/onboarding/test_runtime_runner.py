import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.manifest import OverlayManifest
from chatbot.src.onboarding.runtime_runner import prepare_runtime_workspace, simulate_runtime_merge


def test_prepare_runtime_workspace_copies_source_and_overlay_files(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "app").mkdir(parents=True)
    (source_root / "app" / "config.txt").write_text("original\n", encoding="utf-8")
    (source_root / "README.md").write_text("hello\n", encoding="utf-8")

    run_root = generated_root / "food" / "run-001"
    (run_root / "files" / "app").mkdir(parents=True)
    (run_root / "files" / "app" / "generated.txt").write_text("overlay\n", encoding="utf-8")

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-001",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-15T12:00:00+09:00",
            "agent_version": "v1",
            "analysis": {},
            "generated_files": ["files/app/generated.txt"],
            "patch_targets": [],
            "docker": {},
            "tests": {},
            "status": "generated",
        }
    )

    workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_root=runtime_root,
    )

    assert (workspace / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (workspace / "app" / "config.txt").read_text(encoding="utf-8") == "original\n"
    assert (workspace / "app" / "generated.txt").read_text(encoding="utf-8") == "overlay\n"


def test_simulate_runtime_merge_writes_report(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "app").mkdir(parents=True)
    (source_root / "app" / "config.txt").write_text("original\n", encoding="utf-8")

    run_root = generated_root / "food" / "run-001"
    (run_root / "files" / "app").mkdir(parents=True)
    (run_root / "files" / "app" / "generated.txt").write_text("overlay\n", encoding="utf-8")
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "config.patch").write_text(
        """--- a/app/config.txt
+++ b/app/config.txt
@@ -1 +1 @@
-original
+updated
""",
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-001",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-15T12:00:00+09:00",
            "agent_version": "v1",
            "analysis": {},
            "generated_files": ["files/app/generated.txt"],
            "patch_targets": ["patches/config.patch"],
            "docker": {},
            "tests": {},
            "status": "generated",
        }
    )

    workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_root=runtime_root,
    )
    report_path = simulate_runtime_merge(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_workspace=workspace,
        report_root=run_root / "reports",
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert report_path.name == "merge-simulation.json"
    assert payload["workspace_root"] == str(workspace)
    assert "app/generated.txt" in payload["applied_generated_files"]
    assert "patches/config.patch" in payload["applied_patch_artifacts"]


def test_simulate_runtime_merge_applies_proposed_patch_to_workspace(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() {\n    return <main>Home</main>;\n}\n",
        encoding="utf-8",
    )

    run_root = generated_root / "shop" / "run-frontend"
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "proposed.patch").write_text(
        """--- a/frontend/src/App.js
+++ b/frontend/src/App.js
@@ -1,3 +1,6 @@
+import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";
 export default function App() {
     return <main>Home</main>;
 }
+
+  <SharedChatbotWidget />
""",
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-frontend",
            "site": "shop",
            "source_root": str(source_root),
            "created_at": "2026-03-15T12:00:00+09:00",
            "agent_version": "v1",
            "analysis": {},
            "generated_files": [],
            "patch_targets": [],
            "docker": {},
            "tests": {},
            "status": "generated",
        }
    )

    workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_root=runtime_root,
    )
    report_path = simulate_runtime_merge(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_workspace=workspace,
        report_root=run_root / "reports",
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    content = (workspace / "frontend" / "src" / "App.js").read_text(encoding="utf-8")

    assert "patches/proposed.patch" in payload["applied_patch_artifacts"]
    assert payload["failed_patch_artifacts"] == []
    assert 'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";' in content
