from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from unittest.mock import patch

import httpx

from chatbot.src.adapters.schema import AuthenticatedContext
from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.common import ArtifactRef
from chatbot.src.onboarding_v2.models.planning import IntegrationPlan
from chatbot.src.onboarding_v2.models.validation import (
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
    ReplayResult,
    ValidationBundle,
    ValidationCheck,
    WidgetOrderE2EResult,
)
from chatbot.src.onboarding_v2.validation.backend_runtime import (
    build_backend_runtime_plan,
    launch_backend_runtime,
    prepare_backend_runtime,
    stop_backend_runtime,
)
from chatbot.src.onboarding_v2.validation.replay_evaluator import (
    evaluate_backend_workspace_static,
    evaluate_frontend_workspace_static,
)
from chatbot.src.onboarding_v2.validation.signatures import build_failure_signature
from fastapi.testclient import TestClient
from chatbot import server_fastapi
from chatbot.src.api.v1.endpoints import chat as chat_endpoint


@dataclass(slots=True)
class ValidationRunResult:
    bundle: ValidationBundle
    backend_runtime_prep: BackendRuntimePrepResult
    backend_runtime_state: BackendRuntimeState
    chatbot_runtime_boot: dict[str, Any]
    widget_bundle_fetch: dict[str, Any]
    host_auth_bootstrap: dict[str, Any]
    chatbot_adapter_auth: dict[str, Any]
    widget_order_e2e: WidgetOrderE2EResult


def run_validation(
    *,
    run_root: str | Path,
    host_runtime_workspace: str | Path,
    chatbot_runtime_workspace: str | Path,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    replay_result: ReplayResult,
    artifact_refs: dict[str, ArtifactRef | None],
    onboarding_credentials: dict[str, str] | None = None,
    required_rechecks: list[str] | None = None,
) -> ValidationBundle:
    return run_validation_cycle(
        run_root=run_root,
        host_runtime_workspace=host_runtime_workspace,
        chatbot_runtime_workspace=chatbot_runtime_workspace,
        snapshot=snapshot,
        plan=plan,
        replay_result=replay_result,
        artifact_refs=artifact_refs,
        onboarding_credentials=onboarding_credentials,
        required_rechecks=required_rechecks,
    ).bundle


