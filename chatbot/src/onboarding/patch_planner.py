from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any


def build_patch_proposal(
    *,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
) -> dict[str, Any]:
    target_files: list[dict[str, str]] = []
    for target in _select_target_candidates(codebase_map.get("candidate_edit_targets") or []):
        target_files.append(
            {
                "path": str(target.get("path") or ""),
                "reason": str(target.get("reason") or ""),
                "intent": _infer_intent(
                    path=str(target.get("path") or ""),
                    analysis=analysis,
                    recommended_outputs=recommended_outputs,
                ),
            }
        )

    supporting_generated_files = _supporting_files(recommended_outputs)
    return {
        "target_files": target_files,
        "supporting_generated_files": supporting_generated_files,
        "recommended_outputs": recommended_outputs,
        "analysis_summary": {
            "auth_style": ((analysis.get("auth") or {}).get("auth_style") or "unknown"),
            "frontend_mount_points": analysis.get("frontend_mount_points") or [],
            "route_prefixes": analysis.get("route_prefixes") or [],
        },
    }


def _select_target_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    views = [item for item in candidates if str(item.get("path") or "").lower().endswith("views.py")]
    urls = [item for item in candidates if str(item.get("path") or "").lower().endswith("urls.py")]
    frontend = [
        item
        for item in candidates
        if str(item.get("path") or "").lower().endswith(("app.js", "app.jsx", "app.ts", "app.tsx", ".vue"))
    ]
    entrypoints = [
        item
        for item in candidates
        if str(item.get("path") or "").lower().endswith(("main.py", "app.py"))
    ]

    selected: list[dict[str, str]] = []
    for bucket in [views, urls, frontend, entrypoints]:
        preferred = _pick_preferred_candidate(bucket)
        if preferred is not None:
            selected.append(preferred)
    return selected


def _pick_preferred_candidate(candidates: list[dict[str, str]]) -> dict[str, str] | None:
    if not candidates:
        return None

    def score(item: dict[str, str]) -> tuple[int, int, str]:
        path = str(item.get("path") or "").lower()
        auth_score = 0
        if "/users/" in path or path.startswith("backend/users/"):
            auth_score += 4
        if "/auth" in path or "login" in path or "session" in path:
            auth_score += 3
        if path.endswith("foodshop/urls.py") or path.endswith("config/urls.py"):
            auth_score += 2
        if "/products/" in path or "/orders/" in path:
            auth_score -= 2
        return (-auth_score, len(path), path)

    return sorted(candidates, key=score)[0]


