import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.exporter import export_runtime_patch


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
    )

    assert patch_path == report_root / "approved.patch"
    assert patch_path.exists()
    content = patch_path.read_text(encoding="utf-8")
    assert "--- a/app/config.txt" in content
    assert "+++ b/app/config.txt" in content
    assert "+line-2-updated" in content
    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert metadata["changed_files"] == ["app/config.txt"]


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