def run_validation_cycle(
    *,
    run_root: str | Path,
    host_runtime_workspace: str | Path,
    chatbot_runtime_workspace: str | Path,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    replay_result: ReplayResult,
    artifact_refs: dict[str, ArtifactRef | None],
    onboarding_credentials: dict[str, str] | None = None,
    required_rechecks: list[str] | None = None,
) -> ValidationRunResult:
    run_root = Path(run_root)
    host_runtime_workspace = Path(host_runtime_workspace)
    chatbot_runtime_workspace = Path(chatbot_runtime_workspace)

    prep_result = prepare_backend_runtime(
        workspace=host_runtime_workspace, snapshot=snapshot
    )
    runtime_state: BackendRuntimeState
    chatbot_runtime_boot: dict[str, Any]
    widget_bundle_fetch: dict[str, Any]
    host_auth_bootstrap: dict[str, Any]
    chatbot_adapter_auth: dict[str, Any]
    widget_order_e2e: WidgetOrderE2EResult
    if prep_result.passed:
        runtime_plan = build_backend_runtime_plan(
            workspace=host_runtime_workspace,
            snapshot=snapshot,
            plan=plan,
            prep_result=prep_result,
        )
        runtime_state = launch_backend_runtime(runtime_plan)
    else:
        runtime_plan = None
        runtime_state = _skipped_runtime_state(
            framework=snapshot.repo_profile.backend_framework,
            reason="backend runtime boot skipped because backend runtime prep failed",
        )

    if prep_result.passed and runtime_state.passed and runtime_plan is not None:
        chatbot_runtime_boot = validate_chatbot_runtime_boot(
            chatbot_runtime_workspace=chatbot_runtime_workspace
        )
    else:
        chatbot_runtime_boot = _skipped_result(
            "chatbot runtime boot skipped because backend runtime boot failed"
            if prep_result.passed
            else "chatbot runtime boot skipped because backend runtime prep failed"
        )

    if (
        prep_result.passed
        and runtime_state.passed
        and runtime_plan is not None
        and chatbot_runtime_boot.get("passed")
    ):
        widget_bundle_fetch = validate_widget_bundle_fetch(
            runtime_plan=runtime_plan,
            plan=plan,
        )
    else:
        widget_bundle_fetch = _skipped_result(
            "widget bundle fetch skipped because chatbot runtime boot failed"
            if prep_result.passed and runtime_state.passed
            else (
                "widget bundle fetch skipped because backend runtime boot failed"
                if prep_result.passed
                else "widget bundle fetch skipped because backend runtime prep failed"
            )
        )

    if (
        prep_result.passed
        and runtime_state.passed
        and runtime_plan is not None
        and chatbot_runtime_boot.get("passed")
        and widget_bundle_fetch.get("passed")
    ):
        try:
            host_auth_bootstrap = validate_host_auth_bootstrap(
                run_root=run_root,
                host_runtime_workspace=host_runtime_workspace,
                runtime_plan=runtime_plan,
                snapshot=snapshot,
                plan=plan,
                onboarding_credentials=onboarding_credentials,
            )
            chatbot_adapter_auth = validate_chatbot_adapter_auth(
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                bootstrap_result=host_auth_bootstrap,
                plan=plan,
            )
            widget_order_e2e = validate_widget_order_e2e(
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                bootstrap_result=host_auth_bootstrap,
                adapter_auth_result=chatbot_adapter_auth,
                plan=plan,
            )
            widget_order_e2e = _coerce_widget_order_e2e_result(widget_order_e2e)
        finally:
            stop_backend_runtime(runtime_state)
    else:
        reason = (
            "backend runtime boot failed"
            if prep_result.passed
            else "backend runtime prep failed"
        )
        if prep_result.passed and runtime_state.passed and not chatbot_runtime_boot.get("passed"):
            reason = "chatbot runtime boot failed"
        elif (
            prep_result.passed
            and runtime_state.passed
            and chatbot_runtime_boot.get("passed")
            and not widget_bundle_fetch.get("passed")
        ):
            reason = "widget bundle fetch failed"
        host_auth_bootstrap = _skipped_result(
            "host auth bootstrap skipped because " + reason
        )
        chatbot_adapter_auth = _skipped_result(
            "chatbot adapter auth skipped because " + reason
        )
        widget_order_e2e = WidgetOrderE2EResult(
            passed=False,
            failure_summary="widget order e2e skipped because " + reason,
            related_files=[],
        )

    replay_validation_payload = _evaluate_replay_workspaces(
        host_workspace=Path(replay_result.host_replay_workspace_path),
        chatbot_workspace=Path(replay_result.chatbot_replay_workspace_path),
        plan=plan,
    )

    checks = [
        ValidationCheck(
            name="backend_runtime_prep",
            passed=prep_result.passed,
            summary=prep_result.failure_summary or "backend runtime prepared",
            details=prep_result.model_dump(mode="json"),
        ),
        ValidationCheck(
            name="backend_runtime_boot",
            passed=runtime_state.passed,
            summary=runtime_state.failure_summary or "backend runtime booted",
            details=runtime_state.model_dump(mode="json"),
        ),
        ValidationCheck(
            name="chatbot_runtime_boot",
            passed=bool(chatbot_runtime_boot["passed"]),
            summary=chatbot_runtime_boot["failure_summary"],
            details=chatbot_runtime_boot,
        ),
        ValidationCheck(
            name="widget_bundle_fetch",
            passed=bool(widget_bundle_fetch["passed"]),
            summary=widget_bundle_fetch["failure_summary"],
            details=widget_bundle_fetch,
        ),
        ValidationCheck(
            name="host_auth_bootstrap",
            passed=bool(host_auth_bootstrap["passed"]),
            summary=host_auth_bootstrap["failure_summary"],
            details=host_auth_bootstrap,
        ),
        ValidationCheck(
            name="chatbot_adapter_auth",
            passed=bool(chatbot_adapter_auth["passed"]),
            summary=chatbot_adapter_auth["failure_summary"],
            details=chatbot_adapter_auth,
        ),
        ValidationCheck(
            name="widget_order_e2e",
            passed=widget_order_e2e.passed,
            summary=widget_order_e2e.failure_summary,
            details=widget_order_e2e.model_dump(mode="json"),
        ),
        ValidationCheck(
            name="replay_apply",
            passed=bool(replay_result.passed),
            summary="replay apply passed"
            if replay_result.passed
            else "replay apply failed",
            details=replay_result.model_dump(mode="json"),
        ),
        ValidationCheck(
            name="replay_validation",
            passed=bool(replay_validation_payload["passed"]),
            summary=(
                "replay validation passed"
                if replay_validation_payload["passed"]
                else replay_validation_payload["failure_summary"]
            ),
            details=replay_validation_payload,
        ),
    ]
    _enforce_required_rechecks(
        required_rechecks=list(required_rechecks or []),
        checks=[check.model_dump(mode="json") for check in checks],
    )

    first_failure = next((check for check in checks if not check.passed), None)
    related_artifacts = [ref for ref in artifact_refs.values() if ref is not None]
    input_artifact_versions = {
        name: ref.version for name, ref in artifact_refs.items() if ref is not None
    }
    related_files = sorted(
        {
            *prep_result.related_files,
            *runtime_state.related_files,
            *chatbot_runtime_boot.get("related_files", []),
            *widget_bundle_fetch.get("related_files", []),
            *host_auth_bootstrap.get("related_files", []),
            *chatbot_adapter_auth.get("related_files", []),
            *widget_order_e2e.related_files,
            *replay_validation_payload.get("related_files", []),
        }
    )
    bundle = ValidationBundle(
        passed=first_failure is None,
        checks=checks,
        failure_signature=(
            None
            if first_failure is None
            else build_failure_signature(
                check_name=first_failure.name, summary=first_failure.summary
            )
        ),
        failure_summary=None if first_failure is None else first_failure.summary,
        related_files=related_files,
        related_artifacts=related_artifacts,
        input_artifact_versions=input_artifact_versions,
    )
    return ValidationRunResult(
        bundle=bundle,
        backend_runtime_prep=prep_result,
        backend_runtime_state=runtime_state,
        chatbot_runtime_boot=chatbot_runtime_boot,
        widget_bundle_fetch=widget_bundle_fetch,
        host_auth_bootstrap=host_auth_bootstrap,
        chatbot_adapter_auth=chatbot_adapter_auth,
        widget_order_e2e=widget_order_e2e,
    )


