from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from chatbot.src.onboarding_v2.models.planning import ResolvedOrderActionContract

from .schema import AdapterError, SubmitOrderActionInput, SubmitOrderActionResult
from .site_a.mappers import map_site_a_order_action
from .site_c.mappers import map_site_c_order_action


@dataclass(frozen=True)
class OrderActionRequestSpec:
    method: str
    path: str
    params: dict[str, Any] | None = None
    json: dict[str, Any] | None = None


def build_order_action_request_from_contract(
    contract: ResolvedOrderActionContract,
    input_data: SubmitOrderActionInput,
    *,
    default_endpoint: str,
    order_action_endpoints: dict[str, str],
    format_path: Callable[..., str],
) -> OrderActionRequestSpec:
    if contract.submission_mode == "read_only":
        raise AdapterError("NOT_SUPPORTED", "주문 액션 API를 제공하지 않습니다.")

    endpoint = order_action_endpoints.get(input_data.actionType.value) or default_endpoint
    if not endpoint:
        raise ValueError("order action endpoint is required")

    request_fields = contract.request_fields
    path = format_path(endpoint, order_id=input_data.orderId)
    if contract.submission_mode == "per_action_query_endpoint":
        params: dict[str, Any] = {}
        if contract.reason_transport == "query_param" and input_data.reasonText:
            params[request_fields.reason] = input_data.reasonText
        if (
            contract.new_option_transport == "query_param"
            and input_data.newOptionId
        ):
            params[request_fields.new_option_id] = input_data.newOptionId
        return OrderActionRequestSpec(method="POST", path=path, params=params or None)

    payload: dict[str, Any] = {
        request_fields.action: input_data.actionType.value,
    }
    if contract.reason_transport == "json_body" and input_data.reasonText:
        payload[request_fields.reason] = input_data.reasonText
    if contract.new_option_transport == "json_body" and input_data.newOptionId:
        payload[request_fields.new_option_id] = input_data.newOptionId
    return OrderActionRequestSpec(method="POST", path=path, json=payload)


def map_order_action_result_from_contract(
    contract: ResolvedOrderActionContract,
    raw: Any,
) -> SubmitOrderActionResult:
    if contract.result_profile == "requested_message":
        return map_site_c_order_action(raw)
    if contract.result_profile == "not_supported":
        return SubmitOrderActionResult(
            success=False,
            status="not_allowed",
            message="주문 액션 API를 제공하지 않습니다.",
        )
    return map_site_a_order_action(raw)
