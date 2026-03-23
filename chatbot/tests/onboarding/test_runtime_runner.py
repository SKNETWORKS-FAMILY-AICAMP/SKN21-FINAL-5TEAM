import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.manifest import OverlayManifest
from chatbot.src.onboarding.runtime_runner import (
    apply_overlay_edit_artifacts,
    prepare_runtime_workspace,
    simulate_exported_patch_replay,
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


def test_overlay_manifest_accepts_edit_artifacts(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-001",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-23T12:00:00+09:00",
            "agent_version": "v1",
            "analysis": {},
            "generated_files": [],
            "patch_targets": [],
            "edit_artifacts": ["reports/edit-plan.json"],
            "docker": {},
            "tests": {},
            "status": "generated",
        }
    )

    assert manifest.edit_artifacts == ["reports/edit-plan.json"]


def test_apply_overlay_edit_artifacts_updates_workspace_and_writes_report(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    run_root = generated_root / "food" / "run-001"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "reports" / "edit-plan.json").write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "path": "backend/users/views.py",
                        "operation": "insert_after",
                        "anchor": "def login(request):\n    return None\n",
                        "content": "\n\ndef onboarding_chat_auth_token(request):\n    return None\n",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-001",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-23T12:00:00+09:00",
            "agent_version": "v1",
            "analysis": {},
            "generated_files": [],
            "patch_targets": [],
            "edit_artifacts": ["reports/edit-plan.json"],
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
    report_path = apply_overlay_edit_artifacts(
        manifest=manifest,
        generated_run_root=run_root,
        workspace_root=workspace,
        report_root=run_root / "reports",
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert report_path.name == "edit-execution.json"
    assert payload["passed"] is True
    assert payload["applied_edit_artifacts"] == ["reports/edit-plan.json"]
    assert payload["applied_edits"] == [
        {"path": "backend/users/views.py", "operation": "insert_after"}
    ]
    assert "onboarding_chat_auth_token" in (workspace / "backend" / "users" / "views.py").read_text(encoding="utf-8")


def test_apply_overlay_edit_artifacts_allows_empty_operation_plans(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    run_root = generated_root / "food" / "run-empty"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "reports" / "edit-plan.json").write_text(
        json.dumps({"operations": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-empty",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-23T12:00:00+09:00",
            "agent_version": "v1",
            "analysis": {},
            "generated_files": [],
            "patch_targets": [],
            "edit_artifacts": ["reports/edit-plan.json"],
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
    report_path = apply_overlay_edit_artifacts(
        manifest=manifest,
        generated_run_root=run_root,
        workspace_root=workspace,
        report_root=run_root / "reports",
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["passed"] is True
    assert payload["applied_edit_artifacts"] == ["reports/edit-plan.json"]
    assert payload["applied_edits"] == []
    assert payload["failed_edit_artifacts"] == []


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


def test_prepare_runtime_workspace_retries_runtime_cleanup_when_rmtree_is_transient(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text("export default function App() { return null; }\n", encoding="utf-8")

    run_root = generated_root / "food" / "run-001"
    run_root.mkdir(parents=True)
    existing_workspace = runtime_root / "food" / "run-001" / "workspace"
    (existing_workspace / "frontend" / "node_modules" / ".cache").mkdir(parents=True)
    (existing_workspace / "frontend" / "node_modules" / ".cache" / "cache.txt").write_text("cache\n", encoding="utf-8")

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

    original_rmtree = shutil.rmtree
    calls = {"count": 0}

    def flaky_rmtree(path, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError(66, "Directory not empty", str(path))
        return original_rmtree(path, *args, **kwargs)

    with patch("chatbot.src.onboarding.runtime_runner.shutil.rmtree", side_effect=flaky_rmtree):
        workspace = prepare_runtime_workspace(
            manifest=manifest,
            generated_run_root=run_root,
            runtime_root=runtime_root,
        )

    assert calls["count"] == 2
    assert workspace.exists()
    assert (workspace / "frontend" / "src" / "App.js").exists()


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


def test_simulate_runtime_merge_ignores_unlisted_patch_artifacts(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend").mkdir(parents=True)
    (source_root / "backend" / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )

    run_root = generated_root / "shop" / "run-unlisted"
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "extra.patch").write_text(
        """--- a/backend/app.py
+++ b/backend/app.py
@@ -1,2 +1,3 @@
 from flask import Flask
 app = Flask(__name__)
+print("patched")
""",
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-unlisted",
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

    assert "patches/extra.patch" not in payload["applied_patch_artifacts"]
    assert payload["failed_patch_artifacts"] == []
    assert (workspace / "backend" / "app.py").read_text(encoding="utf-8") == "from flask import Flask\napp = Flask(__name__)\n"


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
@@ -1,3 +1,12 @@
+const ORDER_CS_WIDGET_HOST_CONTRACT = {
+  authBootstrapPath: "/api/chat/auth-token",
+  widgetBundlePath: "/widget.js",
+};
+globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"] = ORDER_CS_WIDGET_HOST_CONTRACT;
export default function App() {
    return <main>Home</main>;
}
+
+  <order-cs-widget />
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


def test_simulate_runtime_merge_ignores_draft_llm_proposed_patch(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    run_root = generated_root / "food" / "run-llm-ignore"
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
            "run_id": "run-llm-ignore",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-23T12:00:00+09:00",
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

    assert "patches/llm-proposed.patch" not in payload["applied_patch_artifacts"]
    assert payload["failed_patch_artifacts"] == []
    assert "onboarding_chat_auth_token" not in (workspace / "backend" / "users" / "views.py").read_text(encoding="utf-8")


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


def test_simulate_exported_patch_replay_applies_approved_patch_to_clean_workspace(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_root = tmp_path / "runtime"
    report_root = tmp_path / "generated" / "food" / "run-001" / "reports"
    patch_path = report_root / "approved.patch"

    (source_root / "app").mkdir(parents=True)
    (source_root / "app" / "config.txt").write_text("original\n", encoding="utf-8")
    report_root.mkdir(parents=True)
    patch_path.write_text(
        """--- a/app/config.txt
+++ b/app/config.txt
@@ -1 +1 @@
-original
+updated
""",
        encoding="utf-8",
    )

    replay_path = simulate_exported_patch_replay(
        source_root=source_root,
        runtime_root=runtime_root,
        report_root=report_root,
        patch_path=patch_path,
        site="food",
        run_id="run-001",
    )
    payload = json.loads(replay_path.read_text(encoding="utf-8"))
    replay_workspace = runtime_root / "food" / "run-001" / "export-replay-workspace"

    assert replay_path.name == "export-replay-validation.json"
    assert payload["passed"] is True
    assert payload["patch_path"] == str(patch_path)
    assert payload["applied_patch_artifacts"] == ["reports/approved.patch"]
    assert (replay_workspace / "app" / "config.txt").read_text(encoding="utf-8") == "updated\n"


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


def test_simulate_candidate_patch_merge_reports_invalid_proposed_patch(tmp_path: Path):
    source_root = tmp_path / "source"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    run_root = generated_root / "food" / "run-proposed"
    (run_root / "patches").mkdir(parents=True)
    (run_root / "patches" / "proposed.patch").write_text(
        "not a valid patch\n",
        encoding="utf-8",
    )

    manifest = OverlayManifest.model_validate(
        {
            "run_id": "run-proposed",
            "site": "food",
            "source_root": str(source_root),
            "created_at": "2026-03-19T12:00:00+09:00",
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
        patch_artifact="patches/proposed.patch",
        report_name="proposed-patch-simulation.json",
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert report_path.name == "proposed-patch-simulation.json"
    assert payload["candidate_patch"] == "patches/proposed.patch"
    assert payload["passed"] is False
    assert payload["failed_patch_artifacts"]
    assert payload["failed_patch_artifacts"][0]["path"] == "patches/proposed.patch"


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
