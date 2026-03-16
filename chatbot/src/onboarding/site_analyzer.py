from __future__ import annotations

import re
from pathlib import Path


TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_text_files(root: Path):
    for file_path in root.rglob("*"):
        if file_path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        yield file_path, text


def _find_function_entrypoints(root: Path, pattern: str) -> list[str]:
    entrypoints: list[str] = []
    for file_path, text in _iter_text_files(root):
        if file_path.suffix != ".py":
            continue
        if not re.search(pattern, text, flags=re.MULTILINE):
            continue

        for match in re.finditer(pattern, text, flags=re.MULTILINE):
            entrypoints.append(f"{_relative_posix(file_path, root)}:{match.group(1)}")
    return entrypoints


def _find_route_literals(root: Path, canonical: str, *aliases: str) -> list[str]:
    results: list[str] = []
    candidates = (canonical, *aliases)
    for _, text in _iter_text_files(root):
        if any(candidate in text for candidate in candidates):
            results.append(canonical)
    return results[:1]


def _find_frontend_mount_points(root: Path) -> list[str]:
    mounts: list[str] = []
    for file_path, text in _iter_text_files(root):
        if file_path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        if "Chatbot" in text or "ChatBot" in text:
            mounts.append(_relative_posix(file_path, root))
    return mounts


def _detect_backend_framework(root: Path) -> str:
    combined = "\n".join(text for _, text in _iter_text_files(root) if _.suffix == ".py")
    if "from fastapi import" in combined or "FastAPI(" in combined or "APIRouter(" in combined:
        return "fastapi"
    if "from flask import" in combined or "Flask(" in combined or "Blueprint(" in combined:
        return "flask"
    if "from django." in combined or "urlpatterns" in combined or "path(" in combined:
        return "django"
    return "unknown"


def _detect_frontend_framework(root: Path) -> str:
    has_vue = any(path.suffix == ".vue" for path, _ in _iter_text_files(root))
    if has_vue:
        return "vue"

    for path, text in _iter_text_files(root):
        if path.suffix in {".js", ".jsx", ".ts", ".tsx"} and ("return <" in text or "React" in text or "function App" in text):
            return "react"
    return "unknown"


def _find_backend_entrypoints(root: Path, backend_framework: str) -> list[str]:
    entrypoints: list[str] = []
    for file_path, text in _iter_text_files(root):
        if file_path.suffix != ".py":
            continue
        rel = _relative_posix(file_path, root)
        if backend_framework == "flask" and ("Flask(" in text or "create_app(" in text):
            entrypoints.append(rel)
        elif backend_framework == "fastapi" and ("FastAPI(" in text or "include_router(" in text):
            entrypoints.append(rel)
    return sorted(dict.fromkeys(entrypoints))


def _find_route_prefixes(root: Path) -> list[str]:
    prefixes: list[str] = []
    for _, text in _iter_text_files(root):
        if "url_prefix=" in text:
            prefixes.extend(re.findall(r'url_prefix\s*=\s*["\']([^"\']+)["\']', text))
        if "include_router(" in text and "prefix=" in text:
            prefixes.extend(re.findall(r'prefix\s*=\s*["\']([^"\']+)["\']', text))
    return sorted(dict.fromkeys(prefixes))


def _collect_auth_signals(root: Path) -> list[str]:
    signals: list[str] = []
    candidates = [
        ("session_token", "session_token"),
        ("request.COOKIES", "request.COOKIES"),
        ("session[", "session["),
        ("response.set_cookie", "response.set_cookie"),
        ("request.cookies.get", "request.cookies.get"),
        ("access_token", "access_token"),
        ("SessionToken", "SessionToken"),
    ]
    combined = "\n".join(text for _, text in _iter_text_files(root) if _.suffix == ".py")
    for needle, label in candidates:
        if needle in combined:
            signals.append(label)
    return signals


def _infer_auth_style(signals: list[str], backend_framework: str) -> str:
    signal_set = set(signals)
    if "session_token" in signal_set or "request.COOKIES" in signal_set or "SessionToken" in signal_set:
        return "session_cookie"
    if "session[" in signal_set:
        return "session"
    if "access_token" in signal_set or "response.set_cookie" in signal_set or "request.cookies.get" in signal_set:
        return "token_cookie"
    if backend_framework == "django":
        return "unknown"
    if backend_framework == "flask":
        return "unknown"
    if backend_framework == "fastapi":
        return "unknown"
    return "unknown"


def analyze_site(site_root: str | Path) -> dict:
    root = Path(site_root)
    login_entrypoints = _find_function_entrypoints(root, r"^def\s+(login)\s*\(")
    me_entrypoints = _find_function_entrypoints(root, r"^def\s+(me)\s*\(")
    backend_framework = _detect_backend_framework(root)
    frontend_framework = _detect_frontend_framework(root)
    auth_signals = _collect_auth_signals(root)

    return {
        "auth": {
            "login_entrypoints": login_entrypoints,
            "me_entrypoints": me_entrypoints,
            "auth_style": _infer_auth_style(auth_signals, backend_framework),
            "signals": auth_signals,
        },
        "framework": {
            "backend": backend_framework,
            "frontend": frontend_framework,
        },
        "backend_entrypoints": _find_backend_entrypoints(root, backend_framework),
        "route_prefixes": _find_route_prefixes(root),
        "product_api": _find_route_literals(root, "/api/products/", "api/products/", 'url_prefix="/api/products"'),
        "order_api": _find_route_literals(root, "/api/orders/", "api/orders/", 'url_prefix="/api/orders"'),
        "frontend_mount_points": _find_frontend_mount_points(root),
    }
