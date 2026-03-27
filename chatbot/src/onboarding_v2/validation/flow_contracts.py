from __future__ import annotations

from typing import Any

from chatbot.src.onboarding_v2.models.planning import IntegrationPlan
from chatbot.src.onboarding_v2.models.validation import (
    ConversationScenarioContract,
    OrderActionCapability,
    ValidationCapabilityContract,
)


def build_validation_capability_contract(
    *,
    plan: IntegrationPlan,
    fixture_manifest: dict[str, Any] | None = None,
    sample_context: dict[str, Any] | None = None,
    widget_order_e2e_result: Any | None = None,
) -> ValidationCapabilityContract:
    fixture_manifest = dict(fixture_manifest or {})
    sample_context = dict(sample_context or {})
    if widget_order_e2e_result is not None:
        raw_contract = dict(
            getattr(widget_order_e2e_result, "validation_capability_contract", {}) or {}
        )
        if raw_contract:
            return ValidationCapabilityContract.model_validate(raw_contract)
    raw_contract = dict(fixture_manifest.get("validation_capability_contract") or {})
    if raw_contract:
        return ValidationCapabilityContract.model_validate(raw_contract)

    order_action_contract = plan.chatbot_bridge.order_action_contract
    available_actions = [
        str(action).strip()
        for action in list(order_action_contract.supported_actions or [])
        if str(action).strip()
    ]
    widget_features = dict(fixture_manifest.get("widget_features") or {})
    enabled_retrieval_corpora = list(fixture_manifest.get("enabled_retrieval_corpora") or [])
    requires_order_selection = any(
        action in available_actions for action in ("cancel", "refund", "exchange")
    )
    requires_option_selection = "exchange" in available_actions

    action_capabilities: dict[str, OrderActionCapability] = {}
    for action in available_actions:
        action_capabilities[action] = OrderActionCapability(
            requires_order_selection=action in {"cancel", "refund", "exchange"}
            and requires_order_selection,
            requires_option_selection=action == "exchange"
            and requires_option_selection,
            allows_direct_execution=action
            in {"get_order_status", "cancel", "refund", "exchange", "list_orders"},
        )

    return ValidationCapabilityContract(
        supports_authenticated_chat=True,
        supports_widget_order_flow=True,
        supports_direct_order_lookup="get_order_status" in available_actions,
        supports_mutations=(
            order_action_contract.submission_mode != "read_only"
            and any(
                action in available_actions
                for action in ("cancel", "refund", "exchange")
            )
        ),
        supports_retrieval=bool(enabled_retrieval_corpora),
        supports_image_upload=bool(widget_features.get("image_upload")),
        requires_order_selection_for_actions=requires_order_selection,
        requires_option_selection_for_exchange=requires_option_selection,
        available_actions=available_actions,
        action_capabilities=action_capabilities,
    )


