from ..schema import (
    AuthenticatedContext,
    User,
    ProductSearchFilter,
    ProductSearchResult,
    KnowledgeSearchInput,
    KnowledgeSearchResult,
    GetOrderStatusInput,
    GetOrderStatusResult,
    GetDeliveryTrackingInput,
    GetDeliveryTrackingResult,
    SubmitOrderActionInput,
    SubmitOrderActionResult,
    AdapterHealth,
    AdapterError,
    OrderStatus,
    DeliveryStatus,
)
from ..base import BaseEcommerceSupportAdapter
from ..auth_headers import build_auth_headers_from_contract
from .client import SiteCClient
from .auth import AUTH_CONTRACT, assert_site_c_context
from .mappers import (
    map_site_c_user,
    map_site_c_product_search,
    map_site_c_order,
    map_site_c_delivery,
    map_site_c_order_action,
)
import datetime

from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract
from chatbot.src.onboarding_v2.models.planning import (
    ResolvedOrderActionContract,
    ResolvedRequestFieldContract,
    ResolvedResponseContract,
)


class SiteCAdapter(BaseEcommerceSupportAdapter):
    def __init__(self, client: SiteCClient):
        self._site_id = "site-c"  # 모듈명과 일치 (Ecommerce 백엔드)
        self._auth_contract = AUTH_CONTRACT
        self._response_contract = ResolvedResponseContract(
            user_profile="direct_user_session",
            product_profile="catalog_items_keyword_results",
            order_profile="user_scoped_order_service",
            delivery_profile="shipping_tracking_record",
            order_status_profile="service_tokens",
            delivery_status_profile="service_tokens",
            order_identifier_mode="order_number_with_internal_resolution",
        )
        self._order_action_contract = ResolvedOrderActionContract(
            submission_mode="per_action_query_endpoint",
            supported_actions=["list_orders", "get_order_status", "cancel", "refund"],
            request_fields=ResolvedRequestFieldContract(),
            reason_transport="query_param",
            new_option_transport="unsupported",
            result_profile="requested_message",
        )
        self.client = client

    @property
    def site_id(self) -> str:
        return self._site_id

    @property
    def auth_contract(self) -> ResolvedAuthContract:
        return self._auth_contract

    @property
    def response_contract(self) -> ResolvedResponseContract:
        return self._response_contract

    @property
    def order_action_contract(self) -> ResolvedOrderActionContract:
        return self._order_action_contract

    def _normalize_order_status(self, raw: str) -> OrderStatus:
        v = str(raw).lower()
        if v in ["pending", "created"]:
            return OrderStatus.PENDING
        if v in ["paid", "payment_complete"]:
            return OrderStatus.PAID
        if v in ["preparing", "packing"]:
            return OrderStatus.PREPARING
        if v in ["shipped", "shipping"]:
            return OrderStatus.SHIPPED
        if v in ["delivered", "done"]:
            return OrderStatus.DELIVERED
        if v in ["cancel_requested"]:
            return OrderStatus.CANCEL_REQUESTED
        if v in ["cancelled", "canceled"]:
            return OrderStatus.CANCELLED
        if v in ["exchange_requested"]:
            return OrderStatus.EXCHANGE_REQUESTED
        if v in ["refund_requested"]:
            return OrderStatus.REFUND_REQUESTED
        if v in ["refunded"]:
            return OrderStatus.REFUNDED
        return OrderStatus.UNKNOWN

    def _normalize_delivery_status(self, raw: str) -> DeliveryStatus:
        v = str(raw).lower()
        if v in ["ready"]:
            return DeliveryStatus.READY
        if v in ["in_transit", "shipping"]:
            return DeliveryStatus.IN_TRANSIT
        if v in ["out_for_delivery"]:
            return DeliveryStatus.OUT_FOR_DELIVERY
        if v in ["delivered"]:
            return DeliveryStatus.DELIVERED
        if v in ["delayed"]:
            return DeliveryStatus.DELAYED
        return DeliveryStatus.UNKNOWN

    async def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(
            siteId=self.site_id, ok=True, checkedAt=datetime.datetime.now().isoformat()
        )

    async def validate_auth(self, ctx: AuthenticatedContext) -> User:
        self.assert_authenticated(ctx)
        assert_site_c_context(ctx)

        try:
            raw = await self.client.validate_session(
                build_auth_headers_from_contract(self.auth_contract, ctx)
            )
            mapped = map_site_c_user(raw, self.site_id)
            if not mapped.id:
                raise AdapterError("UNAUTHORIZED", "로그인이 필요합니다.")
            if mapped.id != str(ctx.userId):
                raise AdapterError(
                    "FORBIDDEN", "세션 사용자와 요청 사용자가 일치하지 않습니다."
                )
            return mapped
        except AdapterError:
            raise
        except Exception as e:
            raise AdapterError(
                "UPSTREAM_ERROR", f"외부 서비스 호출 중 오류가 발생했습니다: {e}"
            )

    async def search_products(
        self, ctx: AuthenticatedContext, input_data: ProductSearchFilter
    ) -> ProductSearchResult:
        self.assert_authenticated(ctx)
        raw = await self.client.search_products(
            input_data,
            build_auth_headers_from_contract(self.auth_contract, ctx),
        )
        return map_site_c_product_search(raw, self.site_id)

    async def search_knowledge(
        self, ctx: AuthenticatedContext, input_data: KnowledgeSearchInput
    ) -> KnowledgeSearchResult:
        raise AdapterError(
            "NOT_SUPPORTED",
            "ecommerce 사이트는 독립 knowledge 검색 API를 제공하지 않습니다.",
        )

    async def get_order_status(
        self, ctx: AuthenticatedContext, input_data: GetOrderStatusInput
    ) -> GetOrderStatusResult:
        self.assert_authenticated(ctx)
        headers = build_auth_headers_from_contract(self.auth_contract, ctx)
        resolved_order_id = await self._resolve_internal_order_id(
            input_data.orderId, headers
        )

        raw = await self.client.get_order(
            ctx.userId, GetOrderStatusInput(orderId=resolved_order_id), headers
        )
        mapped = map_site_c_order(
            raw,
            {
                "site_id": self.site_id,
                "normalize_order_status": self._normalize_order_status,
            },
        )
        self.assert_order_ownership(mapped.order.userId, ctx)
        return mapped

    async def list_orders(
        self,
        ctx: AuthenticatedContext,
        limit: int = 20,
    ) -> list[dict]:
        self.assert_authenticated(ctx)
        headers = build_auth_headers_from_contract(self.auth_contract, ctx)
        raw = await self.client.list_orders(ctx.userId, headers, limit=limit)
        orders = raw.get("orders") if isinstance(raw, dict) else raw
        return orders if isinstance(orders, list) else []

    async def get_delivery_tracking(
        self, ctx: AuthenticatedContext, input_data: GetDeliveryTrackingInput
    ) -> GetDeliveryTrackingResult:
        self.assert_authenticated(ctx)
        headers = build_auth_headers_from_contract(self.auth_contract, ctx)
        resolved_order_id = await self._resolve_internal_order_id(
            input_data.orderId, headers
        )

        # 권한 확인을 위해 주문 상태 조회 선행
        await self.get_order_status(
            ctx, GetOrderStatusInput(orderId=resolved_order_id)
        )

        raw = await self.client.get_delivery(
            GetDeliveryTrackingInput(orderId=resolved_order_id), headers
        )
        if not raw:
            raise AdapterError(
                "NOT_FOUND",
                "배송 정보를 찾을 수 없습니다.",
                {"orderId": input_data.orderId},
            )

        return map_site_c_delivery(
            raw, {"normalize_delivery_status": self._normalize_delivery_status}
        )

    async def submit_order_action(
        self, ctx: AuthenticatedContext, input_data: SubmitOrderActionInput
    ) -> SubmitOrderActionResult:
        self.assert_authenticated(ctx)
        headers = build_auth_headers_from_contract(self.auth_contract, ctx)
        resolved_order_id = await self._resolve_internal_order_id(
            input_data.orderId, headers
        )
        resolved_input = input_data.model_copy(update={"orderId": resolved_order_id})

        # 권한 확인
        await self.get_order_status(
            ctx, GetOrderStatusInput(orderId=resolved_order_id)
        )

        if input_data.actionType.value == "cancel":
            raw = await self.client.submit_cancel(
                ctx.userId, resolved_input, headers
            )
            return map_site_c_order_action(raw)

        if input_data.actionType.value == "refund":
            raw = await self.client.submit_refund(
                ctx.userId, resolved_input, headers
            )
            return map_site_c_order_action(raw)

        raise AdapterError(
            "NOT_SUPPORTED", "ecommerce 사이트는 exchange API를 제공하지 않습니다."
        )

    async def _resolve_internal_order_id(
        self, order_id: str, headers: dict[str, str]
    ) -> str:
        candidate = str(order_id).strip()
        if candidate.isdigit():
            return candidate

        raw = await self.client.get_order_by_number(candidate, headers)
        internal_id = raw.get("id") if isinstance(raw, dict) else None
        if internal_id is None:
            raise AdapterError(
                "NOT_FOUND",
                "주문 번호에 해당하는 주문을 찾을 수 없습니다.",
                {"order_number": candidate},
            )
        return str(internal_id)
