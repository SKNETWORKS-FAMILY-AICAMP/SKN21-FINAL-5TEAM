from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from .backend_integration import CHAT_AUTH_BOOTSTRAP_PATH, build_backend_route_patch, choose_backend_route_target
from .frontend_generator import (
    build_frontend_mount_contract,
    generate_frontend_widget_artifact as _generate_frontend_widget_artifact,
)
from .tool_registry_generator import generate_backend_tool_registry


SITE_ID_BY_NAME = {
    "food": "site-a",
    "bilyeo": "site-b",
    "ecommerce": "site-c",
}

LOCAL_CHAT_TOKEN_HELPER = """import base64
import hashlib
import hmac
import json
import time


def issue_bridge_token(
    *,
    user_id: str,
    site_id: str,
    secret: str,
    name: str,
    email: str,
    scopes: list[str],
    expires_in_seconds: int,
) -> str:
    payload = {
        "user_id": user_id,
        "site_id": site_id,
        "name": name,
        "email": email,
        "scopes": scopes,
        "exp": int(time.time()) + expires_in_seconds,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(body).decode("utf-8").rstrip("=")
        + "."
        + base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    )


def issue_chat_token(**kwargs) -> str:
    return issue_bridge_token(**kwargs)
"""


def _load_manifest(run_root: str | Path) -> dict:
    root = Path(run_root)
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def _read_source_lines_for_diff(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = f"{lines[-1]}\n"
    return lines


def _build_food_chat_auth_template(site_id: str) -> str:
    return f"""from django.http import JsonResponse
from django.views.decorators.http import require_POST

from users.models import SessionToken

{LOCAL_CHAT_TOKEN_HELPER}


@require_POST
def chat_auth_token(request):
    session_token = request.COOKIES.get("session_token")
    if not session_token:
        return JsonResponse(
            {{
                "authenticated": False,
                "site_id": "{site_id}",
                "access_token": "",
                "user": None,
                "detail": "login required",
            }},
            status=401,
        )

    session = (
        SessionToken.objects.select_related("user")
        .filter(token=session_token, is_active=True)
        .first()
    )
    if not session:
        return JsonResponse(
            {{
                "authenticated": False,
                "site_id": "{site_id}",
                "access_token": "",
                "user": None,
                "detail": "invalid session",
            }},
            status=401,
        )

    user = session.user
    token = issue_chat_token(
        user_id=str(user.id),
        site_id="{site_id}",
        secret="CHANGE_ME",
        name=user.get_full_name() or user.username,
        email=user.email,
        scopes=["chat"],
        expires_in_seconds=600,
    )
    return JsonResponse(
        {{
            "authenticated": True,
            "site_id": "{site_id}",
            "access_token": token,
            "user": {{
                "id": str(user.id),
                "email": user.email,
                "name": user.get_full_name() or user.username,
            }},
        }}
    )
"""


def _build_bilyeo_chat_auth_template(site_id: str) -> str:
    return f"""from flask import Blueprint, jsonify, session

{LOCAL_CHAT_TOKEN_HELPER}


chat_auth_bp = Blueprint("chat_auth", __name__)


@chat_auth_bp.route("{CHAT_AUTH_BOOTSTRAP_PATH}", methods=["POST"])
def chat_auth_token():
    user_id = session.get("user_id")
    email = session.get("email")
    name = session.get("name")
    if not user_id:
        return jsonify(
            {{
                "authenticated": False,
                "site_id": "{site_id}",
                "access_token": "",
                "user": None,
                "error": "login required",
            }}
        ), 401

    token = issue_chat_token(
        user_id=str(user_id),
        site_id="{site_id}",
        secret="CHANGE_ME",
        name=name or f"user-{{user_id}}",
        email=email,
        scopes=["chat"],
        expires_in_seconds=600,
    )
    return jsonify(
        {{
            "authenticated": True,
            "site_id": "{site_id}",
            "access_token": token,
            "user": {{
                "id": str(user_id),
                "email": email or "",
                "name": name or f"user-{{user_id}}",
            }},
        }}
    ), 200
"""


def _build_ecommerce_chat_auth_template(site_id: str) -> str:
    return f"""from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

{LOCAL_CHAT_TOKEN_HELPER}


router = APIRouter(tags=["chat-auth"])


@router.post("{CHAT_AUTH_BOOTSTRAP_PATH}")
def chat_auth_token(request: Request):
    access_token = request.cookies.get("access_token")
    if not access_token:
        return JSONResponse(
            {{
                "authenticated": False,
                "site_id": "{site_id}",
                "access_token": "",
                "user": None,
                "detail": "login required",
            }},
            status_code=401,
        )

    # TODO: replace with the site's access_token decoder and user lookup.
    resolved_user_id = "resolved-user-id"
    resolved_name = "resolved-name"
    resolved_email = "resolved-email@example.com"

    token = issue_chat_token(
        user_id=resolved_user_id,
        site_id="{site_id}",
        secret="CHANGE_ME",
        name=resolved_name,
        email=resolved_email,
        scopes=["chat"],
        expires_in_seconds=600,
    )
    return JSONResponse(
        {{
            "authenticated": True,
            "site_id": "{site_id}",
            "access_token": token,
            "user": {{
                "id": resolved_user_id,
                "email": resolved_email,
                "name": resolved_name,
            }},
        }}
    )
"""


def _build_chat_auth_template(site: str, site_id: str) -> str:
    if site == "food":
        return _build_food_chat_auth_template(site_id)
    if site == "bilyeo":
        return _build_bilyeo_chat_auth_template(site_id)
    if site == "ecommerce":
        return _build_ecommerce_chat_auth_template(site_id)
    return f"""{LOCAL_CHAT_TOKEN_HELPER}


def chat_auth_token(request):
    token = issue_chat_token(
        user_id="resolved-user-id",
        site_id="{site_id}",
        secret="CHANGE_ME",
        name="resolved-name",
        email="resolved-email@example.com",
        scopes=["chat"],
        expires_in_seconds=600,
    )
    return {{
        "authenticated": True,
        "site_id": "{site_id}",
        "access_token": token,
        "user": {{
            "id": "resolved-user-id",
            "email": "resolved-email@example.com",
            "name": "resolved-name",
        }},
    }}
"""


def generate_chat_auth_template(run_root: str | Path) -> Path:
    root = Path(run_root)
    manifest = _load_manifest(root)
    site = str(manifest.get("site") or "").strip()
    site_id = SITE_ID_BY_NAME.get(site, "site-unknown")

    output_path = root / "files" / "backend" / "chat_auth.py"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_build_chat_auth_template(site, site_id), encoding="utf-8")
    return output_path


