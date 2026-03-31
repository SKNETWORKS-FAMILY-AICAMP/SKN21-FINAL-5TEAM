from __future__ import annotations

import ast
from pathlib import Path


def _is_bootstrap_call(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Expr):
        return False
    value = stmt.value
    return isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "_bootstrap_legacy_import_alias"


def _contains_chatbot_absolute_import(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.ImportFrom):
        return (stmt.module or "").startswith("chatbot.")
    if isinstance(stmt, ast.Import):
        return any(alias.name.startswith("chatbot.") for alias in stmt.names)
    return False


def test_server_fastapi_bootstraps_chatbot_alias_before_chatbot_imports() -> None:
    source = Path(
        "/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/server_fastapi.py"
    ).read_text(encoding="utf-8")
    module = ast.parse(source)

    bootstrap_index = next(
        (index for index, stmt in enumerate(module.body) if _is_bootstrap_call(stmt)),
        None,
    )
    assert bootstrap_index is not None

    first_chatbot_import_index = next(
        (
            index
            for index, stmt in enumerate(module.body)
            if _contains_chatbot_absolute_import(stmt)
        ),
        None,
    )
    assert first_chatbot_import_index is not None
    assert bootstrap_index < first_chatbot_import_index


def test_server_fastapi_bootstraps_workspace_src_alias() -> None:
    source = Path(
        "/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/server_fastapi.py"
    ).read_text(encoding="utf-8")

    assert 'importlib.import_module("src")' in source
    assert 'importlib.import_module("chatbot.src")' not in source
