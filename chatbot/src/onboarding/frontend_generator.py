from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .shared_chatbot_assets import resolve_shared_chatbot_assets
from .shared_widget_runtime import build_default_react_shared_widget

DEFAULT_WIDGET_PATH = "frontend/src/chatbot/SharedChatbotWidget.jsx"
DEFAULT_VUE_WIDGET_PATH = "frontend/src/chatbot/SharedChatbotWidget.vue"
DEFAULT_WIDGET_CONTENT = build_default_react_shared_widget(resolve_shared_chatbot_assets("food"))
DEFAULT_VUE_WIDGET_CONTENT = """<script setup>
import { onMounted, ref } from "vue";

const status = ref("loading");
const accessToken = ref("");
const sharedWidgetHost = {
  authBootstrapPath: "/api/chat/auth-token",
  streamPath: "/api/v1/chat/stream",
  chatbotApiBase:
    (typeof window !== "undefined" && window.__CHATBOT_API_BASE__) ||
    (typeof process !== "undefined" &&
      process.env &&
      (process.env.REACT_APP_CHATBOT_API_BASE || process.env.NEXT_PUBLIC_CHATBOT_API_BASE)) ||
    "http://localhost:8100",
};

onMounted(async () => {
  try {
    const response = await fetch(sharedWidgetHost.authBootstrapPath, {
      method: "POST",
      credentials: "include",
    });
    const rawBody = await response.text();
    const payload = rawBody ? JSON.parse(rawBody) : {};
    if (!response.ok || !payload.authenticated) {
      status.value = "unauthenticated";
      return;
    }
    accessToken.value = payload.access_token || "";
    status.value = "authenticated";
  } catch (_error) {
    status.value = "error";
  }
});
</script>

<template>
  <div v-if="status === 'loading'" data-chatbot-status="loading">Connecting chat...</div>
  <div v-else-if="status === 'unauthenticated'" data-chatbot-status="unauthenticated">Login required for chat.</div>
  <div v-else-if="status === 'error'" data-chatbot-status="error">Chat is temporarily unavailable.</div>
  <div
    v-else
    data-chatbot-status="authenticated"
    :data-access-token="accessToken"
    :data-chatbot-api-base="sharedWidgetHost.chatbotApiBase"
  >
    Chatbot
  </div>
</template>
"""


def _prepare_frontend_widget_proposal(
    proposal: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if manifest:
        analysis = manifest.get("analysis") or {}
        manifest_proposal = analysis.get("frontend_widget_proposal")
        if isinstance(manifest_proposal, dict):
            merged.update(manifest_proposal)
        widget_path_override = analysis.get("frontend_widget_path")
        if isinstance(widget_path_override, str) and widget_path_override.strip():
            merged.setdefault("widget_path", widget_path_override)
    if proposal:
        merged.update(proposal)
    return merged


def _load_manifest_if_present(run_root: str | Path) -> dict[str, Any] | None:
    manifest_path = Path(run_root) / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _default_widget_path(frontend_strategy: str | None) -> str:
    return DEFAULT_VUE_WIDGET_PATH if frontend_strategy == "vue" else DEFAULT_WIDGET_PATH


def _normalize_widget_path(path: str | None, *, frontend_strategy: str | None = None) -> str:
    if not path:
        return _default_widget_path(frontend_strategy)
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(candidate.anchor)
        except (ValueError, IndexError):
            candidate = Path(*candidate.parts[1:]) if len(candidate.parts) > 1 else Path("")
    normalized = candidate.as_posix()
    if not normalized:
        return _default_widget_path(frontend_strategy)
    if normalized.startswith("frontend/src/"):
        return normalized
    if normalized.startswith("src/"):
        return f"frontend/{normalized}"
    if normalized.startswith("frontend/"):
        remainder = normalized.removeprefix("frontend/").lstrip("/")
        return f"frontend/src/{remainder}"
    return f"frontend/src/{normalized.lstrip('/')}"


def resolve_widget_path(
    *,
    proposal: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> str:
    merged = _prepare_frontend_widget_proposal(proposal, manifest)
    path = merged.get("widget_path")
    frontend_strategy = None
    if manifest:
        frontend_strategy = str((manifest.get("analysis") or {}).get("frontend_strategy") or "").strip() or None
    return _normalize_widget_path(str(path) if path else None, frontend_strategy=frontend_strategy)


def _prepare_widget_content(proposal: dict[str, Any]) -> str:
    explicit = proposal.get("content")
    if isinstance(explicit, str) and explicit.strip():
        return explicit if explicit.endswith("\n") else f"{explicit}\n"
    frontend_strategy = str(proposal.get("frontend_strategy") or "").strip().lower()
    widget_path = str(proposal.get("widget_path") or "").strip().lower()
    site_name = str(proposal.get("site") or "").strip().lower() or "food"
    imports = [
        str(item)
        for item in proposal.get("imports") or []
        if isinstance(item, str) and item.strip()
    ]
    component = proposal.get("component")
    component_str = str(component).strip() if component else ""

    lines: list[str] = []
    if imports:
        lines.extend(imports)
        lines.append("")
    if component_str:
        lines.append(component_str)
    elif frontend_strategy == "vue" or widget_path.endswith(".vue"):
        lines.append(DEFAULT_VUE_WIDGET_CONTENT.strip())
    else:
        lines.append(build_default_react_shared_widget(resolve_shared_chatbot_assets(site_name)).strip())
    content = "\n".join(lines)
    return f"{content}\n" if not content.endswith("\n") else content


def _artifact_subpath_from_widget_path(widget_path: str) -> Path:
    parts = list(Path(widget_path).parts)
    if parts and parts[0] == "frontend":
        parts = parts[1:]
    if not parts:
        return Path("src") / "chatbot" / Path(Path(DEFAULT_WIDGET_PATH).name)
    return Path(*parts)


def generate_frontend_widget_artifact(
    *,
    run_root: str | Path,
    proposal: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, str]:
    run_root = Path(run_root)
    effective_manifest = manifest or _load_manifest_if_present(run_root)
    merged_proposal = _prepare_frontend_widget_proposal(proposal, effective_manifest)
    if effective_manifest:
        merged_proposal.setdefault(
            "frontend_strategy",
            str((effective_manifest.get("analysis") or {}).get("frontend_strategy") or "").strip(),
        )
        merged_proposal.setdefault(
            "site",
            str(effective_manifest.get("site") or "").strip(),
        )
    widget_path = resolve_widget_path(proposal=merged_proposal, manifest=None)
    content = _prepare_widget_content(merged_proposal)
    artifact_subpath = _artifact_subpath_from_widget_path(widget_path)
    target = run_root / "files" / "frontend" / artifact_subpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"type": "widget", "path": str(target)}