def write_patch_proposal(
    *,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
    output_path: str | Path,
) -> Path:
    payload = build_patch_proposal(
        analysis=analysis,
        codebase_map=codebase_map,
        recommended_outputs=recommended_outputs,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_unified_diff_draft(
    *,
    source_root: str | Path,
    generated_run_root: str | Path,
    proposal_path: str | Path,
    output_path: str | Path,
) -> Path:
    source = Path(source_root)
    proposal = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
    patch_chunks: list[str] = []

    for target in proposal.get("target_files") or []:
        relative = str(target.get("path") or "")
        source_file = source / relative
        source_lines = _read_text_or_empty(source_file)
        if relative.endswith("views.py"):
            updated_lines = source_lines + _build_python_stub_lines()
        elif relative.endswith("urls.py"):
            updated_lines = _build_url_registration_updated_lines(source_lines)
        elif relative.endswith("main.py"):
            updated_lines = _build_fastapi_registration_updated_lines(source_lines)
        elif relative.endswith("app.py"):
            updated_lines = _build_flask_registration_updated_lines(source_lines)
        elif _is_frontend_mount_target(relative):
            updated_lines = _build_frontend_mount_updated_lines(source_lines, relative)
        else:
            continue
        diff = difflib.unified_diff(
            source_lines,
            updated_lines,
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
        patch_chunks.append("".join(diff))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(patch_chunks), encoding="utf-8")
    return path


def _infer_intent(*, path: str, analysis: dict[str, Any], recommended_outputs: list[str]) -> str:
    lower = path.lower()
    if "views.py" in lower:
        return "extend backend auth/session handler for onboarding-compatible chat auth"
    if "urls.py" in lower:
        return "wire onboarding-related route entrypoint without touching the original source directly"
    if lower.endswith("main.py"):
        return "prepare FastAPI router registration draft for onboarding chat auth"
    if lower.endswith("app.py"):
        return "prepare Flask blueprint registration draft for onboarding chat auth"
    if lower.endswith(("app.js", "app.jsx", "app.tsx", "app.ts", ".vue")):
        return "prepare frontend chatbot mount draft for runtime-only integration review"
    if recommended_outputs:
        return f"support {recommended_outputs[0]} capability"
    return f"support auth style {((analysis.get('auth') or {}).get('auth_style') or 'unknown')}"


def _supporting_files(recommended_outputs: list[str]) -> list[str]:
    file_map = {
        "chat_auth": "files/backend/chat_auth.py",
        "order_adapter": "files/backend/order_adapter_client.py",
        "product_adapter": "files/backend/product_adapter_client.py",
        "frontend_patch": "patches/frontend_widget_mount.patch",
    }
    return [file_map[item] for item in recommended_outputs if item in file_map]


def _read_text_or_empty(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = f"{lines[-1]}\n"
    return lines


def _build_python_stub_lines() -> list[str]:
    return [
        "\n",
        "def onboarding_chat_auth_token(request):\n",
        '    """Generated onboarding stub for runtime-only integration."""\n',
        "    return None\n",
    ]


def _build_url_registration_stub_lines() -> list[str]:
    return [
        "\n",
        '# onboarding draft route registration\n',
        'path("api/chat/auth-token", onboarding_chat_auth_token),\n',
    ]


def _build_url_registration_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    import_line = "from users.views import onboarding_chat_auth_token\n"
    if import_line not in updated_lines:
        updated_lines = [import_line] + updated_lines
    updated_lines.extend(_build_url_registration_stub_lines())
    return updated_lines


def _build_fastapi_registration_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    import_line = "from backend.chat_auth import router as onboarding_chat_router\n"
    if import_line not in updated_lines:
        updated_lines = [import_line] + updated_lines
    include_line = "app.include_router(onboarding_chat_router)\n"
    if include_line not in updated_lines:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.extend(["\n", include_line])
    return updated_lines


def _build_flask_registration_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    import_line = "from backend.chat_auth import chat_auth_bp\n"
    if import_line not in updated_lines:
        updated_lines = [import_line] + updated_lines
    register_line = "app.register_blueprint(chat_auth_bp)\n"
    if register_line not in updated_lines:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.extend(["\n", register_line])
    return updated_lines


def _is_frontend_mount_target(relative: str) -> bool:
    lower = relative.lower()
    return lower.endswith(("app.js", "app.jsx", "app.ts", "app.tsx", ".vue"))


def _build_frontend_mount_updated_lines(source_lines: list[str], relative: str) -> list[str]:
    updated_lines = list(source_lines)
    lower = relative.lower()
    if lower.endswith(".vue"):
        return _build_vue_mount_updated_lines(updated_lines)
    return _build_react_mount_updated_lines(updated_lines)


def _build_react_mount_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    import_line = 'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
    if import_line not in updated_lines:
        updated_lines = [import_line] + updated_lines
    widget_line = "  <SharedChatbotWidget />\n"
    if widget_line not in updated_lines:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.extend(["\n", widget_line])
    return updated_lines


def _build_vue_mount_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    widget_line = "  <SharedChatbotWidget />\n"
    if widget_line not in updated_lines:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.extend(["\n", "<template>\n", widget_line, "</template>\n"])
    return updated_lines
