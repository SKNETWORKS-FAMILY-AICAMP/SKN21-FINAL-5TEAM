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
from .client import SiteBClient
from .auth import AUTH_CONTRACT, assert_site_b_context
from .mappers import (
    map_site_b_user,
    map_site_b_product_search,
    map_site_b_order,
    map_site_b_delivery,
)
import datetime

from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract
from chatbot.src.onboarding_v2.models.planning import (
    ResolvedOrderActionContract,
    ResolvedRequestFieldContract,
    ResolvedResponseContract,
)


class SiteBAdapter(BaseEcommerceSupportAdapter):
    def __init__(self, client: SiteBClient):
        self._site_id = "site-b"  # 모듈명과 일치 (Bilyeo 백엔드)
        self._auth_contract = AUTH_CONTRACT
        self._response_contract = ResolvedResponseContract(
            user_profile="orders_collection_user_id",
            product_profile="products_wrapper_collection",
            order_profile="orders_collection_scan",
            delivery_profile="orders_collection_scan",
            order_status_profile="korean_labels",
            delivery_status_profile="korean_labels",
            order_identifier_mode="direct_order_id",
        )
        self._order_action_contract = ResolvedOrderActionContract(
            submission_mode="read_only",
            supported_actions=["list_orders", "get_order_status"],
            request_fields=ResolvedRequestFieldContract(),
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
        assert_site_b_context(ctx)

        try:
            raw = await self.client.validate_session(
                build_auth_headers_from_contract(self.auth_contract, ctx)
            )
            has_orders_array = isinstance(raw.get("orders"), list)
            if not has_orders_array:
                raise AdapterError("UNAUTHORIZED", "토큰 검증에 실패했습니다.")

            user = map_site_b_user(raw, self.site_id)
            user.id = ctx.userId
            return user
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
        return map_site_b_product_search(raw, self.site_id)

    async def search_knowledge(
        self, ctx: AuthenticatedContext, input_data: KnowledgeSearchInput
    ) -> KnowledgeSearchResult:
        raise AdapterError(
            "NOT_SUPPORTED", "bilyeo 사이트는 지식문서 검색 API를 제공하지 않습니다."
        )

    async def get_order_status(
        self, ctx: AuthenticatedContext, input_data: GetOrderStatusInput
    ) -> GetOrderStatusResult:
        self.assert_authenticated(ctx)

        raw = await self.client.get_order(
            input_data,
            build_auth_headers_from_contract(self.auth_contract, ctx),
        )
        mapped = map_site_b_order(
            raw,
            {
                "site_id": self.site_id,
                "current_user_id": ctx.userId,
                "target_order_id": str(input_data.orderId),
                "normalize_order_status": self._normalize_order_status,
            },
        )

        if (
            not mapped.order.orderId
            or mapped.order.orderId != str(input_data.orderId)
            or not mapped.order.items
        ):
            raise AdapterError(
                "NOT_FOUND", "주문을 찾을 수 없습니다.", {"orderId": input_data.orderId}
            )

        return mapped

    async def get_delivery_tracking(
        self, ctx: AuthenticatedContext, input_data: GetDeliveryTrackingInput
    ) -> GetDeliveryTrackingResult:
        self.assert_authenticated(ctx)

        # 권한 확인을 위해 주문 상태 조회 선행
        await self.get_order_status(
            ctx, GetOrderStatusInput(orderId=input_data.orderId)
        )

        raw = await self.client.get_delivery(
            input_data,
            build_auth_headers_from_contract(self.auth_contract, ctx),
        )
        return map_site_b_delivery(
            raw,
            {
                "target_order_id": str(input_data.orderId),
                "normalize_delivery_status": self._normalize_delivery_status,
            },
        )

    async def submit_order_action(
        self, ctx: AuthenticatedContext, input_data: SubmitOrderActionInput
    ) -> SubmitOrderActionResult:
        raise AdapterError(
            "NOT_SUPPORTED",
            "bilyeo 사이트는 주문 취소/환불/교환 API를 제공하지 않습니다.",
        )
