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
            content=_build_generated_mappers(),
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
    import_line = (
        f"from .generated.{plan.site_key}.client import Generated{_class_name(plan.site_key)}Client\n"
    )
    adapter_line = (
        f"from .generated.{plan.site_key}.adapter import Generated{_class_name(plan.site_key)}Adapter\n"
    )
    init_block = [
        f'    generated_{plan.site_key}_url = os.environ.get("{plan.host_base_url_env_var}", food_url)\n',
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
    if register_line in updated and f"generated_{plan.site_key}_adapter" not in updated:
        updated = updated.replace(
            register_line,
            "    AdapterRegistry.register_many([\n"
            "        food_adapter,\n"
            "        bilyeo_adapter,\n"
            "        ecommerce_adapter,\n"
            f"        generated_{plan.site_key}_adapter,\n"
            "    ])\n",
        )
    return updated


def _build_generated_init(*, plan: ChatbotBridgePlan) -> str:
    class_name = _class_name(plan.site_key)
    return (
        f"from .client import Generated{class_name}Client\n"
        f"from .adapter import Generated{class_name}Adapter\n\n"
        f"__all__ = [\"Generated{class_name}Client\", \"Generated{class_name}Adapter\"]\n"
    )


def _build_generated_client(*, plan: ChatbotBridgePlan) -> str:
    class_name = _class_name(plan.site_key)
    return (
        "from ...site_a.client import SiteAClient\n\n\n"
        f"class Generated{class_name}Client(SiteAClient):\n"
        '    """Generated site-a compatible client for the host runtime."""\n\n'
        "    pass\n"
    )


def _build_generated_auth(*, plan: ChatbotBridgePlan) -> str:
    return (
        "from typing import Dict\n\n"
        "from ...schema import AuthenticatedContext, AdapterError\n\n\n"
        f'SITE_KEY = "{plan.site_key}"\n\n\n'
        "def assert_generated_context(ctx: AuthenticatedContext) -> None:\n"
        "    if ctx.siteId != SITE_KEY:\n"
        "        raise AdapterError(\n"
        '            "INVALID_INPUT",\n'
        '            "generated adapter context siteId mismatch",\n'
        '            {"expected": SITE_KEY, "received": ctx.siteId},\n'
        "        )\n\n\n"
        "def build_generated_auth_headers(ctx: AuthenticatedContext) -> Dict[str, str]:\n"
        "    cookie_map = ctx.cookies.copy() if ctx.cookies else {}\n"
        "    if ctx.accessToken:\n"
        '        cookie_map["session_token"] = ctx.accessToken\n'
        "    headers: Dict[str, str] = {}\n"
        "    if cookie_map:\n"
        '        headers["Cookie"] = \"; \".join([f\"{key}={value}\" for key, value in cookie_map.items()])\n'
        "    return headers\n"
    )


def _build_generated_mappers() -> str:
    return (
        "from ...site_a.mappers import (\n"
        "    map_site_a_delivery,\n"
        "    map_site_a_order,\n"
        "    map_site_a_order_action,\n"
        "    map_site_a_product_search,\n"
        "    map_site_a_user,\n"
        ")\n\n"
        "__all__ = [\n"
        '    "map_site_a_user",\n'
        '    "map_site_a_product_search",\n'
        '    "map_site_a_order",\n'
        '    "map_site_a_delivery",\n'
        '    "map_site_a_order_action",\n'
        "]\n"
    )


def _build_generated_adapter(*, plan: ChatbotBridgePlan) -> str:
    class_name = _class_name(plan.site_key)
    return (
        "import datetime\n\n"
        "from ...base import BaseEcommerceSupportAdapter\n"
        "from ...schema import (\n"
        "    AdapterError,\n"
        "    AdapterHealth,\n"
        "    AuthenticatedContext,\n"
        "    DeliveryStatus,\n"
        "    GetDeliveryTrackingInput,\n"
        "    GetDeliveryTrackingResult,\n"
        "    GetOrderStatusInput,\n"
        "    GetOrderStatusResult,\n"
        "    KnowledgeSearchInput,\n"
        "    KnowledgeSearchResult,\n"
        "    OrderStatus,\n"
        "    ProductSearchFilter,\n"
        "    ProductSearchResult,\n"
        "    SubmitOrderActionInput,\n"
        "    SubmitOrderActionResult,\n"
        "    User,\n"
        ")\n"
        f"from .client import Generated{class_name}Client\n"
        "from .auth import assert_generated_context, build_generated_auth_headers\n"
        "from .mappers import (\n"
        "    map_site_a_delivery,\n"
        "    map_site_a_order,\n"
        "    map_site_a_order_action,\n"
        "    map_site_a_product_search,\n"
        "    map_site_a_user,\n"
        ")\n\n\n"
        f"class Generated{class_name}Adapter(BaseEcommerceSupportAdapter):\n"
        f'    def __init__(self, client: Generated{class_name}Client):\n'
        f'        self._site_id = "{plan.site_key}"\n'
        "        self.client = client\n\n"
        "    @property\n"
        "    def site_id(self) -> str:\n"
        "        return self._site_id\n\n"
        "    def _normalize_order_status(self, raw: str) -> OrderStatus:\n"
        "        value = str(raw).lower()\n"
        "        return {\n"
        '            "pending": OrderStatus.PENDING,\n'
        '            "created": OrderStatus.PENDING,\n'
        '            "paid": OrderStatus.PAID,\n'
        '            "payment_complete": OrderStatus.PAID,\n'
        '            "preparing": OrderStatus.PREPARING,\n'
        '            "packing": OrderStatus.PREPARING,\n'
        '            "shipped": OrderStatus.SHIPPED,\n'
        '            "shipping": OrderStatus.SHIPPED,\n'
        '            "delivered": OrderStatus.DELIVERED,\n'
        '            "done": OrderStatus.DELIVERED,\n'
        '            "cancel_requested": OrderStatus.CANCEL_REQUESTED,\n'
        '            "cancelled": OrderStatus.CANCELLED,\n'
        '            "canceled": OrderStatus.CANCELLED,\n'
        '            "exchange_requested": OrderStatus.EXCHANGE_REQUESTED,\n'
        '            "refund_requested": OrderStatus.REFUND_REQUESTED,\n'
        '            "refunded": OrderStatus.REFUNDED,\n'
        "        }.get(value, OrderStatus.UNKNOWN)\n\n"
        "    def _normalize_delivery_status(self, raw: str) -> DeliveryStatus:\n"
        "        value = str(raw).lower()\n"
        "        return {\n"
        '            "ready": DeliveryStatus.READY,\n'
        '            "in_transit": DeliveryStatus.IN_TRANSIT,\n'
        '            "shipping": DeliveryStatus.IN_TRANSIT,\n'
        '            "out_for_delivery": DeliveryStatus.OUT_FOR_DELIVERY,\n'
        '            "delivered": DeliveryStatus.DELIVERED,\n'
        '            "delayed": DeliveryStatus.DELAYED,\n'
        "        }.get(value, DeliveryStatus.UNKNOWN)\n\n"
        "    async def healthcheck(self) -> AdapterHealth:\n"
        "        return AdapterHealth(siteId=self.site_id, ok=True, checkedAt=datetime.datetime.now().isoformat())\n\n"
        "    async def validate_auth(self, ctx: AuthenticatedContext) -> User:\n"
        "        self.assert_authenticated(ctx)\n"
        "        assert_generated_context(ctx)\n"
        "        raw = await self.client.validate_session(build_generated_auth_headers(ctx))\n"
        "        return map_site_a_user(raw, self.site_id)\n\n"
        "    async def search_products(self, ctx: AuthenticatedContext, input: ProductSearchFilter) -> ProductSearchResult:\n"
        "        self.assert_authenticated(ctx)\n"
        "        raw = await self.client.search_products(input, build_generated_auth_headers(ctx))\n"
        "        return map_site_a_product_search(raw, self.site_id)\n\n"
        "    async def search_knowledge(self, ctx: AuthenticatedContext, input: KnowledgeSearchInput) -> KnowledgeSearchResult:\n"
        '        raise AdapterError("NOT_SUPPORTED", "generated food adapter does not support knowledge search")\n\n'
        "    async def get_order_status(self, ctx: AuthenticatedContext, input: GetOrderStatusInput) -> GetOrderStatusResult:\n"
        "        self.assert_authenticated(ctx)\n"
        "        raw = await self.client.get_order(input, build_generated_auth_headers(ctx))\n"
        "        return map_site_a_order(raw, {\n"
        '            "site_id": self.site_id,\n'
        '            "current_user_id": ctx.userId,\n'
        '            "normalize_order_status": self._normalize_order_status,\n'
        '            "normalize_delivery_status": self._normalize_delivery_status,\n'
        "        })\n\n"
        "    async def get_delivery_tracking(self, ctx: AuthenticatedContext, input: GetDeliveryTrackingInput) -> GetDeliveryTrackingResult:\n"
        "        self.assert_authenticated(ctx)\n"
        "        await self.get_order_status(ctx, GetOrderStatusInput(orderId=input.orderId))\n"
        "        raw = await self.client.get_delivery(input, build_generated_auth_headers(ctx))\n"
        "        return map_site_a_delivery(raw, {\"normalize_delivery_status\": self._normalize_delivery_status})\n\n"
        "    async def submit_order_action(self, ctx: AuthenticatedContext, input: SubmitOrderActionInput) -> SubmitOrderActionResult:\n"
        "        self.assert_authenticated(ctx)\n"
        "        await self.get_order_status(ctx, GetOrderStatusInput(orderId=input.orderId))\n"
        "        raw = await self.client.submit_order_action(input, build_generated_auth_headers(ctx))\n"
        "        return map_site_a_order_action(raw)\n"
    )


def _class_name(site_key: str) -> str:
    return "".join(part.capitalize() for part in site_key.replace("-", "_").split("_"))
