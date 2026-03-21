from __future__ import annotations

import json
from pathlib import Path

from .recovery_artifacts import write_recovered_smoke_plan
from .shared_chatbot_assets import resolve_shared_chatbot_assets


def _build_recommended_outputs(manifest: dict) -> list[str]:
    analysis = manifest.get("analysis", {})
    outputs: list[str] = []

    auth = analysis.get("auth", {})
    if auth.get("login_entrypoints") and auth.get("me_entrypoints"):
        outputs.append("chat_auth_endpoint")

    if analysis.get("frontend_mount_points"):
        outputs.append("frontend_widget_mount_patch")

    if analysis.get("product_api"):
        outputs.append("product_adapter_client")

    if analysis.get("order_api"):
        outputs.append("order_adapter_client")

    return outputs


def _build_default_probe_plan(manifest: dict) -> list[dict]:
    analysis = manifest.get("analysis", {})
    auth = analysis.get("auth", {})
    auth_style = str(auth.get("auth_style") or "unknown")
    if auth_style == "session_cookie":
        return _build_session_cookie_probe_plan(manifest)
    if auth_style == "session":
        return _build_session_probe_plan(manifest)
    return _build_token_probe_plan(manifest)


def _build_session_probe_plan(manifest: dict) -> list[dict]:
    return _build_session_steps(manifest, include_chat_contract=False)


def _build_session_cookie_probe_plan(manifest: dict) -> list[dict]:
    return _build_session_steps(manifest, include_chat_contract=True)


def _build_session_steps(manifest: dict, *, include_chat_contract: bool) -> list[dict]:
    analysis = manifest.get("analysis", {})
    auth = analysis.get("auth", {})
    product_api = (analysis.get("product_api") or ["/api/products/"])[0]
    order_api = (analysis.get("order_api") or ["/api/orders/"])[0]
    product_api_shape = analysis.get("product_api_shape") or {}
    order_api_shape = analysis.get("order_api_shape") or {}
    base_url = _resolve_base_url(manifest)
    backend_strategy = str(analysis.get("backend_strategy") or "unknown")
    login_fields = list(auth.get("login_fields") or ["username", "password"])
    login_path = auth.get("login_route")
    me_path = auth.get("me_route")
    session_check_shape = auth.get("session_check_shape") or {}
    if not login_path:
        return [
            {
                "id": "login",
                "kind": "analysis_error",
                "category": "auth",
                "required": True,
                "strategy": backend_strategy,
                "error": "Missing resolved login route for auth smoke generation",
            }
        ]

    steps: list[dict] = []
    shared_assets = resolve_shared_chatbot_assets(manifest.get("site"))
    steps.append(
        {
            "id": "login",
            "category": "auth",
            "kind": "http",
            "strategy": backend_strategy,
            "method": "POST",
            "url": f"{base_url}{login_path}",
            "body": {field: f"{{{{probe.credentials.{field}}}}}" for field in login_fields},
            "expects": _build_login_expects(session_check_shape=session_check_shape),
            "timeout_seconds": 10,
            "exports": {"login.cookies": "headers['set-cookie']"},
            "uses": [f"probe.credentials.{field}" for field in login_fields],
            }
        )
    if me_path:
        steps.append(
            {
                "id": "session-me",
                "category": "auth",
                "kind": "http",
                "strategy": backend_strategy,
                "method": "GET",
                "url": f"{base_url}{me_path}",
                "headers": {"Cookie": "{{login.cookies}}"},
                "expects": _build_session_me_expects(session_check_shape=session_check_shape),
                "timeout_seconds": 8,
                "exports": {"login.user_id": "json.user.id"},
                "uses": ["login.cookies"],
            }
        )
    if include_chat_contract:
        steps.append(
            {
                "id": "chat-auth-token",
                "category": "auth",
                "kind": "http",
                "strategy": backend_strategy,
                "method": "POST",
                "url": f"{base_url}/api/chat/auth-token",
                "headers": {"Cookie": "{{login.cookies}}"},
                "expects": {
                    "status": 200,
                    "json_keys": ["access_token"],
                    "json_path_equals": {"authenticated": True},
                },
                "timeout_seconds": 8,
                "exports": {"chat_auth.access_token": "json.access_token"},
                "uses": ["login.cookies"],
            }
        )
        steps.append(
            {
                "id": "chatbot-stream",
                "category": "chatbot",
                "kind": "http",
                "strategy": "shared_chatbot",
                "method": "POST",
                "url": "http://127.0.0.1:8100/api/v1/chat/stream",
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "message": "테스트 메시지",
                    "site_id": shared_assets.site_id,
                    "access_token": "{{chat_auth.access_token}}",
                    "previous_state": None,
                },
                "expects": {"status": 200},
                "timeout_seconds": 10,
                "uses": ["chat_auth.access_token"],
            }
        )
    steps.append(
        {
            "id": "product-api",
            "category": "catalog",
            "kind": "http",
            "strategy": backend_strategy,
            "method": "GET",
            "url": f"{base_url}{product_api}",
            "headers": {"Cookie": "{{login.cookies}}"},
            "expects": _build_collection_expects(product_api_shape),
            "timeout_seconds": 10,
            "exports": {"product.first_item": _build_collection_export(product_api_shape)},
            "uses": ["login.cookies"],
        }
    )
    steps.append(
        {
            "id": "order-api",
            "category": "orders",
            "kind": "http",
            "strategy": backend_strategy,
            "method": "GET",
            "url": f"{base_url}{order_api}",
            "headers": {"Cookie": "{{login.cookies}}"},
            "expects": _build_collection_expects(order_api_shape),
            "timeout_seconds": 10,
            "exports": {"order.first_order": _build_collection_export(order_api_shape)},
            "uses": ["login.cookies"],
        }
    )
    return steps


