from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CompilePreflightResult(BaseModel):
    passed: bool
    failure_code: str | None = None
    failure_summary: str | None = None
    related_files: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


_BANNED_PATTERNS = ("ecommerce.backend", "SessionLocal")
_IGNORED_RUNTIME_DIR_NAMES = {
    "tests",
    "test",
    "benchmark",
    "bench",
    "benchmarks",
    "eval",
    "migrations",
    "__pycache__",
}


def run_chatbot_compile_preflight(chatbot_workspace: Path) -> CompilePreflightResult:
    workspace = Path(chatbot_workspace)
    banned_scan = _scan_for_banned_imports(workspace)
    if banned_scan is not None:
        return banned_scan
    return _run_server_fastapi_import_smoke(workspace)


def _scan_for_banned_imports(workspace: Path) -> CompilePreflightResult | None:
    matches: list[dict[str, str]] = []
    related_files: set[str] = set()

    for file_path in _iter_runtime_source_files(workspace):
        content = _read_source(file_path)
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError as exc:
            relative_path = file_path.relative_to(workspace).as_posix()
            return CompilePreflightResult(
                passed=False,
                failure_code="chatbot_runtime_source_syntax_error",
                failure_summary=f"syntax error in runtime source: {relative_path}: {exc.msg}",
                related_files=[relative_path],
                details={
                    "filename": relative_path,
                    "lineno": exc.lineno,
                    "offset": exc.offset,
                    "text": exc.text,
                },
            )
        matched_patterns = _find_banned_import_patterns(tree)
        if not matched_patterns:
            continue
        relative_path = file_path.relative_to(workspace).as_posix()
        related_files.add(relative_path)
        for pattern in matched_patterns:
            matches.append({"pattern": pattern, "file": relative_path})

    if not matches:
        return None

    summary_patterns = ", ".join(sorted({match["pattern"] for match in matches}))
    return CompilePreflightResult(
        passed=False,
        failure_code="banned_import_detected",
        failure_summary=f"banned import detected: {summary_patterns}",
        related_files=sorted(related_files),
        details={
            "banned_patterns": list(_BANNED_PATTERNS),
            "matches": matches,
        },
    )


def _iter_runtime_source_files(workspace: Path) -> list[Path]:
    files: list[Path] = []
    server_fastapi_path = workspace / "server_fastapi.py"
    if server_fastapi_path.exists():
        files.append(server_fastapi_path)

    src_root = workspace / "src"
    if src_root.exists():
        for file_path in sorted(src_root.rglob("*.py")):
            if _is_ignored_runtime_path(file_path.relative_to(workspace)):
                continue
            files.append(file_path)
    return files


def _is_ignored_runtime_path(relative_path: Path) -> bool:
    parts = relative_path.parts
    if any(part in _IGNORED_RUNTIME_DIR_NAMES for part in parts[:-1]):
        return True
    return relative_path.name.startswith("test_")


def _read_source(file_path: Path) -> str:
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="utf-8", errors="ignore")


def _find_banned_import_patterns(tree: ast.AST) -> list[str]:
    matched_patterns: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name
                if module_name.startswith("ecommerce.backend"):
                    matched_patterns.add("ecommerce.backend")
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name.startswith("ecommerce.backend"):
                matched_patterns.add("ecommerce.backend")
                for alias in node.names:
                    if alias.name == "SessionLocal":
                        matched_patterns.add("SessionLocal")
    return sorted(matched_patterns)


def _run_server_fastapi_import_smoke(workspace: Path) -> CompilePreflightResult:
    command = [
        sys.executable,
        "-c",
        "import server_fastapi as module; assert getattr(module, 'app', None) is not None",
    ]
    env = os.environ.copy()
    result = subprocess.run(
        command,
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return CompilePreflightResult(
            passed=True,
            failure_summary=None,
            related_files=[],
            details={
                "import_smoke": "passed",
                "python_executable": sys.executable,
            },
        )

    return CompilePreflightResult(
        passed=False,
        failure_code="chatbot_runtime_import_failed",
        failure_summary="server_fastapi import failed",
        related_files=["server_fastapi.py"] if (workspace / "server_fastapi.py").exists() else [],
        details={
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
