from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.models.compile import (
    ChatbotBridgeBundle,
    EditOperation,
    SupportingArtifactBundle,
)
from chatbot.src.onboarding_v2.models.planning import ChatbotBridgePlan


def compile_generated_chatbot_bridge_bundle(
    *,
    chatbot_source_root: str | Path,
    plan: ChatbotBridgePlan,
) -> ChatbotBridgeBundle:
    root = Path(chatbot_source_root)
    setup_target = root / plan.setup_target
    if not setup_target.exists():
        raise ValueError(f"chatbot setup target not found: {plan.setup_target}")
    original_setup = setup_target.read_text(encoding="utf-8")
    updated_setup = _ensure_generated_adapter_registration(original_setup, plan=plan)

    supporting_files = [
        SupportingArtifactBundle(
            bundle_id=f"chatbot:{plan.site_key}:package-init",
            path=f"{plan.adapter_package}/__init__.py",
            content=_build_generated_init(plan=plan),
            reason="generated adapter package init",
        ),
        SupportingArtifactBundle(
            bundle_id=f"chatbot:{plan.site_key}:contracts",
            path=f"{plan.adapter_package}/contracts.py",
            content=_build_generated_contracts(plan=plan),
            reason="generated adapter contracts",
        ),
        SupportingArtifactBundle(
            bundle_id=f"chatbot:{plan.site_key}:client",
            path=f"{plan.adapter_package}/client.py",
            content=_build_generated_client(plan=plan),
            reason="generated adapter client",
        ),
        SupportingArtifactBundle(
            bundle_id=f"chatbot:{plan.site_key}:auth",
            path=f"{plan.adapter_package}/auth.py",
            content=_build_generated_auth(plan=plan),
            reason="generated adapter auth helpers",
        ),
        SupportingArtifactBundle(
            bundle_id=f"chatbot:{plan.site_key}:mappers",
            path=f"{plan.adapter_package}/mappers.py",
            content=_build_generated_mappers(plan=plan),
            reason="generated adapter mappers",
        ),
        SupportingArtifactBundle(
            bundle_id=f"chatbot:{plan.site_key}:adapter",
            path=f"{plan.adapter_package}/adapter.py",
            content=_build_generated_adapter(plan=plan),
            reason="generated adapter implementation",
        ),
    ]

    return ChatbotBridgeBundle(
        bundle_id=f"chatbot:{plan.site_key}:bridge",
        target_paths=[plan.setup_target],
        operations=[
            EditOperation(
                path=plan.setup_target,
                operation="replace_text",
                old=original_setup,
                new=updated_setup,
            )
        ],
        supporting_files=supporting_files,
    )


def _ensure_generated_adapter_registration(content: str, *, plan: ChatbotBridgePlan) -> str:
    site_var_name = plan.site_key.replace("-", "_")
    site_api_env_var = f"{site_var_name.upper()}_API_URL"
    import_line = (
        f"from .generated.{plan.site_key}.client import Generated{_class_name(plan.site_key)}Client\n"
    )
    adapter_line = (
        f"from .generated.{plan.site_key}.adapter import Generated{_class_name(plan.site_key)}Adapter\n"
    )
    init_block = [
        (
            f'    generated_{plan.site_key}_url = (\n'
            f'        os.environ.get("{plan.host_base_url_env_var}")\n'
            f'        or os.environ.get("{site_api_env_var}")\n'
            f'        or locals().get("{site_var_name}_url", "")\n'
            f"    )\n"
        ),
        f"    generated_{plan.site_key}_client = Generated{_class_name(plan.site_key)}Client(base_url=generated_{plan.site_key}_url)\n",
        f"    generated_{plan.site_key}_adapter = Generated{_class_name(plan.site_key)}Adapter(client=generated_{plan.site_key}_client)\n",
    ]
    register_line = "    AdapterRegistry.register_many([food_adapter, bilyeo_adapter, ecommerce_adapter])\n"
    updated = content
    if import_line not in updated:
        updated = updated.replace(
            "from .site_c.adapter import SiteCAdapter\n",
            "from .site_c.adapter import SiteCAdapter\n" + import_line + adapter_line,
        )
    if init_block[0] not in updated:
        updated = updated.replace(
            "    ecommerce_client = SiteCClient(base_url=ecommerce_url)\n"
            "    ecommerce_adapter = SiteCAdapter(client=ecommerce_client)\n",
            "    ecommerce_client = SiteCClient(base_url=ecommerce_url)\n"
            "    ecommerce_adapter = SiteCAdapter(client=ecommerce_client)\n"
            + "".join(init_block),
        )
    generated_register_entry = f"        generated_{plan.site_key}_adapter,\n"
    if register_line in updated and generated_register_entry not in updated:
        updated = updated.replace(
            register_line,
            "    AdapterRegistry.register_many([\n"
            "        food_adapter,\n"
            "        bilyeo_adapter,\n"
            "        ecommerce_adapter,\n"
            + generated_register_entry
            + "    ])\n",
        )
    return updated