def _build_login_expects(*, session_check_shape: dict) -> dict:
    expects: dict[str, object] = {"status": 200}
    if session_check_shape.get("mode") == "login_response_user":
        expects["json_keys"] = ["user"]
    return expects


def _build_session_me_expects(*, session_check_shape: dict) -> dict:
    expects: dict[str, object] = {"status": 200}
    if session_check_shape.get("mode") == "authenticated_user":
        expects["json_path_equals"] = {"authenticated": True}
    else:
        expects["json_keys"] = ["user"]
    return expects


def _build_collection_expects(shape: dict | None) -> dict:
    shape = shape or {}
    mode = shape.get("mode")
    if mode == "root_array":
        return {"status": 200, "json_type": "list", "json_array_min_length": 1}
    key = str(shape.get("key") or "items")
    return {"status": 200, "json_keys": [key], "json_array_key": key, "json_array_min_length": 1}


def _build_collection_export(shape: dict | None) -> str:
    shape = shape or {}
    if shape.get("mode") == "root_array":
        return "json[0]"
    key = str(shape.get("key") or "items")
    return f"json.{key}[0]"


def _build_token_probe_plan(manifest: dict) -> list[dict]:
    analysis = manifest.get("analysis", {})
    product_api = (analysis.get("product_api") or ["/api/products/"])[0]
    order_api = (analysis.get("order_api") or ["/api/orders/"])[0]
    base_url = _resolve_base_url(manifest)
    backend_strategy = str(analysis.get("backend_strategy") or "unknown")
    backend_strategy = str(analysis.get("backend_strategy") or "unknown")
    route_prefixes = [str(item) for item in (analysis.get("route_prefixes") or []) if str(item)]
    login_path = "/api/login"
    if backend_strategy == "flask":
        auth_prefix = next((prefix for prefix in route_prefixes if "auth" in prefix), "")
        if auth_prefix:
            login_path = f"{auth_prefix}/login"

    return [
        {
            "id": "login",
            "category": "auth",
            "kind": "http",
            "strategy": backend_strategy,
            "method": "POST",
            "url": f"{base_url}{login_path}",
            "body": {"username": "{{probe.credentials.username}}", "password": "{{probe.credentials.password}}"},
            "expects": {"status": 200},
            "timeout_seconds": 10,
            "exports": {"login.cookies": "headers['set-cookie']"},
            "uses": ["probe.credentials.username", "probe.credentials.password"],
        },
        {
            "id": "chat-auth-token",
            "category": "auth",
            "kind": "http",
            "strategy": backend_strategy,
            "method": "POST",
            "url": f"{base_url}/api/chat/auth-token",
            "headers": {"Cookie": "{{login.cookies}}"},
            "expects": {"status": 200, "json_keys": ["access_token"]},
            "timeout_seconds": 8,
            "exports": {"chat_auth.access_token": "json.access_token"},
            "uses": ["login.cookies"],
        },
        {
            "id": "product-api",
            "category": "catalog",
            "kind": "http",
            "strategy": backend_strategy,
            "method": "GET",
            "url": f"{base_url}{product_api}",
            "headers": {"Authorization": "Bearer {{chat_auth.access_token}}"},
            "expects": {"status": 200, "json_keys": ["items"]},
            "timeout_seconds": 10,
            "exports": {"product.first_item": "json.items[0]"},
            "uses": ["chat_auth.access_token"],
        },
        {
            "id": "order-api",
            "category": "orders",
            "kind": "http",
            "strategy": backend_strategy,
            "method": "GET",
            "url": f"{base_url}{order_api}",
            "headers": {"Authorization": "Bearer {{chat_auth.access_token}}"},
            "expects": {"status": 200},
            "timeout_seconds": 10,
            "exports": {"order.first_order": "json.orders[0]"},
            "uses": ["chat_auth.access_token"],
        },
    ]


def _resolve_base_url(manifest: dict) -> str:
    return "http://127.0.0.1:8000"


def generate_overlay_scaffold(
    run_root: str | Path,
    *,
    recovery_payload: dict | None = None,
) -> Path:
    root = Path(run_root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    (root / "files").mkdir(parents=True, exist_ok=True)
    (root / "patches").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    smoke_root = root / "smoke-tests"
    smoke_root.mkdir(parents=True, exist_ok=True)

    smoke_steps = _build_default_probe_plan(manifest)

    generation_plan = {
        "run_id": manifest.get("run_id"),
        "site": manifest.get("site"),
        "detected": manifest.get("analysis", {}),
        "recommended_outputs": _build_recommended_outputs(manifest),
    }

    manifest["tests"] = {
        **(manifest.get("tests") or {}),
        "smoke": smoke_steps,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (root / "reports" / "generation-plan.json").write_text(
        json.dumps(generation_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if recovery_payload is not None:
        write_recovered_smoke_plan(
            run_root=root,
            smoke_steps=smoke_steps,
            recovery_payload=recovery_payload,
        )

    return root
