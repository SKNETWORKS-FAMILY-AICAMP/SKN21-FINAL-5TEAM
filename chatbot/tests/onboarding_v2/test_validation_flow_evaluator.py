from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.models.planning import (
    ChatbotBridgePlan,
    HostBackendPlan,
    HostFrontendPlan,
    IntegrationPlan,
    ResolvedAuthContract,
    ResolvedOrderActionContract,
)
from chatbot.src.onboarding_v2.models.validation import ConversationScenarioContract


def _build_bilyeo_plan() -> IntegrationPlan:
    return IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="flask_blueprint_register",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="bilyeo",
            supported_order_tools=["list_orders", "get_order_status", "cancel", "refund", "exchange"],
            widget_features={"image_upload": True},
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="vite_mount",
            mount_target="frontend/src/App.vue",
            api_strategy="axios",
            api_client_target="frontend/src/api.ts",
            chatbot_server_base_url="http://localhost:8100",
            enabled_retrieval_corpora=["faq", "policy"],
            widget_features={"image_upload": True},
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="bilyeo",
            adapter_package="src/adapters/generated/bilyeo",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="GENERATED_BILYEO_API_URL",
            auth_validation_endpoint="/api/chat/auth-token",
            current_user_endpoint="/api/chat/auth-token",
            product_search_endpoint="/api/products",
            order_list_endpoint="/api/orders",
            order_detail_endpoint="/api/orders/{order_id}",
            order_action_endpoint="/api/orders/{order_id}/actions",
            auth_contract=ResolvedAuthContract(transport="bearer_token"),
            supported_tools=["list_orders", "get_order_status", "cancel", "refund", "exchange"],
        ),
    )


def test_validation_capability_contract_tracks_retrieval_and_image_upload():
    from chatbot.src.onboarding_v2.validation.flow_contracts import (
        build_validation_capability_contract,
    )

    contract = build_validation_capability_contract(
        plan=_build_bilyeo_plan(),
        fixture_manifest={
            "enabled_retrieval_corpora": ["faq", "policy"],
            "widget_features": {"image_upload": True},
        },
        sample_context={"sampled_option_id": "option-7"},
    )

    assert contract.supports_retrieval is True
    assert contract.supports_image_upload is True
    assert contract.requires_order_selection_for_actions is True
    assert contract.requires_option_selection_for_exchange is True


def test_validation_capability_contract_prefers_nested_action_contract_over_legacy_supported_tools():
    from chatbot.src.onboarding_v2.validation.flow_contracts import (
        build_validation_capability_contract,
    )

    plan = _build_bilyeo_plan().model_copy(
        update={
            "chatbot_bridge": _build_bilyeo_plan().chatbot_bridge.model_copy(
                update={
                    "order_action_contract": ResolvedOrderActionContract(
                        submission_mode="read_only",
                        supported_actions=["list_orders", "get_order_status"],
                    ),
                    "supported_tools": [
                        "list_orders",
                        "get_order_status",
                        "cancel",
                        "refund",
                        "exchange",
                    ],
                }
            )
        }
    )

    contract = build_validation_capability_contract(
        plan=plan,
        fixture_manifest={},
    )

    assert contract.available_actions == ["list_orders", "get_order_status"]
    assert contract.supports_mutations is False


def test_conversation_scenario_builder_allows_selection_first_bilyeo_paths():
    from chatbot.src.onboarding_v2.validation.flow_contracts import (
        build_conversation_scenarios,
        build_validation_capability_contract,
    )

    fixture_manifest = {
        "orders": {
            "lookup_order_id": "7",
            "status_order_id": "7",
            "cancel_order_id": "7",
            "refund_order_id": "7",
            "exchange_order_id": "7",
            "exchange_new_option_id": "option-7",
        }
    }
    contract = build_validation_capability_contract(
        plan=_build_bilyeo_plan(),
        fixture_manifest=fixture_manifest,
        sample_context={"sampled_option_id": "option-7"},
    )

    scenarios = build_conversation_scenarios(
        fixture_manifest=fixture_manifest,
        capability_contract=contract,
    )

    cancel_scenario = next(item for item in scenarios if item["scenario_id"] == "cancel_order")
    followup_scenario = next(
        item for item in scenarios if item["scenario_id"] == "same_session_followup_order_status"
    )

    assert ["show_order_list", "confirm_order_action"] in cancel_scenario["allowed_paths"]
    assert ["cancel"] in cancel_scenario["allowed_paths"]
    assert ["list_orders"] in followup_scenario["allowed_paths"]
    assert ["get_order_status"] in followup_scenario["allowed_paths"]


