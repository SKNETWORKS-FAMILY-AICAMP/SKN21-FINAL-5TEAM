import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.backend_build_runner import build_plan_for_workspace


def test_build_plan_uses_requirements_txt_for_venv_and_pip_install(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "requirements.txt").write_text("flask\n", encoding="utf-8")

    plan = build_plan_for_workspace(workspace)

    assert plan.venv_dir == ".venv"
    assert plan.create_venv_command == ["python", "-m", "venv", ".venv"]
    assert plan.install_command == [".venv/bin/python", "-m", "pip", "install", "-r", "requirements.txt"]
    assert plan.manifest_source == "requirements.txt"


def test_build_plan_uses_pyproject_for_venv_and_pip_install_dot(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    plan = build_plan_for_workspace(workspace)

    assert plan.venv_dir == ".venv"
    assert plan.create_venv_command == ["python", "-m", "venv", ".venv"]
    assert plan.install_command == [".venv/bin/python", "-m", "pip", "install", "."]
    assert plan.manifest_source == "pyproject.toml"


def test_build_plan_returns_no_commands_without_backend_manifest(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    plan = build_plan_for_workspace(workspace)

    assert plan.venv_dir == ".venv"
    assert plan.create_venv_command is None
    assert plan.install_command is None
    assert plan.manifest_source is None
