from __future__ import annotations

import difflib
from pathlib import Path


CHAT_AUTH_BOOTSTRAP_PATH = "/api/chat/auth-token"


def build_backend_route_patch(
    *,
    strategy: str,
    target_file: str,
    source_lines: list[str],
) -> str:
    updated_lines = build_backend_route_updated_lines(
        strategy=strategy,
        source_lines=source_lines,
    )
    diff = difflib.unified_diff(
        source_lines,
        updated_lines,
        fromfile=f"a/{target_file}",
        tofile=f"b/{target_file}",
    )
    return "".join(diff)


def build_backend_route_updated_lines(
    *,
    strategy: str,
    source_lines: list[str],
) -> list[str]:
    if strategy == "django":
        return _build_django_route_updated_lines(source_lines)
    if strategy == "flask":
        return _build_flask_route_updated_lines(source_lines)
    if strategy == "fastapi":
        return _build_fastapi_route_updated_lines(source_lines)
    return list(source_lines)


def _build_django_route_updated_lines(source_lines: list[str]) -> list[str]:
    updated = list(source_lines)
    import_line = "from backend.chat_auth import chat_auth_token\n"
    route_line = f'    path("{CHAT_AUTH_BOOTSTRAP_PATH.lstrip("/")}", chat_auth_token),\n'
    if import_line not in updated:
        insert_at = 0
        while insert_at < len(updated) and updated[insert_at].startswith(("from ", "import ")):
            insert_at += 1
        updated.insert(insert_at, import_line)
    if route_line not in updated:
        for index, line in enumerate(updated):
            if "urlpatterns" in line and "[" in line:
                updated.insert(index + 1, route_line)
                break
    return updated


def _build_flask_route_updated_lines(source_lines: list[str]) -> list[str]:
    updated = list(source_lines)
    import_line = "from backend.chat_auth import chat_auth_bp\n"
    register_line = "app.register_blueprint(chat_auth_bp)\n"
    if import_line not in updated:
        insert_at = 0
        while insert_at < len(updated) and updated[insert_at].startswith(("from ", "import ")):
            insert_at += 1
        updated.insert(insert_at, import_line)
    if register_line not in updated:
        for index, line in enumerate(updated):
            if "app.register_blueprint(" in line:
                updated.insert(index, register_line)
                break
        else:
            updated.append(register_line)
    return updated


def _build_fastapi_route_updated_lines(source_lines: list[str]) -> list[str]:
    updated = list(source_lines)
    import_line = "from backend.chat_auth import router as onboarding_chat_router\n"
    include_line = "app.include_router(onboarding_chat_router)\n"
    if import_line not in updated:
        insert_at = 0
        while insert_at < len(updated) and updated[insert_at].startswith(("from ", "import ")):
            insert_at += 1
        updated.insert(insert_at, import_line)
    if include_line not in updated:
        for index, line in enumerate(updated):
            if "app.include_router(" in line:
                updated.insert(index, include_line)
                break
        else:
            updated.append(include_line)
    return updated


def choose_backend_route_target(targets: list[str]) -> str | None:
    normalized = [str(item).strip() for item in targets if str(item).strip()]
    if not normalized:
        return None
    return sorted(normalized, key=lambda item: (len(Path(item).parts), item))[0]
