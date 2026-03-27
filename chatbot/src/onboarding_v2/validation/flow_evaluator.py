from __future__ import annotations

import json
from typing import Any

from chatbot.src.onboarding_v2.models.validation import ConversationScenarioContract


def evaluate_conversation_deterministic_failures(
    *,
    scenario_contract: ConversationScenarioContract,
    response: dict[str, Any],
    observed_tool_names: list[str],
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    observed_milestones = collect_observed_milestones(
        response=response,
        observed_tool_names=observed_tool_names,
    )
    response_text = str(response.get("response_text") or "").strip().lower()
    if response["status_code"] != 200:
        if response["status_code"] == 401:
            if "adapter" in response_text and (
                "찾을 수 없습니다" in response_text or "not_found" in response_text
            ):
                failures.append("adapter_resolution_failed")
            else:
                failures.append("auth_gate_failed")
        else:
            failures.append("scenario_logic_failed")
        failures.append(f"unexpected status {response['status_code']}")
    if response.get("error_events"):
        failures.append("chat stream emitted error event")
    if not response.get("metadata_state"):
        failures.append("missing metadata state")
    if not response.get("final_answer") and not response.get("ui_interrupts"):
        failures.append("missing final answer or ui interrupt")
    if scenario_contract.allowed_paths and not _allowed_path_satisfied(
        scenario_contract.allowed_paths,
        observed_milestones,
    ):
        failures.extend(
            _classify_missing_path_failure(
                scenario_contract=scenario_contract,
                observed_milestones=observed_milestones,
            )
        )

    expected_order_id = _optional_text(scenario_contract.sampled_order_id)
    if expected_order_id and scenario_contract.mode in {"mutating", "read_only"}:
        serialized = json.dumps(response, ensure_ascii=False, default=str)
        if expected_order_id not in serialized:
            failures.append(f"missing expected order id {expected_order_id}")
    expected_option_id = _optional_text(scenario_contract.sampled_option_id)
    if expected_option_id:
        serialized = json.dumps(response, ensure_ascii=False, default=str)
        if expected_option_id not in serialized:
            failures.append(f"missing expected option id {expected_option_id}")
    return failures, observed_milestones


def classify_conversation_failure(deterministic_failures: list[str]) -> str | None:
    categories = (
        "auth_gate_failed",
        "adapter_resolution_failed",
        "missing_required_selection_step",
        "missing_required_option_selection_step",
        "missing_mutation_confirmation_step",
        "tool_expectation_failed",
        "scenario_logic_failed",
    )
    for category in categories:
        if category in deterministic_failures:
            return category
    if deterministic_failures:
        return "scenario_logic_failed"
    return None


def collect_observed_milestones(
    *,
    response: dict[str, Any],
    observed_tool_names: list[str],
) -> list[str]:
    observed: list[str] = []
    for interrupt in list(response.get("ui_interrupts") or []):
        ui_action = _optional_text(interrupt.get("ui_action"))
        if ui_action and ui_action not in observed:
            observed.append(ui_action)
    for tool_name in observed_tool_names:
        normalized_tool_name = _optional_text(tool_name)
        if normalized_tool_name and normalized_tool_name not in observed:
            observed.append(normalized_tool_name)
    return observed


def _allowed_path_satisfied(
    allowed_paths: list[list[str]],
    observed_milestones: list[str],
) -> bool:
    if not allowed_paths:
        return True
    for path in allowed_paths:
        if _path_is_subsequence(path, observed_milestones):
            return True
    return False


def _path_is_subsequence(path: list[str], observed_milestones: list[str]) -> bool:
    if not path:
        return True
    index = 0
    for milestone in observed_milestones:
        if milestone != path[index]:
            continue
        index += 1
        if index == len(path):
            return True
    return False


def _classify_missing_path_failure(
    *,
    scenario_contract: ConversationScenarioContract,
    observed_milestones: list[str],
) -> list[str]:
    allowed_paths = list(scenario_contract.allowed_paths or [])
    if any("show_option_list" in path for path in allowed_paths):
        if "show_order_list" in observed_milestones and "show_option_list" not in observed_milestones:
            return [
                "missing_required_option_selection_step",
                "missing required milestone show_option_list",
            ]
    if any("confirm_order_action" in path for path in allowed_paths):
        if any(step in observed_milestones for step in ("show_order_list", "show_option_list")) and "confirm_order_action" not in observed_milestones:
            return [
                "missing_mutation_confirmation_step",
                "missing required milestone confirm_order_action",
            ]
    if any("show_order_list" in path for path in allowed_paths):
        if "show_order_list" not in observed_milestones:
            return [
                "missing_required_selection_step",
                "missing required milestone show_order_list",
            ]
    return [
        "tool_expectation_failed",
        "no allowed milestone path satisfied",
    ]


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