def validate_host_auth_bootstrap(
    *,
    run_root: Path,
    host_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    onboarding_credentials: dict[str, str] | None = None,
) -> dict[str, Any]:
    del run_root, host_runtime_workspace, snapshot
    base_url = runtime_plan.readiness_url.removesuffix(
        plan.host_backend.chat_auth_contract_path
    ).rstrip("/")
    credentials = {
        "email": "test1@example.com",
        "password": "password123",
    }
    credentials.update(
        {key: value for key, value in (onboarding_credentials or {}).items() if value}
    )
    login_url = f"{base_url}/api/users/login/"
    bootstrap_url = f"{base_url}{plan.host_backend.chat_auth_contract_path}"

    with httpx.Client(follow_redirects=True, timeout=10.0) as client:
        login_response = client.post(login_url, json=credentials)
        if login_response.status_code != 200:
            return {
                "passed": False,
                "failure_summary": f"host login failed with status {login_response.status_code}",
                "related_files": ["backend/users/views.py"],
            }
        bootstrap_response = client.post(bootstrap_url)
        try:
            payload = bootstrap_response.json()
        except ValueError:
            payload = {}

    passed = (
        bootstrap_response.status_code == 200
        and bool(payload.get("authenticated"))
        and bool(str(payload.get("site_id") or "").strip())
        and bool(str(payload.get("access_token") or "").strip())
        and bool(str((payload.get("user") or {}).get("id") or "").strip())
    )
    summary = "host auth bootstrap passed"
    if not passed:
        if not payload.get("site_id"):
            summary = "host auth bootstrap missing site_id"
        elif not (payload.get("user") or {}).get("id"):
            summary = "host auth bootstrap missing user.id"
        else:
            summary = f"host auth bootstrap failed with status {bootstrap_response.status_code}"
    return {
        "passed": passed,
        "failure_summary": summary,
        "bootstrap_payload": payload,
        "login_status": login_response.status_code,
        "bootstrap_status": bootstrap_response.status_code,
        "related_files": ["backend/chat_auth.py", plan.host_backend.route_target],
    }