def generate_backend_route_patch(run_root: str | Path) -> Path:
    root = Path(run_root)
    manifest = _load_manifest(root)
    analysis = manifest.get("analysis") or {}
    strategy = str(analysis.get("backend_strategy") or (analysis.get("framework") or {}).get("backend") or "unknown")
    target_file = choose_backend_route_target(list(analysis.get("backend_route_targets") or []))
    output_path = root / "patches" / "backend_chat_auth_route.patch"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not target_file or strategy == "unknown":
        output_path.write_text("", encoding="utf-8")
        return output_path

    source_root = Path(str(manifest.get("source_root") or "")).expanduser()
    source_file = source_root / target_file
    source_lines = _read_source_lines_for_diff(source_file)
    patch = build_backend_route_patch(
        strategy=strategy,
        target_file=target_file,
        source_lines=source_lines,
    )
    output_path.write_text(patch, encoding="utf-8")
    return output_path


def _build_food_order_adapter_template(order_api_base: str) -> str:
    return f"""import httpx


ORDER_API_BASE = "{order_api_base}"
ORDER_BRIDGE_OPERATIONS = ("list_orders", "get_order_status", "cancel", "refund", "exchange")


class GeneratedOrderAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_orders(self, headers: dict | None = None) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{{self.base_url}}{{ORDER_API_BASE}}", headers=headers or {{}})
            response.raise_for_status()
            return response.json()

    async def get_order(self, order_id: int, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{ORDER_API_BASE}}{{order_id}}/",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def get_order_status(self, order_id: int, headers: dict | None = None) -> dict:
        return await self.get_order(order_id, headers=headers)

    async def submit_order_action(
        self,
        order_id: int,
        action: str,
        headers: dict | None = None,
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{{self.base_url}}{{ORDER_API_BASE}}{{order_id}}/actions/",
                headers=headers or {{}},
                json={{"action": action}},
            )
            response.raise_for_status()
            return response.json()

    async def cancel(self, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "cancel", headers=headers)

    async def refund(self, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "refund", headers=headers)

    async def exchange(self, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "exchange", headers=headers)
"""


