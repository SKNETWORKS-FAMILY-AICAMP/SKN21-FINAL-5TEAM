import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.exporter import export_patch_artifact, export_runtime_patch


def test_export_runtime_patch_writes_patch_file_for_runtime_changes(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_workspace = tmp_path / "runtime" / "food" / "run-001" / "workspace"
    report_root = tmp_path / "generated" / "food" / "run-001" / "reports"

    (source_root / "app").mkdir(parents=True)
    (runtime_workspace / "app").mkdir(parents=True)
    report_root.mkdir(parents=True)

    (source_root / "app" / "config.txt").write_text("line-1\nline-2\n", encoding="utf-8")
    (runtime_workspace / "app" / "config.txt").write_text("line-1\nline-2-updated\n", encoding="utf-8")

    patch_path = export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        patch_name="approved.patch",
        strategy_provenance={"backend_strategy": "django", "frontend_strategy": "react"},
    )

    assert patch_path == report_root / "approved.patch"
    assert patch_path.exists()
    content = patch_path.read_text(encoding="utf-8")
    assert "--- a/app/config.txt" in content
    assert "+++ b/app/config.txt" in content
    assert "+line-2-updated" in content
    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert metadata["changed_files"] == ["app/config.txt"]
    assert metadata["strategy_provenance"] == {"backend_strategy": "django", "frontend_strategy": "react"}


def test_export_runtime_patch_writes_empty_patch_when_no_changes(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_workspace = tmp_path / "runtime" / "food" / "run-001" / "workspace"
    report_root = tmp_path / "generated" / "food" / "run-001" / "reports"

    (source_root / "app").mkdir(parents=True)
    (runtime_workspace / "app").mkdir(parents=True)
    report_root.mkdir(parents=True)

    (source_root / "app" / "config.txt").write_text("same\n", encoding="utf-8")
    (runtime_workspace / "app" / "config.txt").write_text("same\n", encoding="utf-8")

    patch_path = export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        patch_name="no-op.patch",
    )

    assert patch_path.read_text(encoding="utf-8") == ""
    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert metadata["changed_files"] == []


def test_export_runtime_patch_skips_non_utf8_files(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_workspace = tmp_path / "runtime" / "food" / "run-001" / "workspace"
    report_root = tmp_path / "generated" / "food" / "run-001" / "reports"

    (source_root / "app" / "__pycache__").mkdir(parents=True)
    (runtime_workspace / "app" / "__pycache__").mkdir(parents=True)
    report_root.mkdir(parents=True)

    (source_root / "app" / "__pycache__" / "module.cpython-313.pyc").write_bytes(b"\xf3\x00\x00\x00")
    (runtime_workspace / "app" / "__pycache__" / "module.cpython-313.pyc").write_bytes(b"\xf3\x00\x00\x01")

    patch_path = export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        patch_name="approved.patch",
    )

    assert patch_path.read_text(encoding="utf-8") == ""
    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert metadata["changed_files"] == []


def test_export_runtime_patch_skips_runtime_dependency_and_build_artifacts(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_workspace = tmp_path / "runtime" / "food" / "run-001" / "workspace"
    report_root = tmp_path / "generated" / "food" / "run-001" / "reports"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "backend" / ".venv" / "bin").mkdir(parents=True)
    (runtime_workspace / "frontend" / "node_modules" / ".cache" / "babel-loader").mkdir(parents=True)
    report_root.mkdir(parents=True)

    (source_root / "frontend" / "src" / "App.js").write_text("export default function App() { return null; }\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <div id=\"chat-root\" />; }\n",
        encoding="utf-8",
    )
    (runtime_workspace / "backend" / ".venv" / "bin" / "python").write_text("shim\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "node_modules" / ".cache" / "babel-loader" / "cache.json").write_text(
        "{\"compiled\":true}\n",
        encoding="utf-8",
    )

    patch_path = export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        patch_name="approved.patch",
    )

    content = patch_path.read_text(encoding="utf-8")
    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))

    assert "frontend/src/App.js" in metadata["changed_files"]
    assert "backend/.venv/bin/python" not in metadata["changed_files"]
    assert "frontend/node_modules/.cache/babel-loader/cache.json" not in metadata["changed_files"]
    assert "--- a/frontend/src/App.js" in content
    assert "backend/.venv/bin/python" not in content
    assert "frontend/node_modules/.cache/babel-loader/cache.json" not in content


