from abc import ABC, abstractmethod
from typing import Dict, List

from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract
from chatbot.src.onboarding_v2.models.planning import (
    ResolvedOrderActionContract,
    ResolvedResponseContract,
)

from .schema import (
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
)


class BaseEcommerceSupportAdapter(ABC):
    """
    공통 프론트엔드 어댑터 인터페이스를 Python 환경에 맞게 추상화한 클래스입니다.
    """

    @property
    @abstractmethod
    def site_id(self) -> str:
        pass

    @property
    @abstractmethod
    def auth_contract(self) -> ResolvedAuthContract:
        pass

    @property
    @abstractmethod
    def response_contract(self) -> ResolvedResponseContract:
        pass

    @property
    @abstractmethod
    def order_action_contract(self) -> ResolvedOrderActionContract:
        pass

    @abstractmethod
    async def validate_auth(self, ctx: AuthenticatedContext) -> User:
        pass

    @abstractmethod
    async def search_products(
        self, ctx: AuthenticatedContext, input: ProductSearchFilter
    ) -> ProductSearchResult:
        pass

    @abstractmethod
    async def search_knowledge(
        self, ctx: AuthenticatedContext, input: KnowledgeSearchInput
    ) -> KnowledgeSearchResult:
        pass

    @abstractmethod
    async def get_order_status(
        self, ctx: AuthenticatedContext, input: GetOrderStatusInput
    ) -> GetOrderStatusResult:
        pass

    @abstractmethod
    async def get_delivery_tracking(
        self, ctx: AuthenticatedContext, input: GetDeliveryTrackingInput
    ) -> GetDeliveryTrackingResult:
        pass

    @abstractmethod
    async def submit_order_action(
        self, ctx: AuthenticatedContext, input: SubmitOrderActionInput
    ) -> SubmitOrderActionResult:
        pass

    @abstractmethod
    async def healthcheck(self) -> AdapterHealth:
        pass

    def assert_authenticated(self, ctx: AuthenticatedContext) -> None:
        if not ctx.userId:
            raise AdapterError("UNAUTHORIZED", "로그인이 필요합니다.")

    def assert_order_ownership(
        self, order_user_id: str, ctx: AuthenticatedContext
    ) -> None:
        if str(order_user_id) != str(ctx.userId):
            raise AdapterError("FORBIDDEN", "본인 주문만 조회할 수 있습니다.")


class AdapterRegistry:
    """
    site_id 기반으로 적절한 어댑터를 동적으로 할당하고 제공하는 레지스트리
    """

    _adapters: Dict[str, BaseEcommerceSupportAdapter] = {}

    @classmethod
    def register(cls, adapter: BaseEcommerceSupportAdapter) -> None:
        cls._adapters[adapter.site_id] = adapter

    @classmethod
    def register_many(cls, adapters: List[BaseEcommerceSupportAdapter]) -> None:
        for adapter in adapters:
            cls.register(adapter)

    @classmethod
    def get(cls, site_id: str) -> BaseEcommerceSupportAdapter:
        adapter = cls._adapters.get(site_id)
        if not adapter:
            raise AdapterError(
                "NOT_FOUND", f"site_id={site_id} 에 대한 adapter를 찾을 수 없습니다."
            )
        return adapter

    @classmethod
    def list_site_ids(cls) -> List[str]:
        return list(cls._adapters.keys())
