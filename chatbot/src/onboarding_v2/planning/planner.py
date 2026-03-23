from __future__ import annotations

import json
from pathlib import Path

from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.planning import (
    ChatbotBridgePlan,
    HostBackendPlan,
    HostFrontendPlan,
    IntegrationPlan,
    PlanningNotes,
)

SUPPORTED_ORDER_TOOLS = [
    "list_orders",
    "get_order_status",
    "cancel",
    "refund",
    "exchange",
]


def build_integration_plan(
    snapshot: AnalysisSnapshot,
    *,
    chatbot_server_base_url: str,
) -> IntegrationPlan:
    backend_framework = snapshot.repo_profile.backend_framework
    frontend_framework = snapshot.repo_profile.frontend_framework
    route_target = _choose_route_target(snapshot)
    auth_source = _choose_auth_source(snapshot)
    mount_target = _choose_mount_target(snapshot)
    api_client_target = _choose_api_client_target(snapshot, fallback=mount_target)
    generated_handler_path = _choose_generated_handler_path(backend_framework)
    site_id = _load_required_site_id(Path(snapshot.repo_profile.source_root))
    order_lookup_target = _choose_order_lookup_target(snapshot, site_id=site_id)
    order_action_target = _choose_order_action_target(snapshot, site_id=site_id)
    exchange_strategy = _choose_exchange_strategy(site_id=site_id, order_action_target=order_action_target)
    normalized_chatbot_server_base_url = str(chatbot_server_base_url or "").strip().rstrip("/")
    if not normalized_chatbot_server_base_url:
        raise ValueError("chatbot_server_base_url is required for V2 dual-patch planning")
    chatbot_server_base_url_expression = _resolve_chatbot_server_base_url_expression(
        source_root=Path(snapshot.repo_profile.source_root),
        runtime_base_url=normalized_chatbot_server_base_url,
    )

    backend_strategy = {
        "django": "django_project_urlconf_import_view",
        "flask": "flask_app_register_blueprint",
        "fastapi": "fastapi_include_router",
    }.get(backend_framework, "django_project_urlconf_import_view")
    mount_strategy = {
        "react": "react_app_shell_outside_routes",
        "vue": "react_app_shell_outside_routes",
    }.get(frontend_framework, "react_app_shell_outside_routes")
    api_strategy = {
        "react": "react_api_client_augment_existing",
        "vue": "react_api_client_augment_existing",
    }.get(frontend_framework, "react_api_client_augment_existing")

    assumptions = []
    if backend_framework == "django":
        assumptions.append("chat auth bridge will be materialized in backend/chat_auth.py")
    if mount_target == api_client_target:
        assumptions.append("frontend api support falls back to app shell because no dedicated api client was found")
    assumptions.append("host auth bootstrap returns the real session token as access_token for chatbot adapter validation")

    return IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy=backend_strategy,
            route_target=route_target,
            import_target=route_target,
            order_lookup_target=order_lookup_target,
            order_action_target=order_action_target,
            exchange_strategy=exchange_strategy,
            supported_order_tools=list(SUPPORTED_ORDER_TOOLS),
            auth_handler_source=auth_source,
            generated_handler_path=generated_handler_path,
            chat_auth_contract_path="/api/chat/auth-token",
            site_id=site_id,
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy=mount_strategy,
            mount_target=mount_target,
            router_boundary=(
                snapshot.frontend_seams.router_boundary_candidates[0].path
                if snapshot.frontend_seams.router_boundary_candidates
                else mount_target
            ),
            api_strategy=api_strategy,
            api_client_target=api_client_target,
            auth_bootstrap_path="/api/chat/auth-token",
            chatbot_server_base_url=normalized_chatbot_server_base_url,
            chatbot_server_base_url_expression=chatbot_server_base_url_expression,
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key=_normalize_site_key(site_id),
            adapter_package=f"src/adapters/generated/{_normalize_site_key(site_id)}",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var=_build_chatbot_bridge_env_var(site_id),
            supported_tools=list(SUPPORTED_ORDER_TOOLS),
        ),
        planning_notes=PlanningNotes(
            assumptions=assumptions,
            ambiguities=list(snapshot.ambiguity.open_questions),
            llm_rationale=[],
        ),
    )


def _choose_route_target(snapshot: AnalysisSnapshot) -> str:
    candidates = [candidate.path for candidate in snapshot.backend_seams.route_registration_points]
    if not candidates:
        return "backend/foodshop/urls.py"
    preferred = sorted(
        candidates,
        key=lambda value: (
            0 if value.endswith(("foodshop/urls.py", "config/urls.py", "project/urls.py")) else 1,
            len(Path(value).parts),
            value,
        ),
    )
    return preferred[0]


def _choose_auth_source(snapshot: AnalysisSnapshot) -> str:
    candidates = [candidate.path for candidate in snapshot.backend_seams.auth_source_candidates]
    preferred = [candidate for candidate in candidates if candidate.endswith("users/views.py")]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]
    return "backend/users/views.py"


def _choose_mount_target(snapshot: AnalysisSnapshot) -> str:
    candidates = [candidate.path for candidate in snapshot.frontend_seams.app_shell_candidates]
    preferred = [candidate for candidate in candidates if candidate.endswith("frontend/src/App.js")]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]
    if snapshot.frontend_seams.widget_mount_candidates:
        return snapshot.frontend_seams.widget_mount_candidates[0].path
    return "frontend/src/App.js"