def _build_generated_init(*, plan: ChatbotBridgePlan) -> str:
    class_name = _class_name(plan.site_key)
    return (
        f"from .client import Generated{class_name}Client\n"
        f"from .adapter import Generated{class_name}Adapter\n\n"
        f"__all__ = [\"Generated{class_name}Client\", \"Generated{class_name}Adapter\"]\n"
    )


def _build_generated_contracts(*, plan: ChatbotBridgePlan) -> str:
    return (
        "from ....onboarding_v2.models.planning import (\n"
        "    ResolvedOrderActionContract,\n"
        "    ResolvedRequestFieldContract,\n"
        "    ResolvedResponseContract,\n"
        ")\n\n\n"
        f"RESPONSE_CONTRACT = ResolvedResponseContract({_render_response_contract_expr(plan.response_contract)})\n"
        f"ORDER_ACTION_CONTRACT = ResolvedOrderActionContract({_render_order_action_contract_expr(plan.order_action_contract)})\n"
    )


def _build_generated_client(*, plan: ChatbotBridgePlan) -> str:
    class_name = _class_name(plan.site_key)
    action_endpoints = {
        action: path
        for action, path in sorted((plan.order_action_endpoints or {}).items())
        if str(action).strip() and str(path).strip()
    }
    return (
        "from typing import Any, Dict, Optional\n\n"
        "import httpx\n\n"
        "from ...order_action_profiles import build_order_action_request_from_contract\n"
        "from ...schema import (\n"
        "    AdapterError,\n"
        "    GetDeliveryTrackingInput,\n"
        "    GetOrderStatusInput,\n"
        "    ProductSearchFilter,\n"
        "    SubmitOrderActionInput,\n"
        ")\n"
        "from .contracts import ORDER_ACTION_CONTRACT, RESPONSE_CONTRACT\n\n\n"
        f"class Generated{class_name}Client:\n"
        '    """Generated host client from verified onboarding seams."""\n\n'
        f'    AUTH_VALIDATION_ENDPOINT = "{plan.auth_validation_endpoint}"\n'
        f'    PRODUCT_SEARCH_ENDPOINT = "{plan.product_search_endpoint}"\n'
        f'    ORDER_LIST_ENDPOINT = "{plan.order_list_endpoint}"\n'
        f'    ORDER_DETAIL_ENDPOINT = "{plan.order_detail_endpoint}"\n'
        f'    DEFAULT_ORDER_ACTION_ENDPOINT = "{plan.order_action_endpoint}"\n'
        f"    ORDER_ACTION_ENDPOINTS = {action_endpoints!r}\n"
        "    RESPONSE_CONTRACT = RESPONSE_CONTRACT\n"
        "    ORDER_ACTION_CONTRACT = ORDER_ACTION_CONTRACT\n\n"
        "    def __init__(self, base_url: str, timeout_ms: int = 10000, default_headers: Optional[Dict[str, str]] = None):\n"
        '        self.base_url = base_url.rstrip("/")\n'
        "        self.timeout = timeout_ms / 1000.0\n"
        "        self.default_headers = default_headers or {}\n\n"
        "    async def _request(self, method: str, path: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> Any:\n"
        '        req_headers = {"Content-Type": "application/json", **self.default_headers, **(headers or {})}\n'
        '        url = f"{self.base_url}{path}"\n'
        "        async with httpx.AsyncClient(timeout=self.timeout) as client:\n"
        "            try:\n"
        "                response = await client.request(method, url, headers=req_headers, params=params, json=json)\n"
        "                response.raise_for_status()\n"
        "                return response.json() if response.text else None\n"
        "            except httpx.HTTPStatusError as exc:\n"
        "                response = exc.response\n"
        "                message = None\n"
        "                try:\n"
        "                    payload = response.json()\n"
        '                    message = payload.get("detail") or payload.get("message")\n'
        "                except Exception:\n"
        "                    message = response.text or None\n"
        '                code = {400: "INVALID_INPUT", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(response.status_code, "GENERATED_UPSTREAM_ERROR")\n'
        '                raise AdapterError(code, message or f"요청 실패: {exc}", {"url": url, "status_code": response.status_code}) from exc\n'
        "            except httpx.HTTPError as exc:\n"
        '                raise AdapterError("GENERATED_UPSTREAM_ERROR", f"요청 실패: {exc}", {"url": url}) from exc\n\n'
        "    def _format_path(self, template: str, *, order_id: str | None = None, user_id: str | None = None) -> str:\n"
        "        path = template\n"
        "        if user_id is not None:\n"
        '            path = path.replace("{user_id}", str(user_id))\n'
        "        if order_id is not None:\n"
        '            path = path.replace("{order_id}", str(order_id))\n'
        "        return path\n\n"
        "    async def validate_session(self, headers: Dict[str, str]) -> Any:\n"
        '        return await self._request("GET", self.AUTH_VALIDATION_ENDPOINT, headers=headers)\n\n'
        "    async def search_products(self, filter_input: ProductSearchFilter, headers: Dict[str, str]) -> Any:\n"
        "        params = {}\n"
        "        if filter_input.query:\n"
        '            params["search"] = filter_input.query\n'
        "        if filter_input.categoryIds:\n"
        '            params["category"] = filter_input.categoryIds[0]\n'
        '        return await self._request("GET", self.PRODUCT_SEARCH_ENDPOINT, headers=headers, params=params)\n\n'
        "    async def get_order(self, input_data: GetOrderStatusInput, headers: Dict[str, str], *, user_id: str | None = None) -> Any:\n"
        '        if self.RESPONSE_CONTRACT.order_profile == "orders_collection_scan":\n'
        "            return await self.list_orders(headers, user_id=user_id)\n"
        '        path = self._format_path(self.ORDER_DETAIL_ENDPOINT, order_id=input_data.orderId, user_id=user_id)\n'
        '        return await self._request("GET", path, headers=headers)\n\n'
        "    async def list_orders(self, headers: Dict[str, str], *, user_id: str | None = None, limit: int | None = None) -> Any:\n"
        "        params = {}\n"
        '        if limit is not None and self.RESPONSE_CONTRACT.order_profile == "user_scoped_order_service":\n'
        '            params["limit"] = limit\n'
        '        path = self._format_path(self.ORDER_LIST_ENDPOINT, user_id=user_id)\n'
        '        return await self._request("GET", path, headers=headers, params=params or None)\n\n'
        "    async def get_delivery(self, input_data: GetDeliveryTrackingInput, headers: Dict[str, str], *, user_id: str | None = None) -> Any:\n"
        "        return await self.get_order(GetOrderStatusInput(orderId=input_data.orderId), headers, user_id=user_id)\n\n"
        "    async def submit_order_action(self, input_data: SubmitOrderActionInput, headers: Dict[str, str]) -> Any:\n"
        "        request_spec = build_order_action_request_from_contract(\n"
        "            self.ORDER_ACTION_CONTRACT,\n"
        "            input_data,\n"
        "            default_endpoint=self.DEFAULT_ORDER_ACTION_ENDPOINT,\n"
        "            order_action_endpoints=self.ORDER_ACTION_ENDPOINTS,\n"
        "            format_path=self._format_path,\n"
        "        )\n"
        "        return await self._request(\n"
        "            request_spec.method,\n"
        "            request_spec.path,\n"
        "            headers=headers,\n"
        "            params=request_spec.params,\n"
        "            json=request_spec.json,\n"
        "        )\n"
    )