def test_export_patch_artifact_copies_selected_patch_and_marks_llm_source(tmp_path: Path):
    report_root = tmp_path / "generated" / "food" / "run-001" / "reports"
    source_patch = tmp_path / "generated" / "food" / "run-001" / "patches" / "llm-proposed.patch"
    source_patch.parent.mkdir(parents=True)
    report_root.mkdir(parents=True)

    source_patch.write_text(
        "--- a/backend/users/urls.py\n+++ b/backend/users/urls.py\n@@ -1,1 +1,2 @@\n from django.urls import path\n+path(\"api/chat/auth-token\", onboarding_chat_auth_token)\n",
        encoding="utf-8",
    )

    patch_path = export_patch_artifact(
        patch_path=source_patch,
        report_root=report_root,
        export_source="llm",
        strategy_provenance={"backend_strategy": "fastapi", "frontend_strategy": "react"},
    )

    assert patch_path == report_root / "approved.patch"
    assert patch_path.read_text(encoding="utf-8") == source_patch.read_text(encoding="utf-8")
    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert metadata["export_source"] == "llm"
    assert metadata["source_patch_path"] == str(source_patch)
    assert metadata["changed_files"] == ["backend/users/urls.py"]
    assert metadata["strategy_provenance"] == {"backend_strategy": "fastapi", "frontend_strategy": "react"}


def test_export_runtime_patch_records_recovery_provenance(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_workspace = tmp_path / "runtime" / "food" / "run-002" / "workspace"
    report_root = tmp_path / "generated" / "food" / "run-002" / "reports"

    (source_root / "app").mkdir(parents=True)
    (runtime_workspace / "app").mkdir(parents=True)
    report_root.mkdir(parents=True)

    (source_root / "app" / "config.txt").write_text("line-1\n", encoding="utf-8")
    (runtime_workspace / "app" / "config.txt").write_text("line-1-updated\n", encoding="utf-8")

    export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        recovery_provenance={
            "recovery_artifact_path": str(report_root / "recovery-plan.json"),
            "final_recovery_source": "response_schema_mismatch",
        },
    )

    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert metadata["recovery_provenance"] == {
        "recovery_artifact_path": str(report_root / "recovery-plan.json"),
        "final_recovery_source": "response_schema_mismatch",
    }


def test_export_runtime_patch_overwrites_metadata_after_runtime_completion_reexport(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_workspace = tmp_path / "runtime" / "food" / "run-003" / "workspace"
    report_root = tmp_path / "generated" / "food" / "run-003" / "reports"

    (source_root / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    report_root.mkdir(parents=True)

    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )
    (runtime_workspace / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <main>Home</main>; }\n",
        encoding="utf-8",
    )

    export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        patch_name="approved.patch",
    )

    first_metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert first_metadata["changed_files"] == []

    (runtime_workspace / "frontend" / "src" / "App.js").write_text(
        'const ORDER_CS_WIDGET_HOST_CONTRACT = {\n'
        '  chatbotServerBaseUrl: "",\n'
        '  authBootstrapPath: "/api/chat/auth-token",\n'
        '  widgetBundlePath: "/widget.js",\n'
        '  widgetElementTag: "order-cs-widget",\n'
        '  mountMode: "floating_launcher",\n'
        '};\n'
        'globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"] = ORDER_CS_WIDGET_HOST_CONTRACT;\n'
        "export default function App() { return <><main>Home</main><order-cs-widget /></>; }\n",
        encoding="utf-8",
    )

    export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        patch_name="approved.patch",
    )

    second_metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    approved_patch = (report_root / "approved.patch").read_text(encoding="utf-8")

    assert second_metadata["changed_files"] == ["frontend/src/App.js"]
    assert "order-cs-widget" in approved_patch


def test_export_runtime_patch_can_limit_exports_to_allowed_seam_targets(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_workspace = tmp_path / "runtime" / "food" / "run-004" / "workspace"
    report_root = tmp_path / "generated" / "food" / "run-004" / "reports"

    (source_root / "frontend" / "src" / "views").mkdir(parents=True)
    (runtime_workspace / "frontend" / "src" / "views").mkdir(parents=True)
    report_root.mkdir(parents=True)

    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return null; }\n",
        encoding="utf-8",
    )
    (runtime_workspace / "frontend" / "src" / "App.js").write_text(
        "export default function App() { return <order-cs-widget />; }\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "views" / "Orders.js").write_text(
        "export const Orders = () => null;\n",
        encoding="utf-8",
    )
    (runtime_workspace / "frontend" / "src" / "views" / "Orders.js").write_text(
        "export const Orders = () => <section>Orders</section>;\n",
        encoding="utf-8",
    )

    patch_path = export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        allowed_targets={"frontend/src/App.js"},
    )

    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    content = patch_path.read_text(encoding="utf-8")

    assert metadata["changed_files"] == ["frontend/src/App.js"]
    assert "frontend/src/views/Orders.js" not in content
