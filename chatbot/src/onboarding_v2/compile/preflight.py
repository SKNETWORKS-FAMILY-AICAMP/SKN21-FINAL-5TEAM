from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from chatbot.src.onboarding_v2.validation.backend_runtime import (
    _resolve_backend_root,
    build_backend_subprocess_env,
)


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
_HOST_IMPORT_LAUNCHER_NAME = ".onboarding_host_import_smoke.py"


def run_chatbot_compile_preflight(
    chatbot_workspace: Path,
    *,
    scan_paths: list[str] | None = None,
) -> CompilePreflightResult:
    workspace = Path(chatbot_workspace)
    banned_scan = _scan_for_banned_imports(workspace, scan_paths=scan_paths)
    if banned_scan is not None:
        return banned_scan
    return _run_server_fastapi_import_smoke(workspace)


def run_flask_host_import_smoke(
    host_workspace: Path,
    *,
    entrypoint: str,
) -> CompilePreflightResult:
    workspace = Path(host_workspace).resolve()
    backend_root = _resolve_backend_root(workspace)
    entrypoint_path = (backend_root / entrypoint).resolve()
    if not entrypoint_path.exists():
        return CompilePreflightResult(
            passed=False,
            failure_code="host_backend_import_failed",
            failure_summary="host backend entrypoint missing",
            related_files=[entrypoint],
            details={
                "framework": "flask",
                "entrypoint": entrypoint,
                "command": [],
                "returncode": None,
                "stdout": "",
                "stderr": f"missing entrypoint: {entrypoint_path}",
            },
        )

    launcher_path = backend_root / _HOST_IMPORT_LAUNCHER_NAME
    launcher_path.write_text(
        _build_flask_host_import_launcher(backend_root=backend_root, entrypoint=entrypoint),
        encoding="utf-8",
    )
    command = [sys.executable, str(launcher_path)]
    env = build_backend_subprocess_env(
        backend_root=backend_root,
        extra_env={
            "ONBOARDING_VALIDATION": "1",
            "ONBOARDING_VALIDATION_SKIP_DB_INIT": "1",
        },
    )
    try:
        result = subprocess.run(
            command,
            cwd=backend_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        try:
            launcher_path.unlink()
        except FileNotFoundError:
            pass

    if result.returncode == 0:
        return CompilePreflightResult(
            passed=True,
            failure_summary=None,
            related_files=[],
            details={
                "framework": "flask",
                "entrypoint": entrypoint,
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )

    related_files = _extract_backend_related_files(
        text=f"{result.stdout}\n{result.stderr}",
        backend_root=backend_root,
        entrypoint=entrypoint,
    )
    return CompilePreflightResult(
        passed=False,
        failure_code="host_backend_import_failed",
        failure_summary="host backend import failed",
        related_files=related_files,
        details={
            "framework": "flask",
            "entrypoint": entrypoint,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )


def _scan_for_banned_imports(
    workspace: Path,
    *,
    scan_paths: list[str] | None = None,
) -> CompilePreflightResult | None:
    matches: list[dict[str, str]] = []
    related_files: set[str] = set()

    for file_path in _iter_runtime_source_files(workspace, scan_paths=scan_paths):
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


def _iter_runtime_source_files(
    workspace: Path,
    *,
    scan_paths: list[str] | None = None,
) -> list[Path]:
    if scan_paths:
        files: list[Path] = []
        seen: set[Path] = set()
        for relative_path_str in scan_paths:
            relative_path = Path(relative_path_str)
            candidate = workspace / relative_path
            if candidate.is_dir():
                for file_path in sorted(candidate.rglob("*.py")):
                    try:
                        file_relative = file_path.relative_to(workspace)
                    except ValueError:
                        continue
                    if _is_ignored_runtime_path(file_relative):
                        continue
                    if file_path not in seen:
                        seen.add(file_path)
                        files.append(file_path)
                continue
            if candidate.suffix != ".py" or not candidate.exists():
                continue
            if candidate not in seen:
                seen.add(candidate)
                files.append(candidate)
        return files

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


def _build_flask_host_import_launcher(*, backend_root: Path, entrypoint: str) -> str:
    return f"""from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path({str(backend_root)!r})
ENTRYPOINT_PATH = BACKEND_ROOT / {entrypoint!r}

os.environ.setdefault("ONBOARDING_VALIDATION", "1")
os.environ.setdefault("ONBOARDING_VALIDATION_SKIP_DB_INIT", "1")
sys.path.insert(0, str(BACKEND_ROOT))


def _noop(*args, **kwargs):
    return None


spec = importlib.util.spec_from_file_location(
    "onboarding_compile_host_entrypoint",
    ENTRYPOINT_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to load Flask entrypoint: {{ENTRYPOINT_PATH}}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

if os.environ.get("ONBOARDING_VALIDATION_SKIP_DB_INIT") == "1":
    for hook_name in ("init_db_with_retry", "init_db"):
        candidate = getattr(module, hook_name, None)
        if callable(candidate):
            setattr(module, hook_name, _noop)

create_app = getattr(module, "create_app", None)
if callable(create_app):
    app = create_app()
else:
    app = getattr(module, "app", None)

if app is None:
    raise RuntimeError("Flask entrypoint did not expose app or create_app")
"""


def _extract_backend_related_files(
    *,
    text: str,
    backend_root: Path,
    entrypoint: str,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(relative_path: str) -> None:
        normalized = str(relative_path or "").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered.append(normalized)

    _add(entrypoint)
    for match in re.finditer(r'File "([^"]+)"', text):
        raw_path = match.group(1)
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (backend_root / candidate).resolve()
        try:
            relative_path = candidate.relative_to(backend_root).as_posix()
        except ValueError:
            continue
        if relative_path == _HOST_IMPORT_LAUNCHER_NAME:
            continue
        _add(relative_path)

    chat_auth_path = backend_root / "chat_auth.py"
    if "chat_auth.py" in text and chat_auth_path.exists():
        _add("chat_auth.py")
    return ordered