def _build_generated_auth(*, plan: ChatbotBridgePlan) -> str:
    contract_expr = _render_auth_contract_expr(plan.auth_contract)
    return (
        "from typing import Dict\n\n"
        "from ...auth_headers import assert_context_site, build_auth_headers_from_contract\n"
        "from ...schema import AuthenticatedContext\n"
        "from ....onboarding_v2.models.planning import ResolvedAuthContract\n\n\n"
        f'SITE_KEY = "{plan.site_key}"\n'
        f"AUTH_CONTRACT = ResolvedAuthContract({contract_expr})\n\n\n"
        "def assert_generated_context(ctx: AuthenticatedContext) -> None:\n"
        '    assert_context_site(ctx, expected_site_id=SITE_KEY, label="generated adapter")\n\n\n'
        "def build_generated_auth_headers(ctx: AuthenticatedContext) -> Dict[str, str]:\n"
        "    return build_auth_headers_from_contract(AUTH_CONTRACT, ctx)\n"
    )


def _build_generated_mappers(*, plan: ChatbotBridgePlan) -> str:
    return (
        "from typing import Any\n\n"
        "from ...order_action_profiles import map_order_action_result_from_contract\n"
        "from ...response_profiles import (\n"
        "    map_delivery_from_contract,\n"
        "    map_order_from_contract,\n"
        "    map_product_search_from_contract,\n"
        "    map_user_from_contract,\n"
        ")\n"
        "from .contracts import ORDER_ACTION_CONTRACT, RESPONSE_CONTRACT\n\n"
        "def map_generated_user(raw: Any, site_id: str):\n"
        "    return map_user_from_contract(RESPONSE_CONTRACT, raw, site_id)\n\n"
        "def map_generated_product_search(raw: Any, site_id: str):\n"
        "    return map_product_search_from_contract(RESPONSE_CONTRACT, raw, site_id)\n\n"
        "def map_generated_order(raw: Any, deps: dict):\n"
        "    return map_order_from_contract(RESPONSE_CONTRACT, raw, deps)\n\n"
        "def map_generated_delivery(raw: Any, deps: dict):\n"
        "    return map_delivery_from_contract(RESPONSE_CONTRACT, raw, deps)\n\n"
        "def map_generated_order_action(raw: Any):\n"
        "    return map_order_action_result_from_contract(ORDER_ACTION_CONTRACT, raw)\n\n"
        "__all__ = [\n"
        '    "map_generated_user",\n'
        '    "map_generated_product_search",\n'
        '    "map_generated_order",\n'
        '    "map_generated_delivery",\n'
        '    "map_generated_order_action",\n'
        "]\n"
    )


