import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.workspace_editor import apply_direct_edit_operations


def test_apply_direct_edit_operations_applies_supported_edits(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    target = workspace / "backend" / "users" / "views.py"
    target.parent.mkdir(parents=True)
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = apply_direct_edit_operations(
        workspace_root=workspace,
        operations=[
            {
                "path": "backend/users/views.py",
                "operation": "replace_text",
                "old": "beta",
                "new": "BETA",
            },
            {
                "path": "backend/users/views.py",
                "operation": "insert_before",
                "anchor": "alpha",
                "content": "start\n",
            },
            {
                "path": "backend/users/views.py",
                "operation": "insert_after",
                "anchor": "gamma",
                "content": "\nend",
            },
            {
                "path": "backend/users/views.py",
                "operation": "append_text",
                "content": "appended",
            },
        ],
    )

    assert target.read_text(encoding="utf-8") == "start\nalpha\nBETA\ngamma\nend\nappended"
    assert result["applied_edits"] == [
        {"path": "backend/users/views.py", "operation": "replace_text"},
        {"path": "backend/users/views.py", "operation": "insert_before"},
        {"path": "backend/users/views.py", "operation": "insert_after"},
        {"path": "backend/users/views.py", "operation": "append_text"},
    ]


@pytest.mark.parametrize("bad_path", ["/tmp/outside.py", "../outside.py", "backend/../outside.py"])
def test_apply_direct_edit_operations_rejects_invalid_paths(tmp_path: Path, bad_path: str):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "backend" / "users" / "views.py"
    target.parent.mkdir(parents=True)
    target.write_text("alpha\n", encoding="utf-8")

    with pytest.raises(ValueError):
        apply_direct_edit_operations(
            workspace_root=workspace,
            operations=[
                {
                    "path": bad_path,
                    "operation": "append_text",
                    "content": "beta\n",
                }
            ],
        )


def test_apply_direct_edit_operations_rejects_non_utf8_files(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "backend" / "users" / "views.pyc"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\x00\x80")

    with pytest.raises(ValueError):
        apply_direct_edit_operations(
            workspace_root=workspace,
            operations=[
                {
                    "path": "backend/users/views.pyc",
                    "operation": "append_text",
                    "content": "beta\n",
                }
            ],
        )


def test_apply_direct_edit_operations_rejects_unsupported_operation(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "backend" / "users" / "views.py"
    target.parent.mkdir(parents=True)
    target.write_text("alpha\n", encoding="utf-8")

    with pytest.raises(ValueError):
        apply_direct_edit_operations(
            workspace_root=workspace,
            operations=[
                {
                    "path": "backend/users/views.py",
                    "operation": "delete_text",
                    "content": "alpha\n",
                }
            ],
        )


def test_apply_direct_edit_operations_is_atomic_when_a_later_operation_fails(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "backend" / "users" / "views.py"
    target.parent.mkdir(parents=True)
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    with pytest.raises(ValueError, match="existing anchor"):
        apply_direct_edit_operations(
            workspace_root=workspace,
            operations=[
                {
                    "path": "backend/users/views.py",
                    "operation": "replace_text",
                    "old": "beta",
                    "new": "BETA",
                },
                {
                    "path": "backend/users/views.py",
                    "operation": "insert_after",
                    "anchor": "missing",
                    "content": "\nend",
                },
            ],
        )

    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"


def test_apply_direct_edit_operations_preserves_requested_blank_line_on_append(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "backend" / "users" / "views.py"
    target.parent.mkdir(parents=True)
    target.write_text("alpha\n", encoding="utf-8")

    apply_direct_edit_operations(
        workspace_root=workspace,
        operations=[
            {
                "path": "backend/users/views.py",
                "operation": "append_text",
                "content": "\n\nomega",
            }
        ],
    )

    assert target.read_text(encoding="utf-8") == "alpha\n\n\nomega"


def test_apply_direct_edit_operations_rejects_symlink_targets_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    outside_target = tmp_path / "outside.py"
    outside_target.write_text("alpha\n", encoding="utf-8")

    symlink_target = workspace / "backend" / "users" / "views.py"
    symlink_target.parent.mkdir(parents=True)
    symlink_target.symlink_to(outside_target)

    with pytest.raises(ValueError, match="inside the workspace"):
        apply_direct_edit_operations(
            workspace_root=workspace,
            operations=[
                {
                    "path": "backend/users/views.py",
                    "operation": "append_text",
                    "content": "omega\n",
                }
            ],
        )

    assert outside_target.read_text(encoding="utf-8") == "alpha\n"
