from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .integration_contracts import (
    BackendContract,
    FrontendContract,
    SiteIntegrationContract,
)


TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}
SKIP_PATH_PARTS = {".venv", "venv", "site-packages", "node_modules", "__pycache__"}
ORDER_BRIDGE_TOOL_NAMES = [
    "list_orders",
    "get_order_status",
    "cancel",
    "refund",
    "exchange",
]


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _should_skip_path(path: Path, root: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        relative_parts = path.parts
    return any(part in SKIP_PATH_PARTS for part in relative_parts)


def _iter_text_files(root: Path):
    for file_path in root.rglob("*"):
        if _should_skip_path(file_path, root):
            continue
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


def _find_route_literal_files(root: Path, canonical: str, *aliases: str) -> list[str]:
    results: list[str] = []
    candidates = (canonical, *aliases)
    for file_path, text in _iter_text_files(root):
        if any(candidate in text for candidate in candidates):
            results.append(_relative_posix(file_path, root))
    return sorted(dict.fromkeys(results))


def _find_frontend_mount_points(root: Path) -> list[str]:
    mounts: list[str] = []
    for file_path, text in _iter_text_files(root):
        if file_path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        if "Chatbot" in text or "ChatBot" in text:
            mounts.append(_relative_posix(file_path, root))
    return mounts


def _find_frontend_app_shell_path(root: Path) -> str | None:
    candidates: list[str] = []
    for file_path, text in _iter_text_files(root):
        if file_path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        rel = _relative_posix(file_path, root)
        if file_path.stem.lower() == "app":
            candidates.append(rel)
            continue
        if "<router-view" in text or "<Routes" in text or "function App" in text or "export default function App" in text:
            candidates.append(rel)
    normalized = sorted(dict.fromkeys(candidates))
    return normalized[0] if normalized else None


def _find_auth_source_paths(root: Path, *, login_entrypoints: list[str], me_entrypoints: list[str]) -> list[str]:
    paths = [entrypoint.split(":", 1)[0] for entrypoint in [*login_entrypoints, *me_entrypoints]]
    return sorted(dict.fromkeys(path for path in paths if path))


def _find_api_client_paths(root: Path) -> list[str]:
    candidates: list[str] = []
    for file_path, text in _iter_text_files(root):
        if file_path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        if "fetch(" in text or "axios" in text:
            candidates.append(_relative_posix(file_path, root))
    return sorted(dict.fromkeys(candidates))


def _build_integration_contract(
    *,
    root: Path,
    backend_framework: str,
    frontend_framework: str,
    auth_style: str,
    login_entrypoints: list[str],
    me_entrypoints: list[str],
    backend_route_targets: list[str],
    frontend_mount_targets: list[str],
    product_api: list[str],
    order_api: list[str],
) -> dict:
    app_shell_path = _find_frontend_app_shell_path(root)
    mount_targets = frontend_mount_targets or ([app_shell_path] if app_shell_path else [])
    contract = SiteIntegrationContract(
        site=root.name,
        backend=BackendContract(
            framework=backend_framework,
            auth_style=auth_style,
            route_registration_points=backend_route_targets,
            auth_source_paths=_find_auth_source_paths(
                root,
                login_entrypoints=login_entrypoints,
                me_entrypoints=me_entrypoints,
            ),
            user_resolver_paths=[entrypoint.split(":", 1)[0] for entrypoint in me_entrypoints],
        ),
        frontend=FrontendContract(
            framework=frontend_framework,
            app_shell_path=app_shell_path or (mount_targets[0] if mount_targets else "frontend/src/App.js"),
            router_boundary_path=app_shell_path,
            api_client_paths=_find_api_client_paths(root),
            widget_mount_points=mount_targets,
        ),
        product_adapter={
            "enabled": bool(product_api),
            "api_base_paths": product_api,
        },
        order_adapter={
            "enabled": bool(order_api),
            "tool_names": ORDER_BRIDGE_TOOL_NAMES if order_api else [],
            "api_base_paths": order_api,
        },
    )
    return contract.model_dump(mode="json")


def _build_order_bridge_targets(root: Path, order_api: list[str]) -> list[str]:
    targets: list[str] = []
    for api_base in order_api:
        normalized = str(api_base).strip()
        if not normalized:
            continue
        aliases = {
            normalized,
            normalized.lstrip("/"),
            normalized.rstrip("/"),
            normalized.strip("/"),
            f'url_prefix="{normalized.rstrip("/")}"',
            f"url_prefix='{normalized.rstrip('/')}'",
        }
        targets.extend(_find_route_literal_files(root, normalized, *sorted(aliases)))

    if targets:
        return sorted(dict.fromkeys(targets))

    for file_path, _text in _iter_text_files(root):
        rel = _relative_posix(file_path, root)
        if rel.startswith("backend/") and "order" in rel.lower():
            targets.append(rel)
    return sorted(dict.fromkeys(targets))


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


def _find_backend_route_targets(
    root: Path,
    backend_framework: str,
    *,
    login_entrypoints: list[str] | None = None,
    me_entrypoints: list[str] | None = None,
) -> list[str]:
    login_entrypoints = login_entrypoints or []
    me_entrypoints = me_entrypoints or []
    targets: list[str] = []
    auth_source_paths = _find_auth_source_paths(
        root,
        login_entrypoints=login_entrypoints,
        me_entrypoints=me_entrypoints,
    )
    auth_module_names = {
        Path(path).parent.name
        for path in auth_source_paths
        if Path(path).parent.name
    }
    for file_path, text in _iter_text_files(root):
        if file_path.suffix != ".py":
            continue
        rel = _relative_posix(file_path, root)
        if backend_framework == "django":
            if not any(marker in text for marker in ("urlpatterns", "path(", "re_path(")):
                continue
            has_auth_include = any(
                re.search(
                    rf'include\(\s*["\']{re.escape(module_name)}(?:\.[^"\']+)?["\']',
                    text,
                )
                for module_name in auth_module_names
            )
            has_direct_auth_route = bool(
                re.search(
                    r'path\(\s*["\'][^"\']*["\']\s*,\s*(?:views\.)?(login|me|logout)\b',
                    text,
                )
            )
            if has_auth_include or has_direct_auth_route:
                targets.append(rel)
        elif backend_framework == "flask" and "register_blueprint(" in text:
            targets.append(rel)
        elif backend_framework == "fastapi" and ("include_router(" in text or "FastAPI(" in text):
            targets.append(rel)
    return sorted(dict.fromkeys(targets))


def _find_tool_registry_targets(root: Path) -> list[str]:
    targets: list[str] = []
    for file_path, text in _iter_text_files(root):
        if file_path.suffix != ".py":
            continue
        rel = _relative_posix(file_path, root)
        if "def login(" in text or "def me(" in text or "session[" in text or "request.COOKIES" in text:
            targets.append(rel)
    return sorted(dict.fromkeys(targets))


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


def _resolve_django_auth_routes(root: Path) -> dict[str, str | None]:
    url_files: list[tuple[Path, str]] = [
        (file_path, text)
        for file_path, text in _iter_text_files(root)
        if file_path.suffix == ".py" and file_path.name == "urls.py"
    ]
    module_map = {
        _relative_posix(file_path.with_suffix(""), root).replace("/", "."): file_path
        for file_path, _ in url_files
    }
    direct_routes: dict[Path, dict[str, str]] = {}
    include_routes: dict[Path, list[tuple[str, Path]]] = {}
    unresolved_auth_prefixes: list[str] = []

    for file_path, text in url_files:
        direct: dict[str, str] = {}
        for route, function_name in re.findall(
            r'path\(\s*["\']([^"\']+)["\']\s*,\s*(?:views\.)?(login|me|logout)\b',
            text,
        ):
            direct[function_name] = route
        direct_routes[file_path] = direct

        includes: list[tuple[str, Path]] = []
        for prefix, module_name in re.findall(
            r'path\(\s*["\']([^"\']+)["\']\s*,\s*include\(\s*["\']([^"\']+)["\']\s*\)',
            text,
        ):
            target = _resolve_module_path(module_name, module_map)
            if target is not None:
                includes.append((prefix, target))
            elif any(token in module_name for token in ("users", "auth")):
                unresolved_auth_prefixes.append(prefix)
        include_routes[file_path] = includes

    parent_routes: dict[Path, list[tuple[Path, str]]] = {file_path: [] for file_path, _ in url_files}
    for parent_path, includes in include_routes.items():
        for prefix, child_path in includes:
            parent_routes.setdefault(child_path, []).append((parent_path, prefix))

    login_route = _first_resolved_route("login", direct_routes, parent_routes)
    me_route = _first_resolved_route("me", direct_routes, parent_routes)
    logout_route = _first_resolved_route("logout", direct_routes, parent_routes)
    if login_route is None and unresolved_auth_prefixes:
        login_route = _join_route_segments(sorted(dict.fromkeys(unresolved_auth_prefixes))[0], "login/")
    if me_route is None and unresolved_auth_prefixes:
        me_route = _join_route_segments(sorted(dict.fromkeys(unresolved_auth_prefixes))[0], "me/")
    return {
        "login_route": login_route,
        "me_route": me_route,
        "logout_route": logout_route,
        "route_source": "django_urlpatterns" if any((login_route, me_route, logout_route)) else None,
    }


def _resolve_flask_auth_routes(root: Path) -> dict[str, str | None]:
    auth_prefixes = [prefix for prefix in _find_route_prefixes(root) if "auth" in prefix]
    if not auth_prefixes:
        return {
            "login_route": None,
            "me_route": None,
            "logout_route": None,
            "route_source": None,
        }
    prefix = auth_prefixes[0]
    return {
        "login_route": _join_route_segments(prefix, "login"),
        "me_route": _join_route_segments(prefix, "me"),
        "logout_route": _join_route_segments(prefix, "logout"),
        "route_source": "flask_blueprint_routes",
    }


def _resolve_module_path(module_name: str, module_map: dict[str, Path]) -> Path | None:
    normalized = module_name.strip()
    if normalized in module_map:
        return module_map[normalized]
    suffix = f".{normalized}"
    for candidate_module, candidate_path in module_map.items():
        if candidate_module.endswith(suffix):
            return candidate_path
    return None


def _first_resolved_route(
    function_name: str,
    direct_routes: dict[Path, dict[str, str]],
    parent_routes: dict[Path, list[tuple[Path, str]]],
) -> str | None:
    matches: list[str] = []
    for file_path, routes in direct_routes.items():
        relative = routes.get(function_name)
        if not relative:
            continue
        for prefix in _iter_route_prefixes(file_path, parent_routes):
            matches.append(_join_route_segments(prefix, relative))
    normalized = sorted(dict.fromkeys(matches))
    return normalized[0] if normalized else None


def _iter_route_prefixes(
    file_path: Path,
    parent_routes: dict[Path, list[tuple[Path, str]]],
    prefix: str = "",
    visited: tuple[Path, ...] = (),
) -> Iterable[str]:
    parents = parent_routes.get(file_path) or []
    current_visited = (*visited, file_path)
    if not parents:
        yield prefix
        return
    for parent_path, parent_prefix in parents:
        if parent_path in current_visited:
            continue
        next_prefix = _join_route_segments(parent_prefix, prefix)
        yield from _iter_route_prefixes(parent_path, parent_routes, next_prefix, current_visited)


def _join_route_segments(prefix: str, relative: str) -> str:
    cleaned = "/".join(
        part.strip("/")
        for part in [prefix or "", relative or ""]
        if part is not None and part.strip("/")
    )
    if not cleaned:
        return "/"
    return f"/{cleaned}/"


def _find_login_fields(root: Path, login_entrypoints: list[str]) -> list[str]:
    candidates: list[str] = []
    for entrypoint in login_entrypoints:
        path_str = entrypoint.split(":", 1)[0]
        file_path = root / path_str
        if not file_path.exists():
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r'get\(\s*["\']email["\']', text):
            candidates.append("email")
        if re.search(r'get\(\s*["\']username["\']', text):
            candidates.append("username")
        if re.search(r'get\(\s*["\']password["\']', text):
            candidates.append("password")
    ordered = [field for field in ("email", "username", "password") if field in candidates]
    return ordered


