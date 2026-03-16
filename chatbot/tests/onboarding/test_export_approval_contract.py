import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.exporter import export_runtime_patch


def test_export_report_contains_pr_metadata_placeholders(tmp_path: Path):
    source_root = tmp_path / "source"
    runtime_workspace = tmp_path / "runtime" / "food" / "run-001" / "workspace"
    report_root = tmp_path / "generated" / "food" / "run-001" / "reports"

    (source_root / "app").mkdir(parents=True)
    (runtime_workspace / "app").mkdir(parents=True)
    report_root.mkdir(parents=True)

    (source_root / "app" / "config.txt").write_text("line-1\nline-2\n", encoding="utf-8")
    (runtime_workspace / "app" / "config.txt").write_text("line-1\nline-2-updated\n", encoding="utf-8")

    export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=report_root,
        patch_name="approved.patch",
    )

    metadata = json.loads((report_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert metadata["patch_path"] == str(report_root / "approved.patch")
    assert metadata["pr"]["title"]
    assert metadata["pr"]["body"]
    assert metadata["pr"]["head_branch"]
