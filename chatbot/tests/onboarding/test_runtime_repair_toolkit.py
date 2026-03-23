import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.runtime_repair_toolkit import (
    choose_runtime_import_replacement,
    resolve_python_module_candidates,
    rewrite_python_import_line,
)


def test_resolve_python_module_candidates_finds_runtime_module_file(tmp_path: Path):
    workspace = tmp_path / "runtime" / "food" / "food-run-015" / "workspace"
    (workspace / "backend").mkdir(parents=True)
    target = workspace / "backend" / "chat_auth.py"
    target.write_text("def chat_auth_token(request):\n    return None\n", encoding="utf-8")

    candidates = resolve_python_module_candidates(
        workspace_root=workspace,
        module_name="backend.chat_auth",
    )

    assert candidates == [target]


def test_choose_runtime_import_replacement_prefers_runtime_local_import_from_caller_context(tmp_path: Path):
    workspace = tmp_path / "runtime" / "food" / "food-run-015" / "workspace"
    caller_file = workspace / "backend" / "foodshop" / "urls.py"
    caller_file.parent.mkdir(parents=True)
    caller_file.write_text("from backend.chat_auth import chat_auth_token\n", encoding="utf-8")
    (workspace / "backend" / "chat_auth.py").write_text(
        "def chat_auth_token(request):\n    return None\n",
        encoding="utf-8",
    )

    replacement = choose_runtime_import_replacement(
        workspace_root=workspace,
        caller_file=caller_file,
        broken_import="backend.chat_auth",
    )

    assert replacement == "chat_auth"


def test_rewrite_python_import_line_rewrites_only_exact_import_statement(tmp_path: Path):
    file_path = tmp_path / "urls.py"
    file_path.write_text(
        "from backend.chat_auth import chat_auth_token\n"
        "from backend.chat_auth_extra import keep_me\n"
        "value = 'backend.chat_auth should stay in strings'\n",
        encoding="utf-8",
    )

    rewritten = rewrite_python_import_line(
        file_path=file_path,
        broken_import="backend.chat_auth",
        replacement_import="chat_auth",
    )

    assert rewritten is True
    content = file_path.read_text(encoding="utf-8")
    assert "from chat_auth import chat_auth_token" in content
    assert "from backend.chat_auth_extra import keep_me" in content
    assert "backend.chat_auth should stay in strings" in content
