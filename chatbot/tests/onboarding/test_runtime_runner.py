import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.manifest import OverlayManifest
from chatbot.src.onboarding.runtime_runner import (
    prepare_runtime_workspace,
    simulate_candidate_patch_merge,
    simulate_runtime_merge,
)


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


def test_prepare_runtime_workspace_excludes_dependency_and_build_artifacts(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "node_modules" / ".bin").mkdir(parents=True)
    (source_root / "frontend" / "node_modules" / ".bin" / "react-scripts").write_text(
        "broken runtime shim\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "build").mkdir(parents=True)
    (source_root / "frontend" / "build" / "index.html").write_text(
        "old build\n",
        encoding="utf-8",
    )
    (source_root / "backend").mkdir(parents=True)
    (source_root / "backend" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (source_root / "backend" / "__pycache__").mkdir(parents=True)
    (source_root / "backend" / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"pyc")
    (source_root / ".venv" / "bin").mkdir(parents=True)
    (source_root / ".venv" / "bin" / "python").write_text("python\n", encoding="utf-8")

    run_root = generated_root / "food" / "run-001"
    run_root.mkdir(parents=True)

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-001",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-18T12:00:00+09:00",
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

    assert (workspace / "frontend" / "src" / "App.js").exists()
    assert (workspace / "backend" / "app.py").exists()
    assert not (workspace / "frontend" / "node_modules").exists()
    assert not (workspace / ".venv").exists()
    assert not (workspace / "backend" / "__pycache__").exists()
    assert not (workspace / "frontend" / "build").exists()


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


def test_simulate_runtime_merge_ignores_draft_proposed_patch(tmp_path: Path):
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

    assert "patches/proposed.patch" not in payload["applied_patch_artifacts"]
    assert payload["failed_patch_artifacts"] == []
    assert 'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";' not in content


def test_simulate_runtime_merge_ignores_invalid_draft_proposed_patch(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend").mkdir(parents=True)
    (source_root / "backend" / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )

    run_root = generated_root / "shop" / "run-fail"
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "proposed.patch").write_text(
        """--- a/backend/missing.py
+++ b/backend/missing.py
@@ -1 +1 @@
-missing
+updated
""",
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-fail",
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

    assert payload["passed"] is True
    assert payload["failed_patch_artifacts"] == []
    assert "patches/proposed.patch" not in payload["applied_patch_artifacts"]

def test_simulate_candidate_patch_merge_writes_llm_patch_report(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    run_root = generated_root / "food" / "run-llm"
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "llm-proposed.patch").write_text(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,5 @@
 def login(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
""",
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-llm",
            "site": "food",
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

    report_path = simulate_candidate_patch_merge(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_root=runtime_root,
        report_root=run_root / "reports",
        patch_artifact="patches/llm-proposed.patch",
        report_name="llm-patch-simulation.json",
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert report_path.name == "llm-patch-simulation.json"
    assert payload["candidate_patch"] == "patches/llm-proposed.patch"
    assert payload["passed"] is True
    assert payload["applied_patch_artifacts"] == ["patches/llm-proposed.patch"]


def test_simulate_runtime_merge_emits_observability_events(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend").mkdir(parents=True)
    (source_root / "backend" / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )

    run_root = generated_root / "shop" / "run-fail"
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "proposed.patch").write_text(
        """--- a/backend/missing.py
+++ b/backend/missing.py
@@ -1 +1 @@
-missing
+updated
""",
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-fail",
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
    simulate_runtime_merge(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_workspace=workspace,
        report_root=run_root / "reports",
    )

    trace_path = run_root / "reports" / "execution-trace.jsonl"
    trace_lines = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert any(item["component"] == "runtime_runner" and item["event"] == "simulation_started" for item in trace_lines)
    assert not any(item["component"] == "runtime_runner" and item["event"] == "hard_fallback_used" for item in trace_lines)
    assert any(item["component"] == "runtime_runner" and item["event"] == "simulation_completed" for item in trace_lines)