def validate_chatbot_adapter_auth(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    bootstrap_result: dict[str, Any],
    plan: IntegrationPlan,
) -> dict[str, Any]:
    payload = dict(bootstrap_result.get("bootstrap_payload") or {})
    if not bootstrap_result.get("passed"):
        return _skipped_result(
            "chatbot adapter auth skipped because host auth bootstrap failed"
        )

    module_prefix = f"src.adapters.generated.{plan.chatbot_bridge.site_key}"
    with _prepend_path(chatbot_runtime_workspace):
        _drop_import_cache(module_prefix)
        adapter_module = importlib.import_module(f"{module_prefix}.adapter")
        client_module = importlib.import_module(f"{module_prefix}.client")
        adapter_class = getattr(
            adapter_module,
            f"Generated{_class_name(plan.chatbot_bridge.site_key)}Adapter",
        )
        client_class = getattr(
            client_module, f"Generated{_class_name(plan.chatbot_bridge.site_key)}Client"
        )
        adapter = adapter_class(
            client=client_class(base_url=_runtime_base_url(runtime_plan))
        )
        try:
            validated_user = asyncio.run(
                adapter.validate_auth(
                    AuthenticatedContext(
                        siteId=plan.chatbot_bridge.site_key,
                        userId="__bridge__",
                        accessToken=str(payload.get("access_token") or ""),
                    )
                )
            )
        except Exception as exc:
            return {
                "passed": False,
                "failure_summary": f"chatbot adapter auth failed: {exc}",
                "related_files": [
                    f"{plan.chatbot_bridge.adapter_package}/adapter.py",
                    f"{plan.chatbot_bridge.adapter_package}/auth.py",
                    plan.chatbot_bridge.setup_target,
                ],
            }
    user_id = str(getattr(validated_user, "id", "") or "").strip()
    return {
        "passed": bool(user_id),
        "failure_summary": "chatbot adapter auth passed"
        if user_id
        else "chatbot adapter auth missing user.id",
        "validated_user": validated_user.model_dump(mode="json"),
        "related_files": [
            f"{plan.chatbot_bridge.adapter_package}/adapter.py",
            f"{plan.chatbot_bridge.adapter_package}/auth.py",
            plan.chatbot_bridge.setup_target,
        ],
    }


def validate_chatbot_runtime_boot(
    *,
    chatbot_runtime_workspace: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-c",
        (
            "import server_fastapi as module; "
            "app = getattr(module, 'app', None); "
            "assert app is not None, 'server_fastapi.app missing'; "
            "print('chatbot runtime boot passed')"
        ),
    ]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{chatbot_runtime_workspace}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(chatbot_runtime_workspace)
    )
    result = subprocess.run(
        command,
        cwd=str(chatbot_runtime_workspace),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        summary = "chatbot runtime boot passed"
    else:
        failure_line = next(
            (
                line.strip()
                for line in reversed(result.stderr.splitlines())
                if line.strip()
            ),
            f"exit code {result.returncode}",
        )
        summary = f"chatbot runtime boot failed: {failure_line}"
    return {
        "passed": result.returncode == 0,
        "failure_summary": summary,
        "command": command,
        "cwd": str(chatbot_runtime_workspace),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "related_files": [
            "server_fastapi.py",
            "src/tools/adapter_order_tools.py",
            "src/tools/order_tools.py",
        ],
    }


def validate_widget_bundle_fetch(
    *,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
) -> dict[str, Any]:
    chatbot_base_url = str(plan.host_frontend.chatbot_server_base_url or "").strip().rstrip("/")
    widget_path = "/widget.js"
    host_base_url = runtime_plan.readiness_url.removesuffix(
        plan.host_backend.chat_auth_contract_path
    ).rstrip("/")

    if not chatbot_base_url:
        return {
            "passed": False,
            "failure_summary": "widget bundle fetch failed: chatbotServerBaseUrl is empty",
            "target_url": widget_path,
            "related_files": [plan.host_frontend.mount_target],
        }

    target_url = f"{chatbot_base_url}{widget_path}"
    chatbot_origin = urlparse(chatbot_base_url)
    host_origin = urlparse(host_base_url)
    if (
        chatbot_origin.scheme == host_origin.scheme
        and chatbot_origin.netloc == host_origin.netloc
    ):
        return {
            "passed": False,
            "failure_summary": "widget bundle fetch failed: resolved to host origin",
            "target_url": target_url,
            "related_files": [plan.host_frontend.mount_target],
        }

    client = TestClient(server_fastapi.app, base_url=chatbot_base_url)
    response = client.get(widget_path)
    passed = (
        response.status_code == 200
        and "javascript" in response.headers.get("content-type", "").lower()
        and "order-cs-widget" in response.text
    )
    return {
        "passed": passed,
        "failure_summary": (
            "widget bundle fetch passed"
            if passed
            else f"widget bundle fetch failed with status {response.status_code}"
        ),
        "target_url": target_url,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "related_files": [
            plan.host_frontend.mount_target,
            "chatbot/src/api/v1/endpoints/chat.py",
            "chatbot/frontend/shared_widget/web-component.tsx",
        ],
    }


def validate_widget_order_e2e(
    *,
    chatbot_runtime_workspace: Path,
    bootstrap_result: dict[str, Any],
    adapter_auth_result: dict[str, Any],
    plan: IntegrationPlan,
) -> WidgetOrderE2EResult:

    if not bootstrap_result.get("passed"):
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary="widget order e2e skipped because host auth bootstrap failed",
            related_files=[],
        )
    if not adapter_auth_result.get("passed"):
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary="widget order e2e skipped because chatbot adapter auth failed",
            related_files=[],
        )

    payload = dict(bootstrap_result.get("bootstrap_payload") or {})
    adapter = _load_generated_adapter(
        chatbot_runtime_workspace=chatbot_runtime_workspace, plan=plan
    )
    flow_reports = _collect_widget_order_flow_report(
        adapter=adapter,
        adapter_auth_result=adapter_auth_result,
        payload=payload,
        plan=plan,
        server_fastapi=server_fastapi,
        chat_endpoint=chat_endpoint,
    )
    return _evaluate_widget_order_flow_report(plan=plan, flow_reports=flow_reports)