def _build_generated_adapter(*, plan: ChatbotBridgePlan) -> str:
    class_name = _class_name(plan.site_key)
    return (
        "import datetime\n\n"
        "from ...base import BaseEcommerceSupportAdapter\n"
        "from ...response_profiles import (\n"
        "    normalize_delivery_status_from_contract,\n"
        "    normalize_order_status_from_contract,\n"
        ")\n"
        "from ...schema import (\n"
        "    AdapterError,\n"
        "    AdapterHealth,\n"
        "    AuthenticatedContext,\n"
        "    GetDeliveryTrackingInput,\n"
        "    GetDeliveryTrackingResult,\n"
        "    GetOrderStatusInput,\n"
        "    GetOrderStatusResult,\n"
        "    KnowledgeSearchInput,\n"
        "    KnowledgeSearchResult,\n"
        "    ProductSearchFilter,\n"
        "    ProductSearchResult,\n"
        "    SubmitOrderActionInput,\n"
        "    SubmitOrderActionResult,\n"
        "    User,\n"
        ")\n"
        "from ....onboarding_v2.models.planning import (\n"
        "    ResolvedAuthContract,\n"
        "    ResolvedOrderActionContract,\n"
        "    ResolvedResponseContract,\n"
        ")\n"
        f"from .client import Generated{class_name}Client\n"
        "from .contracts import ORDER_ACTION_CONTRACT, RESPONSE_CONTRACT\n"
        "from .auth import AUTH_CONTRACT, assert_generated_context, build_generated_auth_headers\n"
        "from .mappers import (\n"
        "    map_generated_delivery,\n"
        "    map_generated_order,\n"
        "    map_generated_order_action,\n"
        "    map_generated_product_search,\n"
        "    map_generated_user,\n"
        ")\n\n\n"
        f"class Generated{class_name}Adapter(BaseEcommerceSupportAdapter):\n"
        f'    def __init__(self, client: Generated{class_name}Client):\n'
        f'        self._site_id = "{plan.site_key}"\n'
        "        self._auth_contract = AUTH_CONTRACT\n"
        "        self._response_contract = RESPONSE_CONTRACT\n"
        "        self._order_action_contract = ORDER_ACTION_CONTRACT\n"
        "        self.client = client\n\n"
        "    @property\n"
        "    def site_id(self) -> str:\n"
        "        return self._site_id\n\n"
        "    @property\n"
        "    def auth_contract(self) -> ResolvedAuthContract:\n"
        "        return self._auth_contract\n\n"
        "    @property\n"
        "    def response_contract(self) -> ResolvedResponseContract:\n"
        "        return self._response_contract\n\n"
        "    @property\n"
        "    def order_action_contract(self) -> ResolvedOrderActionContract:\n"
        "        return self._order_action_contract\n\n"
        "    def _normalize_order_status(self, raw: str):\n"
        "        return normalize_order_status_from_contract(self.response_contract, raw)\n\n"
        "    def _normalize_delivery_status(self, raw: str):\n"
        "        return normalize_delivery_status_from_contract(self.response_contract, raw)\n\n"
        "    async def healthcheck(self) -> AdapterHealth:\n"
        "        return AdapterHealth(siteId=self.site_id, ok=True, checkedAt=datetime.datetime.now().isoformat())\n\n"
        "    async def validate_auth(self, ctx: AuthenticatedContext) -> User:\n"
        "        self.assert_authenticated(ctx)\n"
        "        assert_generated_context(ctx)\n"
        "        raw = await self.client.validate_session(build_generated_auth_headers(ctx))\n"
        "        return map_generated_user(raw, self.site_id)\n\n"
        "    async def search_products(self, ctx: AuthenticatedContext, input: ProductSearchFilter) -> ProductSearchResult:\n"
        "        self.assert_authenticated(ctx)\n"
        "        raw = await self.client.search_products(input, build_generated_auth_headers(ctx))\n"
        "        return map_generated_product_search(raw, self.site_id)\n\n"
        "    async def search_knowledge(self, ctx: AuthenticatedContext, input: KnowledgeSearchInput) -> KnowledgeSearchResult:\n"
        '        raise AdapterError("NOT_SUPPORTED", "generated food adapter does not support knowledge search")\n\n'
        "    async def get_order_status(self, ctx: AuthenticatedContext, input: GetOrderStatusInput) -> GetOrderStatusResult:\n"
        "        self.assert_authenticated(ctx)\n"
        "        raw = await self.client.get_order(input, build_generated_auth_headers(ctx), user_id=ctx.userId)\n"
        "        return map_generated_order(raw, {\n"
        '            "site_id": self.site_id,\n'
        '            "current_user_id": ctx.userId,\n'
        '            "target_order_id": str(input.orderId),\n'
        '            "normalize_order_status": self._normalize_order_status,\n'
        '            "normalize_delivery_status": self._normalize_delivery_status,\n'
        "        })\n\n"
        "    async def get_delivery_tracking(self, ctx: AuthenticatedContext, input: GetDeliveryTrackingInput) -> GetDeliveryTrackingResult:\n"
        "        self.assert_authenticated(ctx)\n"
        "        await self.get_order_status(ctx, GetOrderStatusInput(orderId=input.orderId))\n"
        "        raw = await self.client.get_delivery(input, build_generated_auth_headers(ctx), user_id=ctx.userId)\n"
        "        return map_generated_delivery(raw, {\"target_order_id\": str(input.orderId), \"normalize_delivery_status\": self._normalize_delivery_status})\n\n"
        "    async def submit_order_action(self, ctx: AuthenticatedContext, input: SubmitOrderActionInput) -> SubmitOrderActionResult:\n"
        "        self.assert_authenticated(ctx)\n"
        "        await self.get_order_status(ctx, GetOrderStatusInput(orderId=input.orderId))\n"
        "        raw = await self.client.submit_order_action(input, build_generated_auth_headers(ctx))\n"
        "        return map_generated_order_action(raw)\n"
    )


