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
from .client import SiteCClient
from .auth import assert_site_c_context, build_site_c_auth_headers
from .mappers import (
    map_site_c_user,
    map_site_c_product_search,
    map_site_c_order,
    map_site_c_delivery,
    map_site_c_order_action,
)
import datetime


class SiteCAdapter(BaseEcommerceSupportAdapter):
    def __init__(self, client: SiteCClient):
        self._site_id = "site-c"  # 모듈명과 일치 (Ecommerce 백엔드)
        self.client = client

    @property
    def site_id(self) -> str:
        return self._site_id

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
            raw = await self.client.validate_session(build_site_c_auth_headers(ctx))
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
            input_data, build_site_c_auth_headers(ctx)
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

        raw = await self.client.get_order(
            ctx.userId, input_data, build_site_c_auth_headers(ctx)
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

    async def get_delivery_tracking(
        self, ctx: AuthenticatedContext, input_data: GetDeliveryTrackingInput
    ) -> GetDeliveryTrackingResult:
        self.assert_authenticated(ctx)

        # 권한 확인을 위해 주문 상태 조회 선행
        await self.get_order_status(
            ctx, GetOrderStatusInput(orderId=input_data.orderId)
        )

        raw = await self.client.get_delivery(input_data, build_site_c_auth_headers(ctx))
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

        # 권한 확인
        await self.get_order_status(
            ctx, GetOrderStatusInput(orderId=input_data.orderId)
        )

        if input_data.actionType.value == "cancel":
            raw = await self.client.submit_cancel(
                ctx.userId, input_data, build_site_c_auth_headers(ctx)
            )
            return map_site_c_order_action(raw)

        if input_data.actionType.value == "refund":
            raw = await self.client.submit_refund(
                ctx.userId, input_data, build_site_c_auth_headers(ctx)
            )
            return map_site_c_order_action(raw)

        raise AdapterError(
            "NOT_SUPPORTED", "ecommerce 사이트는 exchange API를 제공하지 않습니다."
        )