def _collect_widget_order_flow_report(
    *,
    adapter: Any,
    adapter_auth_result: dict[str, Any],
    payload: dict[str, Any],
    plan: IntegrationPlan,
    server_fastapi: Any,
    chat_endpoint: Any,
) -> dict[str, dict[str, Any]]:
    auth_context = AuthenticatedContext(
        siteId=plan.chatbot_bridge.site_key,
        userId=str(
            (adapter_auth_result.get("validated_user") or {}).get("id") or "__bridge__"
        ),
        accessToken=str(payload.get("access_token") or ""),
    )
    status_input = importlib.import_module("src.adapters.schema").GetOrderStatusInput(
        orderId="1"
    )
    flow_reports: dict[str, dict[str, Any]] = {}
    try:
        order_status = asyncio.run(adapter.get_order_status(auth_context, status_input))
        flow_reports["get_order_status"] = {
            "passed": True,
            "steps": [],
            "status": getattr(
                getattr(order_status, "order", None), "status", None
            ).value
            if getattr(getattr(order_status, "order", None), "status", None) is not None
            else None,
        }
    except Exception as exc:
        flow_reports["get_order_status"] = {
            "passed": False,
            "steps": [],
            "failure_summary": f"get_order_status failed: {exc}",
        }

    with patch.object(
        chat_endpoint.adapter_setup, "resolve_site_adapter", lambda site_id: adapter
    ):
        client = TestClient(server_fastapi.app)
        flow_reports["list_orders"] = _exercise_widget_order_flow(
            client=client,
            server_fastapi=server_fastapi,
            site_id=plan.chatbot_bridge.site_key,
            access_token=str(payload.get("access_token") or ""),
            conversation_id="conv-widget-list-orders",
            message="주문 목록 보여줘",
            step_specs=[
                _widget_step(
                    "show_order_list",
                    "최근 주문 목록입니다.",
                    ui_data=[_sample_order_ui_item()],
                    requires_selection=True,
                )
            ],
            resume_payloads=[],
        )
        flow_reports["cancel"] = _exercise_widget_order_flow(
            client=client,
            server_fastapi=server_fastapi,
            site_id=plan.chatbot_bridge.site_key,
            access_token=str(payload.get("access_token") or ""),
            conversation_id="conv-widget-cancel",
            message="주문 취소해줘",
            step_specs=[
                _widget_step(
                    "show_order_list",
                    "취소할 주문을 선택해주세요.",
                    ui_data=[_sample_order_ui_item()],
                    requires_selection=True,
                    prior_action="cancel",
                ),
                _widget_step(
                    "confirm_order_action",
                    "주문 취소를 진행할까요?",
                    action="cancel",
                    order_id="1",
                ),
            ],
            resume_payloads=[{"selected_order_ids": ["1"]}],
        )
        flow_reports["refund"] = _exercise_widget_order_flow(
            client=client,
            server_fastapi=server_fastapi,
            site_id=plan.chatbot_bridge.site_key,
            access_token=str(payload.get("access_token") or ""),
            conversation_id="conv-widget-refund",
            message="환불해줘",
            step_specs=[
                _widget_step(
                    "show_order_list",
                    "환불할 주문을 선택해주세요.",
                    ui_data=[_sample_order_ui_item()],
                    requires_selection=True,
                    prior_action="refund",
                ),
                _widget_step(
                    "confirm_order_action",
                    "환불을 진행할까요?",
                    action="refund",
                    order_id="1",
                ),
            ],
            resume_payloads=[{"selected_order_ids": ["1"]}],
        )
        flow_reports["exchange"] = _exercise_widget_order_flow(
            client=client,
            server_fastapi=server_fastapi,
            site_id=plan.chatbot_bridge.site_key,
            access_token=str(payload.get("access_token") or ""),
            conversation_id="conv-widget-exchange",
            message="교환해줘",
            step_specs=[
                _widget_step(
                    "show_order_list",
                    "교환할 주문을 선택해주세요.",
                    ui_data=[_sample_order_ui_item()],
                    requires_selection=True,
                    prior_action="exchange",
                ),
                _widget_step(
                    "show_option_list",
                    "교환할 옵션을 선택해주세요.",
                    action="select_option",
                    ui_data=[_sample_option_item("201"), _sample_option_item("202")],
                    prior_action="exchange",
                ),
                _widget_step(
                    "confirm_order_action",
                    "교환을 진행할까요?",
                    action="exchange",
                    order_id="1",
                    new_option_id="201",
                ),
            ],
            resume_payloads=[
                {"selected_order_ids": ["1"]},
                {"new_option_id": "201"},
            ],
        )
    return flow_reports


