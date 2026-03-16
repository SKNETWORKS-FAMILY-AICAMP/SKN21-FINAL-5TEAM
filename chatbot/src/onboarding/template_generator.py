from __future__ import annotations

import difflib
import json
from pathlib import Path


SITE_ID_BY_NAME = {
    "food": "site-a",
    "bilyeo": "site-b",
    "ecommerce": "site-c",
}


def _load_manifest(run_root: str | Path) -> dict:
    root = Path(run_root)
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def _build_food_chat_auth_template(site_id: str) -> str:
    return f"""from django.http import JsonResponse
from django.views.decorators.http import require_POST

from chatbot.src.auth.chat_token import issue_chat_token
from users.models import SessionToken


@require_POST
def chat_auth_token(request):
    session_token = request.COOKIES.get("session_token")
    if not session_token:
        return JsonResponse({{"authenticated": False, "detail": "login required"}}, status=401)

    session = (
        SessionToken.objects.select_related("user")
        .filter(token=session_token, is_active=True)
        .first()
    )
    if not session:
        return JsonResponse({{"authenticated": False, "detail": "invalid session"}}, status=401)

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
        }}
    )
"""


def _build_bilyeo_chat_auth_template(site_id: str) -> str:
    return f"""from flask import Blueprint, jsonify, session

from chatbot.src.auth.chat_token import issue_chat_token


chat_auth_bp = Blueprint("chat_auth", __name__)


@chat_auth_bp.route("/api/chat/auth-token", methods=["POST"])
def chat_auth_token():
    user_id = session.get("user_id")
    email = session.get("email")
    name = session.get("name")
    if not user_id:
        return jsonify({{"authenticated": False, "error": "login required"}}), 401

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
        }}
    ), 200
"""


def _build_ecommerce_chat_auth_template(site_id: str) -> str:
    return f"""from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from chatbot.src.auth.chat_token import issue_chat_token


router = APIRouter(tags=["chat-auth"])


@router.post("/api/chat/auth-token")
def chat_auth_token(request: Request):
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")

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
    return f"""from chatbot.src.auth.chat_token import issue_chat_token


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
    return {{"site": "{site}", "site_id": "{site_id}", "access_token": token}}
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


def _build_food_order_adapter_template(order_api_base: str) -> str:
    return f"""import httpx


ORDER_API_BASE = "{order_api_base}"


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
"""


def _build_bilyeo_order_adapter_template(order_api_base: str) -> str:
    return f"""import httpx


ORDER_API_BASE = "{order_api_base}"


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
"""


def _build_ecommerce_order_adapter_template(order_api_base: str) -> str:
    return f"""import httpx


ORDER_API_BASE = "{order_api_base}"


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

    async def cancel_order(self, user_id: int, order_id: int, headers: dict | None = None) -> dict:
        order_base = self._order_base(user_id)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{{self.base_url}}{{order_base}}/{{order_id}}/cancel",
                headers=headers or {{}},
            )
            response.raise_for_status()
            return response.json()
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


class GeneratedOrderAdapterClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
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


def _build_frontend_mount_patch(target_file: str) -> str:
    return f"""--- a/{target_file}
+++ b/{target_file}
@@
+import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";
@@
+      <SharedChatbotWidget />
"""


def generate_frontend_mount_patch(run_root: str | Path) -> Path:
    root = Path(run_root)
    manifest = _load_manifest(root)
    analysis = manifest.get("analysis", {})
    mount_points = analysis.get("frontend_mount_points") or []
    target_file = str(mount_points[0]).strip() if mount_points else "frontend/src/App.js"
    source_root = Path(str(manifest.get("source_root") or "")).expanduser()

    output_path = root / "patches" / "frontend_widget_mount.patch"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_file = source_root / target_file
    if source_file.exists():
        source_lines = source_file.read_text(encoding="utf-8").splitlines(keepends=True)
        updated_lines = _build_frontend_mount_updated_lines(source_lines, target_file)
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


def _build_frontend_mount_updated_lines(source_lines: list[str], target_file: str) -> list[str]:
    updated_lines = list(source_lines)
    lower = target_file.lower()
    if lower.endswith(".vue"):
        widget_line = "  <SharedChatbotWidget />\n"
        if widget_line not in updated_lines:
            updated_lines.extend(["\n", "<template>\n", widget_line, "</template>\n"])
        return updated_lines

    import_line = 'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
    if import_line not in updated_lines:
        updated_lines = [import_line] + updated_lines
    widget_line = "  <SharedChatbotWidget />\n"
    if widget_line not in updated_lines:
        updated_lines.extend(["\n", widget_line])
    return updated_lines
