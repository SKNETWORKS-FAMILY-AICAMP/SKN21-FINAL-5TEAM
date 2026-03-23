from __future__ import annotations

from pathlib import Path
from typing import Any

from .shared_chatbot_assets import (
    DEFAULT_AUTH_BOOTSTRAP_PATH,
    build_shared_widget_host_contract,
)


DEFAULT_WIDGET_PATH = "frontend/src/chatbot/orderCsWidgetHost.js"
DEFAULT_VUE_WIDGET_PATH = DEFAULT_WIDGET_PATH
LEGACY_WIDGET_MARKER = "SharedChatbotWidget"


def build_frontend_mount_contract(*, chatbot_server_base_url: str = "") -> dict[str, str]:
    return build_shared_widget_host_contract(
        chatbot_server_base_url=chatbot_server_base_url,
    )


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


def _default_widget_path(frontend_strategy: str | None) -> str:
    return DEFAULT_VUE_WIDGET_PATH if frontend_strategy == "vue" else DEFAULT_WIDGET_PATH


def _normalize_widget_path(path: str | None, *, frontend_strategy: str | None = None) -> str:
    if not path:
        return _default_widget_path(frontend_strategy)
    if LEGACY_WIDGET_MARKER in str(path):
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
    if isinstance(explicit, str) and explicit.strip() and LEGACY_WIDGET_MARKER not in explicit:
        return explicit if explicit.endswith("\n") else f"{explicit}\n"
    frontend_strategy = str(proposal.get("frontend_strategy") or "").strip().lower()
    widget_path = str(proposal.get("widget_path") or "").strip().lower()
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
    if component_str and LEGACY_WIDGET_MARKER not in component_str:
        lines.append(component_str)
    else:
        lines.append(_build_default_widget_host_content().strip())
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
    merged_proposal = _prepare_frontend_widget_proposal(proposal, manifest)
    if manifest:
        merged_proposal.setdefault(
            "frontend_strategy",
            str((manifest.get("analysis") or {}).get("frontend_strategy") or "").strip(),
        )
    widget_path = resolve_widget_path(proposal=merged_proposal, manifest=None)
    content = _prepare_widget_content(merged_proposal)
    artifact_subpath = _artifact_subpath_from_widget_path(widget_path)
    target = run_root / "files" / "frontend" / artifact_subpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"type": "widget", "path": str(target)}


def _build_default_widget_host_content() -> str:
    contract = build_frontend_mount_contract()
    return """export const ORDER_CS_WIDGET_HOST_CONTRACT = {
  chatbotServerBaseUrl: "%s",
  authBootstrapPath: "%s",
  widgetBundlePath: "%s",
  widgetElementTag: "%s",
  mountMode: "%s",
};

export function ensureOrderCsWidgetHost(globalTarget = typeof globalThis === "object" ? globalThis : undefined) {
  if (globalTarget) {
    globalTarget["__ORDER_CS_WIDGET_HOST_CONTRACT__"] = ORDER_CS_WIDGET_HOST_CONTRACT;
  }

  if (
    typeof document !== "undefined" &&
    !document.querySelector('script[data-order-cs-widget-bundle="true"]')
  ) {
    const orderCsWidgetScript = document.createElement("script");
    orderCsWidgetScript.src = `${ORDER_CS_WIDGET_HOST_CONTRACT.chatbotServerBaseUrl}${ORDER_CS_WIDGET_HOST_CONTRACT.widgetBundlePath}`;
    orderCsWidgetScript.async = true;
    orderCsWidgetScript.dataset.orderCsWidgetBundle = "true";
    document.head.appendChild(orderCsWidgetScript);
  }

  return ORDER_CS_WIDGET_HOST_CONTRACT;
}

export default ensureOrderCsWidgetHost;
""" % (
        contract["chatbotServerBaseUrl"],
        contract["authBootstrapPath"] or DEFAULT_AUTH_BOOTSTRAP_PATH,
        contract["widgetBundlePath"],
        contract["widgetElementTag"],
        contract["mountMode"],
    )
