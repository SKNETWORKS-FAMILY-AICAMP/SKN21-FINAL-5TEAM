from __future__ import annotations

from typing import Any

_DISALLOWED_SEAM_PARTS = {
    ".venv",
    "node_modules",
    "__pycache__",
    ".next",
    "build",
    "dist",
}


def build_strategy_allowlist(
    *,
    integration_contract: dict[str, Any] | None,
    recommended_outputs: list[str],
    codebase_map: dict[str, Any],
) -> set[str]:
    contract = integration_contract or {}
    backend = contract.get("backend") or {}
    frontend = contract.get("frontend") or {}
    allowlist: set[str] = set()

    backend_outputs = {"chat_auth", "product_adapter", "order_adapter"}
    if set(recommended_outputs).intersection(backend_outputs):
        allowlist.update(str(path).strip() for path in backend.get("auth_source_paths") or [])
        allowlist.update(str(path).strip() for path in backend.get("user_resolver_paths") or [])
        route_registration_points = [
            str(path).strip()
            for path in backend.get("route_registration_points") or []
            if str(path).strip()
        ]
        allowlist.update(route_registration_points)
        if not route_registration_points:
            allowlist.update(
                str(item.get("path") or "").strip()
                for item in (codebase_map.get("backend_route_targets") or [])
            )
        allowlist.update(
            str(item.get("path") or "").strip()
            for item in (codebase_map.get("tool_registry_targets") or [])
        )

    frontend_outputs = {"frontend_patch", "frontend_widget", "frontend_mount"}
    if set(recommended_outputs).intersection(frontend_outputs):
        allowlist.update(str(path).strip() for path in frontend.get("auth_store_paths") or [])
        allowlist.update(str(path).strip() for path in frontend.get("api_client_paths") or [])
        allowlist.update(str(path).strip() for path in frontend.get("widget_mount_points") or [])
        app_shell_path = str(frontend.get("app_shell_path") or "").strip()
        router_boundary_path = str(frontend.get("router_boundary_path") or "").strip()
        if app_shell_path:
            allowlist.add(app_shell_path)
        if router_boundary_path:
            allowlist.add(router_boundary_path)

    return {
        path
        for path in allowlist
        if path and seam_target_rejection_reason(path) is None
    }


def select_strategy_target_candidates(
    *,
    integration_contract: dict[str, Any] | None,
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
) -> list[dict[str, str]]:
    contract = integration_contract or {}
    backend = contract.get("backend") or {}
    frontend = contract.get("frontend") or {}
    candidate_sources = _candidate_sources_by_path(codebase_map)
    selected_paths: list[str] = []

    backend_outputs = {"chat_auth", "product_adapter", "order_adapter"}
    if set(recommended_outputs).intersection(backend_outputs):
        selected_paths.extend(str(path).strip() for path in backend.get("auth_source_paths") or [])
        route_registration_points = [
            str(path).strip()
            for path in backend.get("route_registration_points") or []
            if str(path).strip()
        ]
        selected_paths.extend(route_registration_points)
        if not route_registration_points:
            backend_route_candidates = [
                str(item.get("path") or "").strip()
                for item in (codebase_map.get("backend_route_targets") or [])
                if str(item.get("path") or "").strip()
            ]
            if backend_route_candidates:
                selected_paths.append(backend_route_candidates[0])
        if set(recommended_outputs).intersection({"product_adapter", "order_adapter"}):
            selected_paths.extend(
                str(item.get("path") or "").strip()
                for item in (codebase_map.get("tool_registry_targets") or [])
            )

    frontend_outputs = {"frontend_patch", "frontend_widget", "frontend_mount"}
    if set(recommended_outputs).intersection(frontend_outputs):
        selected_paths.extend(str(path).strip() for path in frontend.get("auth_store_paths") or [])
        selected_paths.extend(str(path).strip() for path in frontend.get("api_client_paths") or [])
        selected_paths.extend(str(path).strip() for path in frontend.get("widget_mount_points") or [])
        selected_paths.append(str(frontend.get("app_shell_path") or "").strip())
        selected_paths.append(str(frontend.get("router_boundary_path") or "").strip())

    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in selected_paths:
        if not path or path in seen:
            continue
        if seam_target_rejection_reason(path) is not None:
            continue
        candidate = candidate_sources.get(path)
        if candidate is None:
            continue
        selected.append(candidate)
        seen.add(path)
    return selected


def seam_target_rejection_reason(path: str) -> str | None:
    normalized = str(path or "").strip()
    if not normalized:
        return "empty_target_path"
    parts = set(part for part in normalized.split("/") if part)
    if parts.intersection(_DISALLOWED_SEAM_PARTS):
        return "build_artifact_target"
    if not (normalized.startswith("frontend/") or normalized.startswith("backend/")):
        return "non_source_target"
    return None


def _candidate_sources_by_path(codebase_map: dict[str, Any]) -> dict[str, dict[str, str]]:
    ordered_sources = [
        codebase_map.get("candidate_edit_targets") or [],
        codebase_map.get("backend_route_targets") or [],
        codebase_map.get("frontend_mount_targets") or [],
        codebase_map.get("tool_registry_targets") or [],
        codebase_map.get("validated_frontend_mount_targets") or [],
    ]
    candidates: dict[str, dict[str, str]] = {}
    for items in ordered_sources:
        for item in items:
            path = str(item.get("path") or "").strip()
            if not path or path in candidates:
                continue
            candidates[path] = {
                "path": path,
                "reason": str(item.get("reason") or "strategy-selected target"),
            }
    return candidates