def _class_name(site_key: str) -> str:
    return "".join(part.capitalize() for part in site_key.replace("-", "_").split("_"))


def _render_auth_contract_expr(auth_contract) -> str:
    contract_kwargs: list[str] = [f'transport="{auth_contract.transport}"']
    if auth_contract.session_cookie_name:
        contract_kwargs.append(
            f'session_cookie_name="{auth_contract.session_cookie_name}"'
        )
    if auth_contract.csrf_cookie_name:
        contract_kwargs.append(
            f'csrf_cookie_name="{auth_contract.csrf_cookie_name}"'
        )
    if auth_contract.csrf_header_name:
        contract_kwargs.append(
            f'csrf_header_name="{auth_contract.csrf_header_name}"'
        )
    return ", ".join(contract_kwargs)


def _render_request_field_contract_expr(request_fields) -> str:
    field_kwargs: list[str] = [
        f'action="{request_fields.action}"',
        f'reason="{request_fields.reason}"',
        f'new_option_id="{request_fields.new_option_id}"',
    ]
    return ", ".join(field_kwargs)


def _render_response_contract_expr(response_contract) -> str:
    contract_kwargs = [
        f'user_profile="{response_contract.user_profile}"',
        f'product_profile="{response_contract.product_profile}"',
        f'order_profile="{response_contract.order_profile}"',
        f'delivery_profile="{response_contract.delivery_profile}"',
        f'order_status_profile="{response_contract.order_status_profile}"',
        f'delivery_status_profile="{response_contract.delivery_status_profile}"',
        f'order_identifier_mode="{response_contract.order_identifier_mode}"',
    ]
    return ", ".join(contract_kwargs)


def _render_order_action_contract_expr(order_action_contract) -> str:
    contract_kwargs = [
        f'submission_mode="{order_action_contract.submission_mode}"',
        f"supported_actions={list(order_action_contract.supported_actions)!r}",
        f"request_fields=ResolvedRequestFieldContract({_render_request_field_contract_expr(order_action_contract.request_fields)})",
    ]
    if order_action_contract.reason_transport:
        contract_kwargs.append(
            f'reason_transport="{order_action_contract.reason_transport}"'
        )
    if order_action_contract.new_option_transport:
        contract_kwargs.append(
            f'new_option_transport="{order_action_contract.new_option_transport}"'
        )
    if order_action_contract.result_profile:
        contract_kwargs.append(
            f'result_profile="{order_action_contract.result_profile}"'
        )
    return ", ".join(contract_kwargs)