def _choose_api_client_target(snapshot: AnalysisSnapshot, *, fallback: str) -> str:
    candidates = [candidate.path for candidate in snapshot.frontend_seams.api_client_candidates]
    preferred = [
        candidate
        for candidate in candidates
        if candidate.endswith(("frontend/src/api/api.js", "src/api/api.js"))
    ]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]
    return fallback


def _choose_order_lookup_target(snapshot: AnalysisSnapshot, *, site_id: str) -> str:
    return _choose_order_target(snapshot, site_id=site_id, role="lookup")


def _choose_order_action_target(snapshot: AnalysisSnapshot, *, site_id: str) -> str:
    return _choose_order_target(snapshot, site_id=site_id, role="action")


def _choose_order_target(snapshot: AnalysisSnapshot, *, site_id: str, role: str) -> str:
    candidates = _filter_valid_order_bridge_candidates(snapshot.domain_integration.order_bridge_targets)
    if candidates:
        enumerated_candidates = list(enumerate(candidates))
        preferred = sorted(
            enumerated_candidates,
            key=lambda item: (
                -_order_target_role_score(item[1].path, role=role),
                item[0],
                item[1].path,
            ),
        )
        if _order_target_role_score(preferred[0][1].path, role=role) > 0:
            return preferred[0][1].path
        return candidates[0].path
    return _fallback_order_target(site_id=site_id)


def _choose_exchange_strategy(*, site_id: str, order_action_target: str) -> str:
    normalized_site_id = _normalize_site_key(site_id)
    if normalized_site_id in {"food", "site_a", "site-a"} and order_action_target.endswith("backend/orders/views.py"):
        return "augment_existing_order_action_endpoint"
    if order_action_target:
        return "augment_existing_order_action_endpoint"
    return "augment_existing_order_action_endpoint"


def _order_target_role_score(path: str, *, role: str) -> int:
    normalized = path.lower()
    if role == "lookup":
        keywords = ("lookup", "status", "list", "detail", "query", "read")
    else:
        keywords = ("action", "update", "cancel", "refund", "exchange", "modify", "mutat", "command", "handler", "write")
    return 1 if any(keyword in normalized for keyword in keywords) else 0


def _filter_valid_order_bridge_candidates(candidates) -> list:
    return [candidate for candidate in candidates if _is_valid_order_bridge_candidate(candidate.path)]


def _is_valid_order_bridge_candidate(path: str) -> bool:
    normalized = path.replace("\\", "/").strip().lower()
    if normalized.endswith("/urls.py") or normalized.endswith("/tests.py"):
        return False
    parts = Path(normalized).parts
    if "tests" in parts or "migrations" in parts:
        return False
    return True


def _fallback_order_target(*, site_id: str) -> str:
    normalized_site_id = _normalize_site_key(site_id)
    if normalized_site_id in {"food", "site_a", "site-a"}:
        return "backend/orders/views.py"
    return "backend/orders/views.py"


def _choose_generated_handler_path(backend_framework: str) -> str | None:
    if backend_framework == "django":
        return "backend/chat_auth.py"
    if backend_framework in {"flask", "fastapi"}:
        return "chat_auth.py"
    return None


def _load_required_site_id(source_root: Path) -> str:
    manifest_path = source_root / "site-manifest.json"
    if not manifest_path.exists():
        raise ValueError("site-manifest.json with site_id is required for V2 dual-patch planning")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    site_id = str(payload.get("site_id") or "").strip()
    if not site_id:
        raise ValueError("site-manifest.json must declare a non-empty site_id")
    return site_id


def _normalize_site_key(site_id: str) -> str:
    cleaned = site_id.strip().lower().replace(" ", "_")
    return "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in cleaned)


def _build_chatbot_bridge_env_var(site_id: str) -> str:
    normalized = _normalize_site_key(site_id).upper().replace("-", "_")
    return f"GENERATED_{normalized}_API_URL"


def _resolve_chatbot_server_base_url_expression(
    *,
    source_root: Path,
    runtime_base_url: str,
) -> str:
    package_path = source_root / "frontend" / "package.json"
    if not package_path.exists():
        raise ValueError("frontend/package.json is required to infer chatbotServerBaseUrl env injection strategy")

    package = json.loads(package_path.read_text(encoding="utf-8"))
    dependencies = {
        **(package.get("dependencies") or {}),
        **(package.get("devDependencies") or {}),
    }
    scripts = package.get("scripts") or {}
    combined_script_text = " ".join(str(value) for value in scripts.values())
    fallback = _normalize_runtime_fallback(runtime_base_url)

    if "react-scripts" in dependencies:
        return f'process.env.REACT_APP_CHATBOT_SERVER_BASE_URL || "{fallback}"'
    if "next" in dependencies:
        return f'process.env.NEXT_PUBLIC_CHATBOT_SERVER_BASE_URL || "{fallback}"'
    if "vite" in dependencies or "vite" in combined_script_text:
        return f'import.meta.env.VITE_CHATBOT_SERVER_BASE_URL || "{fallback}"'

    raise ValueError("unable to infer a safe chatbotServerBaseUrl env injection strategy for host frontend")


def _normalize_runtime_fallback(runtime_base_url: str) -> str:
    normalized = runtime_base_url.strip().rstrip("/")
    if normalized in {"http://localhost:8100", "http://127.0.0.1:8100"}:
        return "http://127.0.0.1:8100"
    return normalized