def build_conversation_scenarios(
    *,
    fixture_manifest: dict[str, Any],
    capability_contract: ValidationCapabilityContract | None = None,
) -> list[dict[str, Any]]:
    fixture_manifest = dict(fixture_manifest or {})
    capability_contract = capability_contract or _contract_from_manifest(
        fixture_manifest
    )
    orders = dict(fixture_manifest.get("orders") or {})
    lookup_order_id = str(orders.get("lookup_order_id") or "")
    status_order_id = str(orders.get("status_order_id") or lookup_order_id)
    cancel_order_id = str(orders.get("cancel_order_id") or lookup_order_id)
    refund_order_id = str(orders.get("refund_order_id") or lookup_order_id)
    exchange_order_id = str(orders.get("exchange_order_id") or lookup_order_id)
    exchange_new_option_id = str(
        orders.get("exchange_new_option_id") or "synthetic-option-1"
    )

    scenarios = [
        ConversationScenarioContract(
            scenario_id="unauthenticated_chat_request",
            mode="auth",
            prompt="주문 목록 보여줘",
        ),
        ConversationScenarioContract(
            scenario_id="authenticated_list_orders",
            mode="read_only",
            prompt="내 주문 목록 보여줘",
            expected_milestones=["list_orders", "show_order_list"],
            allowed_paths=[["list_orders"], ["show_order_list"]],
            sampled_order_id=lookup_order_id or None,
        ),
        ConversationScenarioContract(
            scenario_id="same_session_followup_order_status",
            mode="read_only",
            prompt="그 주문 상태 알려줘",
            expected_milestones=["get_order_status", "list_orders", "show_order_list"],
            allowed_paths=_status_lookup_paths(capability_contract),
            sampled_order_id=status_order_id or None,
            previous_state_from="authenticated_list_orders",
        ),
        ConversationScenarioContract(
            scenario_id="cancel_order",
            mode="mutating",
            prompt=f"주문 {cancel_order_id} 취소해줘",
            expected_milestones=_expected_milestones_for_action(
                action="cancel",
                capability_contract=capability_contract,
            ),
            allowed_paths=_action_allowed_paths(
                action="cancel",
                capability_contract=capability_contract,
            ),
            sampled_order_id=cancel_order_id or None,
        ),
        ConversationScenarioContract(
            scenario_id="refund_order",
            mode="mutating",
            prompt=f"주문 {refund_order_id} 환불해줘",
            expected_milestones=_expected_milestones_for_action(
                action="refund",
                capability_contract=capability_contract,
            ),
            allowed_paths=_action_allowed_paths(
                action="refund",
                capability_contract=capability_contract,
            ),
            sampled_order_id=refund_order_id or None,
        ),
        ConversationScenarioContract(
            scenario_id="exchange_order",
            mode="mutating",
            prompt=f"주문 {exchange_order_id} 옵션을 {exchange_new_option_id}로 교환해줘",
            expected_milestones=_expected_milestones_for_action(
                action="exchange",
                capability_contract=capability_contract,
            ),
            allowed_paths=_action_allowed_paths(
                action="exchange",
                capability_contract=capability_contract,
            ),
            sampled_order_id=exchange_order_id or None,
            sampled_option_id=exchange_new_option_id or None,
        ),
        ConversationScenarioContract(
            scenario_id="session_continuity",
            mode="read_only",
            prompt="방금 조회한 주문 다시 이어서 설명해줘",
            sampled_order_id=status_order_id or None,
            previous_state_from="authenticated_list_orders",
        ),
        ConversationScenarioContract(
            scenario_id="out_of_scope_discovery_rejected",
            mode="policy",
            prompt="가방 추천해줘",
        ),
        ConversationScenarioContract(
            scenario_id="review_writing_rejected",
            mode="policy",
            prompt="리뷰 작성 도와줘",
        ),
        ConversationScenarioContract(
            scenario_id="ambiguous_order_question",
            mode="policy",
            prompt="주문 관련해서 도와줘",
        ),
    ]
    return [_scenario_payload(item) for item in scenarios]


def _status_lookup_paths(
    capability_contract: ValidationCapabilityContract,
) -> list[list[str]]:
    paths: list[list[str]] = []
    if capability_contract.supports_direct_order_lookup:
        paths.append(["get_order_status"])
    if "list_orders" in capability_contract.available_actions:
        paths.append(["list_orders"])
        paths.append(["show_order_list"])
    return paths or [["get_order_status"]]


def _action_allowed_paths(
    *,
    action: str,
    capability_contract: ValidationCapabilityContract,
) -> list[list[str]]:
    capability = capability_contract.action_capabilities.get(
        action, OrderActionCapability()
    )
    paths: list[list[str]] = []
    if capability.allows_direct_execution:
        paths.append([action])
    selection_path: list[str] = []
    if capability.requires_order_selection:
        selection_path.append("show_order_list")
    if capability.requires_option_selection:
        selection_path.append("show_option_list")
    if capability.requires_order_selection or capability.requires_option_selection:
        selection_path.append("confirm_order_action")
    if selection_path:
        paths.append(selection_path)
    return paths or [[action]]


def _expected_milestones_for_action(
    *,
    action: str,
    capability_contract: ValidationCapabilityContract,
) -> list[str]:
    milestones = _ordered_unique(
        _action_allowed_paths(action=action, capability_contract=capability_contract)
    )
    if action not in milestones:
        milestones.append(action)
    return milestones


def _ordered_unique(paths: list[list[str]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for step in path:
            if step in seen:
                continue
            seen.add(step)
            ordered.append(step)
    return ordered


def _contract_from_manifest(
    fixture_manifest: dict[str, Any],
) -> ValidationCapabilityContract:
    raw_contract = dict(fixture_manifest.get("validation_capability_contract") or {})
    if raw_contract:
        return ValidationCapabilityContract.model_validate(raw_contract)
    return ValidationCapabilityContract()


def _scenario_payload(contract: ConversationScenarioContract) -> dict[str, Any]:
    scenario_contract_payload = contract.model_dump(mode="json")
    payload = dict(scenario_contract_payload)
    payload["scenario_contract"] = dict(scenario_contract_payload)
    payload["expected_tool_names"] = _scenario_expected_tool_names(contract)
    return payload


def _scenario_expected_tool_names(
    contract: ConversationScenarioContract,
) -> list[str]:
    direct_tools = [
        step
        for path in contract.allowed_paths
        for step in path
        if step in {"list_orders", "get_order_status", "cancel", "refund", "exchange"}
    ]
    ordered: list[str] = []
    for tool_name in direct_tools:
        if tool_name not in ordered:
            ordered.append(tool_name)
    return ordered