def _build_bilyeo_order_adapter_template(order_api_base: str) -> str:
    return f"""import httpx


ORDER_API_BASE = "{order_api_base}"
ORDER_BRIDGE_OPERATIONS = ("list_orders", "get_order_status", "cancel", "refund", "exchange")


class GeneratedOrderAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_orders(self, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{ORDER_API_BASE}}",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def get_order(self, order_id: int, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{ORDER_API_BASE}}/{{order_id}}",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def get_order_status(self, order_id: int, headers: dict | None = None) -> dict:
        return await self.get_order(order_id, headers=headers)

    async def submit_order_action(
        self,
        order_id: int,
        action: str,
        headers: dict | None = None,
        payload: dict | None = None,
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{{self.base_url}}{{ORDER_API_BASE}}/{{order_id}}/actions/",
                headers=headers or {{}},
                json={{"action": action, **(payload or {{}})}},
            )
            response.raise_for_status()
            return response.json()

    async def cancel(self, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "cancel", headers=headers)

    async def refund(self, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "refund", headers=headers)

    async def exchange(self, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "exchange", headers=headers)
"""


def _build_ecommerce_order_adapter_template(order_api_base: str) -> str:
    return f"""import httpx


ORDER_API_BASE = "{order_api_base}"
ORDER_BRIDGE_OPERATIONS = ("list_orders", "get_order_status", "cancel", "refund", "exchange")


class GeneratedOrderAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _order_base(self, user_id: int) -> str:
        return ORDER_API_BASE.format(user_id=user_id)

    async def list_orders(
        self,
        user_id: int,
        headers: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        order_base = self._order_base(user_id)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{order_base}}",
                headers=headers or {{}},
                params=params or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def get_order(self, user_id: int, order_id: int, headers: dict | None = None) -> dict:
        order_base = self._order_base(user_id)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{order_base}}/{{order_id}}",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def get_order_status(self, user_id: int, order_id: int, headers: dict | None = None) -> dict:
        return await self.get_order(user_id, order_id, headers=headers)

    async def cancel_order(self, user_id: int, order_id: int, headers: dict | None = None) -> dict:
        order_base = self._order_base(user_id)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{{self.base_url}}{{order_base}}/{{order_id}}/cancel",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def submit_order_action(
        self,
        user_id: int,
        order_id: int,
        action: str,
        headers: dict | None = None,
        payload: dict | None = None,
    ) -> dict:
        if action == "cancel":
            return await self.cancel_order(user_id, order_id, headers=headers)
        order_base = self._order_base(user_id)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{{self.base_url}}{{order_base}}/{{order_id}}/{{action}}",
                headers=headers or {{}},
                json=payload or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def cancel(self, user_id: int, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(user_id, order_id, "cancel", headers=headers)

    async def refund(self, user_id: int, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(user_id, order_id, "refund", headers=headers)

    async def exchange(self, user_id: int, order_id: int, headers: dict | None = None) -> dict:
        return await self.submit_order_action(user_id, order_id, "exchange", headers=headers)
"""