def _infer_session_check_shape(root: Path, *, me_entrypoints: list[str], login_entrypoints: list[str]) -> dict[str, str] | None:
    for entrypoint in me_entrypoints:
        path_str = entrypoint.split(":", 1)[0]
        file_path = root / path_str
        if not file_path.exists():
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        if '"authenticated"' in text and '"user"' in text:
            return {"mode": "authenticated_user"}
    for entrypoint in login_entrypoints:
        path_str = entrypoint.split(":", 1)[0]
        file_path = root / path_str
        if not file_path.exists():
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        if '"user"' in text or "'user'" in text:
            return {"mode": "login_response_user"}
    return None


def _infer_api_response_shape(root: Path, route: str) -> dict[str, str] | None:
    route_files = _find_route_literal_files(root, route, route.lstrip("/"), f'url_prefix="{route.rstrip("/")}"')
    candidate_texts: list[str] = []
    for relative in route_files:
        path = root / relative
        if path.exists():
            candidate_texts.append(path.read_text(encoding="utf-8", errors="ignore"))
    if route.endswith("/api/products/"):
        wrapper_key = "products"
    elif route.endswith("/api/orders/"):
        wrapper_key = "orders"
    else:
        wrapper_key = "items"
    combined = "\n".join(candidate_texts)
    if re.search(rf'jsonify\(\s*\{{\s*["\']{wrapper_key}["\']\s*:', combined):
        return {"mode": "object_array", "key": wrapper_key}
    if "Response(list(" in combined or re.search(r"payload\s*=\s*\[", combined) and "Response(payload)" in combined:
        return {"mode": "root_array"}
    all_text = "\n".join(text for _, text in _iter_text_files(root))
    if re.search(rf'jsonify\(\s*\{{\s*["\']{wrapper_key}["\']\s*:', all_text):
        return {"mode": "object_array", "key": wrapper_key}
    if "Response(list(" in all_text or re.search(r"payload\s*=\s*\[", all_text) and "Response(payload)" in all_text:
        return {"mode": "root_array"}
    return None