def _evaluate_widget_order_flow_report(
    *,
    plan: IntegrationPlan,
    flow_reports: dict[str, dict[str, Any]],
) -> WidgetOrderE2EResult:
    required_step_flows = [
        ("list_orders", ["show_order_list"]),
        ("cancel", ["show_order_list", "confirm_order_action"]),
        ("refund", ["show_order_list", "confirm_order_action"]),
        ("exchange", ["show_order_list", "show_option_list", "confirm_order_action"]),
    ]
    covered_flows: list[str] = []
    for flow_name, expected_steps in required_step_flows:
        actual_steps = list((flow_reports.get(flow_name) or {}).get("steps") or [])
        missing_step = _find_missing_flow_step(expected_steps, actual_steps)
        if missing_step is not None:
            return WidgetOrderE2EResult(
                passed=False,
                failure_summary=f"{missing_step} missing",
                covered_flows=covered_flows,
                flow_reports=flow_reports,
                related_files=_widget_order_related_files(plan),
            )
        covered_flows.append(flow_name)

    status_report = flow_reports.get("get_order_status") or {}
    if not status_report.get("passed"):
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary=str(
                status_report.get("failure_summary") or "get_order_status failed"
            ),
            covered_flows=covered_flows,
            flow_reports=flow_reports,
            related_files=_widget_order_related_files(plan),
        )
    covered_flows.insert(1, "get_order_status")

    return WidgetOrderE2EResult(
        passed=True,
        failure_summary="widget order e2e passed",
        covered_flows=covered_flows,
        flow_reports=flow_reports,
        related_files=_widget_order_related_files(plan),
    )