def _build_order_adapter_template(site: str, order_api_base: str) -> str:
    if site == "food":
        return _build_food_order_adapter_template(order_api_base)
    if site == "bilyeo":
        return _build_bilyeo_order_adapter_template(order_api_base)
    if site == "ecommerce":
        return _build_ecommerce_order_adapter_template(order_api_base)
    return f"""import httpx


ORDER_API_BASE = "{order_api_base}"
ORDER_BRIDGE_OPERATIONS = ("list_orders", "get_order_status", "cancel", "refund", "exchange")


class GeneratedOrderAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_orders(self, headers: dict | None = None, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{ORDER_API_BASE}}",
                headers=headers or {{}},
                params=params or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def get_order(self, order_id: str, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{ORDER_API_BASE}}/{{order_id}}",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def get_order_status(self, order_id: str, headers: dict | None = None) -> dict:
        return await self.get_order(order_id, headers=headers)

    async def submit_order_action(
        self,
        order_id: str,
        action: str,
        headers: dict | None = None,
        payload: dict | None = None,
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{{self.base_url}}{{ORDER_API_BASE}}/{{order_id}}/{{action}}",
                headers=headers or {{}},
                json=payload or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def cancel(self, order_id: str, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "cancel", headers=headers)

    async def refund(self, order_id: str, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "refund", headers=headers)

    async def exchange(self, order_id: str, headers: dict | None = None) -> dict:
        return await self.submit_order_action(order_id, "exchange", headers=headers)
"""


def generate_order_adapter_template(run_root: str | Path) -> Path:
    root = Path(run_root)
    manifest = _load_manifest(root)
    site = str(manifest.get("site") or "").strip()
    analysis = manifest.get("analysis", {})
    order_api = analysis.get("order_api") or []
    order_api_base = str(order_api[0]).strip() if order_api else "/orders"

    output_path = root / "files" / "backend" / "order_adapter_client.py"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _build_order_adapter_template(site, order_api_base),
        encoding="utf-8",
    )
    return output_path


def _build_food_product_adapter_template(product_api_base: str) -> str:
    return f"""import httpx


PRODUCT_API_BASE = "{product_api_base}"


class GeneratedProductAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_products(self, headers: dict | None = None, params: dict | None = None) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{PRODUCT_API_BASE}}",
                headers=headers or {{}},
                params=params or {{}},
            )
            response.raise_for_status()
            return response.json()

    async def get_product(self, product_id: int, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{PRODUCT_API_BASE}}{{product_id}}/",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()
"""


def _build_bilyeo_product_adapter_template(product_api_base: str) -> str:
    return f"""import httpx


PRODUCT_API_BASE = "{product_api_base}"


class GeneratedProductAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_products(
        self,
        headers: dict | None = None,
        category: str | None = None,
        search: str | None = None,
    ) -> dict:
        raw_params = {{
            "category": category,
            "search": search,
        }}
        params = {{
            key: value
            for key, value in raw_params.items()
            if value is not None and value != ""
        }}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{PRODUCT_API_BASE}}",
                headers=headers or {{}},
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def get_product(self, product_id: int, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{PRODUCT_API_BASE}}/{{product_id}}",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()
"""


def _build_ecommerce_product_adapter_template(product_api_base: str) -> str:
    return f"""import httpx


PRODUCT_API_BASE = "{product_api_base}"


class GeneratedProductAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_products(
        self,
        headers: dict | None = None,
        category_id: int | None = None,
        keyword: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> dict:
        raw_params = {{
            "category_id": category_id,
            "keyword": keyword,
            "min_price": min_price,
            "max_price": max_price,
            "skip": skip,
            "limit": limit,
        }}
        params = {{
            key: value
            for key, value in raw_params.items()
            if value is not None and value != ""
        }}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{PRODUCT_API_BASE}}",
                headers=headers or {{}},
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def get_product(self, product_id: int, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{{self.base_url}}{{PRODUCT_API_BASE}}/{{product_id}}",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()
"""


def _build_product_adapter_template(site: str, product_api_base: str) -> str:
    if site == "food":
        return _build_food_product_adapter_template(product_api_base)
    if site == "bilyeo":
        return _build_bilyeo_product_adapter_template(product_api_base)
    if site == "ecommerce":
        return _build_ecommerce_product_adapter_template(product_api_base)
    return f"""import httpx


PRODUCT_API_BASE = "{product_api_base}"
"""