def analyze_site(site_root: str | Path) -> dict:
    root = Path(site_root)
    login_entrypoints = _find_function_entrypoints(root, r"^def\s+(login)\s*\(")
    me_entrypoints = _find_function_entrypoints(root, r"^def\s+(me)\s*\(")
    backend_framework = _detect_backend_framework(root)
    frontend_framework = _detect_frontend_framework(root)
    auth_signals = _collect_auth_signals(root)
    if backend_framework == "django":
        auth_routes = _resolve_django_auth_routes(root)
    elif backend_framework == "flask":
        auth_routes = _resolve_flask_auth_routes(root)
    else:
        auth_routes = {"login_route": None, "me_route": None, "logout_route": None, "route_source": None}
    login_fields = _find_login_fields(root, login_entrypoints)
    session_check_shape = _infer_session_check_shape(root, me_entrypoints=me_entrypoints, login_entrypoints=login_entrypoints)
    product_api = _find_route_literals(root, "/api/products/", "api/products/", 'url_prefix="/api/products"')
    order_api = _find_route_literals(root, "/api/orders/", "api/orders/", 'url_prefix="/api/orders"')
    backend_route_targets = _find_backend_route_targets(
        root,
        backend_framework,
        login_entrypoints=login_entrypoints,
        me_entrypoints=me_entrypoints,
    )
    frontend_mount_targets = _find_frontend_mount_points(root)
    tool_registry_targets = _find_tool_registry_targets(root)
    order_bridge_targets = _build_order_bridge_targets(root, order_api)
    integration_contract = _build_integration_contract(
        root=root,
        backend_framework=backend_framework,
        frontend_framework=frontend_framework,
        auth_style=_infer_auth_style(auth_signals, backend_framework),
        login_entrypoints=login_entrypoints,
        me_entrypoints=me_entrypoints,
        backend_route_targets=backend_route_targets,
        frontend_mount_targets=frontend_mount_targets,
        product_api=product_api,
        order_api=order_api,
    )

    return {
        "auth": {
            "login_entrypoints": login_entrypoints,
            "me_entrypoints": me_entrypoints,
            "auth_style": integration_contract["backend"]["auth_style"],
            "signals": auth_signals,
            "login_fields": login_fields,
            "session_check_shape": session_check_shape,
            **auth_routes,
        },
        "framework": {
            "backend": backend_framework,
            "frontend": frontend_framework,
        },
        "backend_strategy": backend_framework,
        "frontend_strategy": frontend_framework,
        "backend_entrypoints": _find_backend_entrypoints(root, backend_framework),
        "backend_route_targets": backend_route_targets,
        "route_prefixes": _find_route_prefixes(root),
        "product_api": product_api,
        "product_api_shape": _infer_api_response_shape(root, product_api[0]) if product_api else None,
        "order_api": order_api,
        "order_api_shape": _infer_api_response_shape(root, order_api[0]) if order_api else None,
        "order_bridge_targets": order_bridge_targets,
        "frontend_mount_points": frontend_mount_targets,
        "frontend_mount_targets": frontend_mount_targets,
        "tool_registry_targets": tool_registry_targets,
        "integration_contract": integration_contract,
    }