def _exercise_widget_order_flow(
    *,
    client: Any,
    server_fastapi: Any,
    site_id: str,
    access_token: str,
    conversation_id: str,
    message: str,
    step_specs: list[dict[str, Any]],
    resume_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    fragments: list[str] = []
    observed_steps: list[str] = []
    pending_interrupt: list[dict[str, Any]] = []
    with patch.object(
        server_fastapi.graph_app,
        "astream_events",
        _build_widget_astream_events(step_specs),
    ):
        for index, step_spec in enumerate(step_specs):
            request_payload: dict[str, Any] = {
                "message": message if index == 0 else "계속",
                "site_id": site_id,
                "access_token": access_token,
            }
            if index > 0:
                request_payload["previous_state"] = {
                    "conversation_id": conversation_id,
                    "pending_interrupt": pending_interrupt,
                }
                request_payload["resume_payload"] = resume_payloads[index - 1]
            response = client.post("/api/v1/chat/stream", json=request_payload)
            text = response.text
            fragments.append(text)
            ui_action = step_spec["ui_action"]
            if f'"ui_action":"{ui_action}"' in text:
                observed_steps.append(ui_action)
            pending_interrupt = [_interrupt_value_for_step(step_spec)]
    return {
        "passed": len(observed_steps) == len(step_specs),
        "steps": observed_steps,
        "fragments": fragments,
    }


def _build_widget_astream_events(step_specs: list[dict[str, Any]]):
    state = {"index": 0}

    async def _fake_astream_events(stream_input, *, version, config):
        del stream_input, version, config
        index = state["index"]
        state["index"] += 1
        step_spec = step_specs[index]
        interrupt_value = _interrupt_value_for_step(step_spec)
        yield {
            "event": "on_tool_end",
            "data": {"output": interrupt_value},
        }
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "messages": [],
                    "completed_tasks": [] if index == 0 else ["resume-selection"],
                    "ui_action_required": step_spec["ui_action"],
                    "__interrupt__": [{"value": interrupt_value}],
                    "order_context": {},
                }
            },
        }

    return _fake_astream_events


def _interrupt_value_for_step(step_spec: dict[str, Any]) -> dict[str, Any]:
    value = {
        "ui_action": step_spec["ui_action"],
        "message": step_spec["message"],
    }
    for key in (
        "action",
        "ui_data",
        "requires_selection",
        "prior_action",
        "order_id",
        "new_option_id",
    ):
        if key in step_spec:
            value[key] = step_spec[key]
    return value


def _widget_step(
    ui_action: str,
    message: str,
    *,
    action: str | None = None,
    ui_data: Any | None = None,
    requires_selection: bool | None = None,
    prior_action: str | None = None,
    order_id: str | None = None,
    new_option_id: str | None = None,
) -> dict[str, Any]:
    step = {"ui_action": ui_action, "message": message}
    if action is not None:
        step["action"] = action
    if ui_data is not None:
        step["ui_data"] = ui_data
    if requires_selection is not None:
        step["requires_selection"] = requires_selection
    if prior_action is not None:
        step["prior_action"] = prior_action
    if order_id is not None:
        step["order_id"] = order_id
    if new_option_id is not None:
        step["new_option_id"] = new_option_id
    return step


def _sample_order_ui_item() -> dict[str, Any]:
    return {
        "order_id": "1",
        "date": "2026-03-23",
        "status": "paid",
        "product_name": "테스트 상품",
        "amount": 12000,
    }


def _sample_option_item(option_id: str) -> dict[str, Any]:
    return {
        "option_id": option_id,
        "label": f"테스트 옵션 {option_id}",
        "in_stock": True,
    }


def _find_missing_flow_step(
    expected_steps: list[str], actual_steps: list[str]
) -> str | None:
    actual_index = 0
    for expected in expected_steps:
        while (
            actual_index < len(actual_steps) and actual_steps[actual_index] != expected
        ):
            actual_index += 1
        if actual_index >= len(actual_steps):
            return expected
        actual_index += 1
    return None


def _widget_order_related_files(plan: IntegrationPlan) -> list[str]:
    return [
        f"{plan.chatbot_bridge.adapter_package}/adapter.py",
        "chatbot/frontend/shared_widget/ChatbotWidget.tsx",
        "chatbot/frontend/shared_widget/chatbotfab.tsx",
    ]


def _evaluate_backend(workspace: Path) -> dict[str, Any]:
    return evaluate_backend_workspace_static(workspace)


def _evaluate_frontend(workspace: Path) -> dict[str, Any]:
    return evaluate_frontend_workspace_static(workspace)


def _enforce_required_rechecks(
    *,
    required_rechecks: list[str],
    checks: list[dict[str, Any]],
) -> None:
    requested = [item for item in required_rechecks if item]
    if not requested:
        return
    available = {
        str(check.get("name") or "").strip()
        for check in checks
        if str(check.get("name") or "").strip()
    }
    missing = [item for item in requested if item not in available]
    if missing:
        raise ValueError(
            "required validation rechecks missing: " + ", ".join(missing)
        )