def generate_product_adapter_template(run_root: str | Path) -> Path:
    root = Path(run_root)
    manifest = _load_manifest(root)
    site = str(manifest.get("site") or "").strip()
    analysis = manifest.get("analysis", {})
    product_api = analysis.get("product_api") or []
    product_api_base = str(product_api[0]).strip() if product_api else "/products"

    output_path = root / "files" / "backend" / "product_adapter_client.py"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _build_product_adapter_template(site, product_api_base),
        encoding="utf-8",
    )
    return output_path


def _merge_frontend_widget_proposal(
    manifest: dict[str, Any],
    explicit_proposal: dict[str, Any] | None,
) -> dict[str, Any]:
    analysis = manifest.get("analysis") or {}
    merged: dict[str, Any] = {}
    base_proposal = analysis.get("frontend_widget_proposal")
    if isinstance(base_proposal, dict):
        merged.update(base_proposal)
    if explicit_proposal:
        merged.update(explicit_proposal)
    return merged


def generate_frontend_widget_artifact(
    run_root: str | Path,
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(run_root)
    manifest = _load_manifest(root)
    merged_proposal = _merge_frontend_widget_proposal(manifest, proposal)
    return _generate_frontend_widget_artifact(
        run_root=run_root,
        proposal=merged_proposal,
        manifest=manifest,
    )


def _build_shared_widget_bootstrap_lines() -> list[str]:
    contract = build_frontend_mount_contract()
    return [
        "const ORDER_CS_WIDGET_HOST_CONTRACT = {\n",
        f'  chatbotServerBaseUrl: "{contract["chatbotServerBaseUrl"]}",\n',
        f'  authBootstrapPath: "{contract["authBootstrapPath"]}",\n',
        f'  widgetBundlePath: "{contract["widgetBundlePath"]}",\n',
        f'  widgetElementTag: "{contract["widgetElementTag"]}",\n',
        f'  mountMode: "{contract["mountMode"]}",\n',
        "};\n",
        "\n",
        'if (typeof globalThis === "object") {\n',
        '  globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"] = ORDER_CS_WIDGET_HOST_CONTRACT;\n',
        "}\n",
        "\n",
        (
            'if (typeof document !== "undefined" && '
            '!document.querySelector(\'script[data-order-cs-widget-bundle="true"]\')) {\n'
        ),
        '  const orderCsWidgetScript = document.createElement("script");\n',
        (
            "  orderCsWidgetScript.src = "
            "`${ORDER_CS_WIDGET_HOST_CONTRACT.chatbotServerBaseUrl}"
            "${ORDER_CS_WIDGET_HOST_CONTRACT.widgetBundlePath}`;\n"
        ),
        "  orderCsWidgetScript.async = true;\n",
        '  orderCsWidgetScript.dataset.orderCsWidgetBundle = "true";\n',
        "  document.head.appendChild(orderCsWidgetScript);\n",
        "}\n",
    ]


def _build_frontend_mount_patch(target_file: str) -> str:
    bootstrap = "".join(f"+{line}" for line in _build_shared_widget_bootstrap_lines()).rstrip()
    return f"""--- a/{target_file}
+++ b/{target_file}
@@
{bootstrap}
@@
+      <order-cs-widget />
"""


def generate_frontend_mount_patch(
    run_root: str | Path,
    widget_path: str | None = None,
) -> Path:
    root = Path(run_root)
    manifest = _load_manifest(root)
    analysis = manifest.get("analysis", {})
    mount_points = analysis.get("frontend_mount_points") or []
    mount_targets = analysis.get("frontend_mount_targets") or []
    frontend_strategy = str(analysis.get("frontend_strategy") or "unknown")
    target_candidates = list(mount_points) + list(mount_targets)
    target_file = str(target_candidates[0]).strip() if target_candidates else (
        "frontend/src/App.vue" if frontend_strategy == "vue" else "frontend/src/App.js"
    )
    source_root = Path(str(manifest.get("source_root") or "")).expanduser()

    output_path = root / "patches" / "frontend_widget_mount.patch"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_file = source_root / target_file
    if source_file.exists():
        source_lines = _read_source_lines_for_diff(source_file)
        updated_lines = _build_frontend_mount_updated_lines(
            source_lines,
            target_file,
        )
        diff = difflib.unified_diff(
            source_lines,
            updated_lines,
            fromfile=f"a/{target_file}",
            tofile=f"b/{target_file}",
        )
        output_path.write_text("".join(diff), encoding="utf-8")
    else:
        output_path.write_text(_build_frontend_mount_patch(target_file), encoding="utf-8")
    return output_path


def _build_frontend_mount_updated_lines(
    source_lines: list[str],
    target_file: str,
) -> list[str]:
    updated_lines = list(source_lines)
    bootstrap_lines = _build_shared_widget_bootstrap_lines()
    lower = target_file.lower()
    if lower.endswith(".vue"):
        widget_line = "  <order-cs-widget />\n"
        if 'globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"]' not in "".join(updated_lines):
            script_close = next((index for index, line in enumerate(updated_lines) if "</script>" in line), None)
            if script_close is not None:
                insertion = list(bootstrap_lines)
                if script_close > 0 and updated_lines[script_close - 1].strip():
                    insertion.insert(0, "\n")
                updated_lines[script_close:script_close] = insertion
            else:
                updated_lines.extend(["\n", "<script setup>\n", *bootstrap_lines, "</script>\n"])
        template_close = next((index for index, line in enumerate(updated_lines) if "</template>" in line), None)
        if widget_line not in updated_lines:
            if template_close is not None:
                updated_lines.insert(template_close, widget_line)
            else:
                updated_lines.extend(["\n", "<template>\n", widget_line, "</template>\n"])
        return updated_lines

    single_line_return_index = next(
        (
            index
            for index, line in enumerate(updated_lines)
            if line.strip().startswith("return <") and line.strip().endswith(">;")
        ),
        None,
    )
    if single_line_return_index is not None:
        indent = updated_lines[single_line_return_index].split("return", 1)[0]
        return_line = updated_lines[single_line_return_index].strip()
        jsx_expression = return_line[len("return ") : -1]
        updated_lines = _insert_shared_widget_bootstrap_lines(updated_lines, bootstrap_lines)
        single_line_return_index = next(
            index
            for index, line in enumerate(updated_lines)
            if line.strip().startswith("return <") and line.strip().endswith(">;")
        )
        updated_lines[single_line_return_index : single_line_return_index + 1] = [
            f"{indent}return (\n",
            f"{indent}  <>\n",
            f"{indent}    {jsx_expression}\n",
            f"{indent}    <order-cs-widget />\n",
            f"{indent}  </>\n",
            f"{indent});\n",
        ]
        return updated_lines

    updated_lines = _insert_shared_widget_bootstrap_lines(updated_lines, bootstrap_lines)
    widget_line = "      <order-cs-widget />\n"
    if widget_line in updated_lines:
        return updated_lines

    insert_index = _find_react_mount_insert_index(updated_lines)
    if insert_index is None:
        fallback_line = "  <order-cs-widget />\n"
        if fallback_line not in updated_lines:
            if updated_lines and not updated_lines[-1].endswith("\n"):
                updated_lines[-1] = f"{updated_lines[-1]}\n"
            updated_lines.extend(["\n", fallback_line])
        return updated_lines

    updated_lines.insert(insert_index, widget_line)
    return updated_lines


def _insert_shared_widget_bootstrap_lines(
    source_lines: list[str],
    bootstrap_lines: list[str],
) -> list[str]:
    updated_lines = list(source_lines)
    if 'globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"]' in "".join(updated_lines):
        return updated_lines

    insert_index = 0
    for index, line in enumerate(updated_lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_index = index + 1
            continue
        if stripped == "":
            if insert_index:
                insert_index = index + 1
            continue
        break

    updated_lines[insert_index:insert_index] = [*bootstrap_lines, "\n"]
    return updated_lines


def _find_react_mount_insert_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped in {"</BrowserRouter>", "</Routes>", "</main>", "</div>"}:
            return index
    return None