def test_conversation_scenario_builder_skips_mutation_scenarios_for_read_only_contract():
    from chatbot.src.onboarding_v2.validation.flow_contracts import (
        build_conversation_scenarios,
        build_validation_capability_contract,
    )

    fixture_manifest = {
        "orders": {
            "lookup_order_id": "7",
            "status_order_id": "7",
            "cancel_order_id": "7",
            "refund_order_id": "7",
            "exchange_order_id": "7",
            "exchange_new_option_id": "option-7",
        },
        "enabled_retrieval_corpora": ["faq", "policy"],
    }
    plan = _build_bilyeo_plan().model_copy(
        update={
            "chatbot_bridge": _build_bilyeo_plan().chatbot_bridge.model_copy(
                update={
                    "order_action_contract": ResolvedOrderActionContract(
                        submission_mode="read_only",
                        supported_actions=["list_orders", "get_order_status"],
                    )
                }
            )
        }
    )
    contract = build_validation_capability_contract(
        plan=plan,
        fixture_manifest=fixture_manifest,
    )

    scenarios = build_conversation_scenarios(
        fixture_manifest=fixture_manifest,
        capability_contract=contract,
    )

    scenario_ids = [item["scenario_id"] for item in scenarios]
    assert "cancel_order" not in scenario_ids
    assert "refund_order" not in scenario_ids
    assert "exchange_order" not in scenario_ids
    assert contract.available_actions == ["list_orders", "get_order_status"]
    assert contract.supports_retrieval is True


def test_conversation_scenario_builder_skips_mutation_scenarios_without_eligible_fixture_orders():
    from chatbot.src.onboarding_v2.validation.flow_contracts import (
        build_conversation_scenarios,
        build_validation_capability_contract,
    )

    fixture_manifest = {
        "orders": {
            "lookup_order_id": "7",
            "status_order_id": "7",
        }
    }
    contract = build_validation_capability_contract(
        plan=_build_bilyeo_plan(),
        fixture_manifest=fixture_manifest,
    )

    scenarios = build_conversation_scenarios(
        fixture_manifest=fixture_manifest,
        capability_contract=contract,
    )

    scenario_ids = [item["scenario_id"] for item in scenarios]
    assert "cancel_order" not in scenario_ids
    assert "refund_order" not in scenario_ids
    assert "exchange_order" not in scenario_ids


def test_conversation_scenario_builder_emits_valid_nested_contract_payload():
    from chatbot.src.onboarding_v2.validation.flow_contracts import (
        build_conversation_scenarios,
        build_validation_capability_contract,
    )

    fixture_manifest = {
        "orders": {
            "lookup_order_id": "7",
            "status_order_id": "7",
            "cancel_order_id": "7",
            "refund_order_id": "7",
            "exchange_order_id": "7",
            "exchange_new_option_id": "option-7",
        }
    }
    contract = build_validation_capability_contract(
        plan=_build_bilyeo_plan(),
        fixture_manifest=fixture_manifest,
        sample_context={"sampled_option_id": "option-7"},
    )

    scenarios = build_conversation_scenarios(
        fixture_manifest=fixture_manifest,
        capability_contract=contract,
    )

    authenticated_list_orders = next(
        item for item in scenarios if item["scenario_id"] == "authenticated_list_orders"
    )
    nested = ConversationScenarioContract.model_validate(
        authenticated_list_orders["scenario_contract"]
    )

    assert nested.scenario_id == "authenticated_list_orders"
    assert "expected_tool_names" not in authenticated_list_orders["scenario_contract"]


def test_flow_evaluator_accepts_selection_first_path_without_direct_mutation_tool():
    from chatbot.src.onboarding_v2.validation.flow_evaluator import (
        evaluate_conversation_deterministic_failures,
    )

    scenario_contract = ConversationScenarioContract(
        scenario_id="cancel_order",
        mode="mutating",
        prompt="주문 취소해줘",
        expected_milestones=["show_order_list", "confirm_order_action"],
        allowed_paths=[["show_order_list", "confirm_order_action"], ["cancel"]],
        sampled_order_id="7",
    )

    failures, observed_milestones = evaluate_conversation_deterministic_failures(
        scenario_contract=scenario_contract,
        response={
            "status_code": 200,
            "error_events": [],
            "metadata_state": {"order_context": {"last_tool": "get_user_orders"}},
            "final_answer": "",
            "ui_interrupts": [
                {"ui_action": "show_order_list", "ui_data": [{"order_id": "7"}]},
                {"ui_action": "confirm_order_action", "order_id": "7"},
            ],
        },
        observed_tool_names=["list_orders"],
    )

    assert failures == []
    assert observed_milestones == ["show_order_list", "confirm_order_action", "list_orders"]


def test_flow_evaluator_classifies_missing_option_selection_step():
    from chatbot.src.onboarding_v2.validation.flow_evaluator import (
        classify_conversation_failure,
        evaluate_conversation_deterministic_failures,
    )

    scenario_contract = ConversationScenarioContract(
        scenario_id="exchange_order",
        mode="mutating",
        prompt="교환해줘",
        expected_milestones=["show_order_list", "show_option_list", "confirm_order_action"],
        allowed_paths=[
            ["show_order_list", "show_option_list", "confirm_order_action"],
            ["exchange"],
        ],
        sampled_order_id="7",
        sampled_option_id="option-9",
    )

    failures, _ = evaluate_conversation_deterministic_failures(
        scenario_contract=scenario_contract,
        response={
            "status_code": 200,
            "error_events": [],
            "metadata_state": {"order_context": {"last_tool": "get_user_orders"}},
            "final_answer": "",
            "ui_interrupts": [
                {"ui_action": "show_order_list"},
                {"ui_action": "confirm_order_action"},
            ],
        },
        observed_tool_names=["list_orders"],
    )

    assert "missing_required_option_selection_step" in failures
    assert classify_conversation_failure(failures) == "missing_required_option_selection_step"