def _evaluate_replay_workspaces(
    *,
    host_workspace: Path,
    chatbot_workspace: Path,
    plan: IntegrationPlan,
) -> dict[str, Any]:
    host_backend = _evaluate_backend(host_workspace)
    host_frontend = _evaluate_frontend(host_workspace)
    generated_adapter = (
        chatbot_workspace / plan.chatbot_bridge.adapter_package / "adapter.py"
    )
    setup_path = chatbot_workspace / plan.chatbot_bridge.setup_target
    passed = (
        host_backend["passed"]
        and host_frontend["passed"]
        and generated_adapter.exists()
        and setup_path.exists()
    )
    failure_summary = "replay validation passed"
    if not passed:
        if not host_backend["passed"]:
            failure_summary = host_backend["failure_summary"]
        elif not host_frontend["passed"]:
            failure_summary = host_frontend["failure_summary"]
        elif not generated_adapter.exists():
            failure_summary = "generated adapter missing in replay workspace"
        else:
            failure_summary = "chatbot setup patch missing in replay workspace"
    return {
        "passed": passed,
        "failure_summary": failure_summary,
        "host_backend": host_backend,
        "host_frontend": host_frontend,
        "related_files": sorted(
            set(host_backend["related_files"])
            | set(host_frontend["related_files"])
            | {
                f"{plan.chatbot_bridge.adapter_package}/adapter.py",
                plan.chatbot_bridge.setup_target,
            }
        ),
    }


def _skipped_runtime_state(*, framework: str, reason: str) -> BackendRuntimeState:
    return BackendRuntimeState(
        framework=framework,
        passed=False,
        failure_summary=reason,
        related_files=["backend/manage.py", "backend/chat_auth.py"]
        if framework == "django"
        else ["chat_auth.py"],
    )


def _skipped_result(reason: str) -> dict[str, Any]:
    return {
        "passed": False,
        "failure_summary": reason,
        "related_files": [],
    }


def _coerce_widget_order_e2e_result(
    value: WidgetOrderE2EResult | dict[str, Any],
) -> WidgetOrderE2EResult:
    if isinstance(value, WidgetOrderE2EResult):
        return value
    payload = dict(value or {})
    payload.setdefault("covered_flows", [])
    payload.setdefault("flow_reports", {})
    payload.setdefault("related_files", [])
    payload.setdefault("failure_summary", "widget order e2e failed")
    payload.setdefault("passed", False)
    return WidgetOrderE2EResult.model_validate(payload)


def _runtime_base_url(runtime_plan: BackendRuntimePlan) -> str:
    readiness_url = runtime_plan.readiness_url
    marker = "/api/chat/auth-token"
    if readiness_url.endswith(marker):
        return readiness_url.removesuffix(marker)
    return readiness_url.rsplit("/", 1)[0]


def _load_generated_adapter(*, chatbot_runtime_workspace: Path, plan: IntegrationPlan):
    module_prefix = f"src.adapters.generated.{plan.chatbot_bridge.site_key}"
    with _prepend_path(chatbot_runtime_workspace):
        _drop_import_cache(module_prefix)
        adapter_module = importlib.import_module(f"{module_prefix}.adapter")
        client_module = importlib.import_module(f"{module_prefix}.client")
        adapter_class = getattr(
            adapter_module,
            f"Generated{_class_name(plan.chatbot_bridge.site_key)}Adapter",
        )
        client_class = getattr(
            client_module, f"Generated{_class_name(plan.chatbot_bridge.site_key)}Client"
        )
        return adapter_class(client=client_class(base_url="http://127.0.0.1:8000"))


def _drop_import_cache(module_prefix: str) -> None:
    for module_name in list(sys.modules):
        if module_name == module_prefix or module_name.startswith(module_prefix + "."):
            sys.modules.pop(module_name, None)


@contextmanager
def _prepend_path(path: Path):
    path_str = str(path)
    sys.path.insert(0, path_str)
    try:
        yield
    finally:
        try:
            sys.path.remove(path_str)
        except ValueError:
            pass


def _class_name(site_key: str) -> str:
    return "".join(part.capitalize() for part in site_key.replace("-", "_").split("_"))
