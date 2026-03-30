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
from uuid import uuid4

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel, ConfigDict, Field

from chatbot.src.adapters.schema import AuthenticatedContext
from chatbot.src.adapters.response_profiles import resolve_visible_order_id_from_contract
from chatbot.src.infrastructure.conversation_logger import ConversationRunLogger
from chatbot.src.onboarding_v2.llm_runtime import invoke_structured_stage
from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.common import ArtifactRef
from chatbot.src.onboarding_v2.models.planning import IntegrationPlan
from chatbot.src.onboarding_v2.models.validation import (
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
    ConversationScenarioContract,
    ConversationScenarioResult,
    ConversationValidationResult,
    ReplayResult,
    ValidationCapabilityContract,
    ValidationBundle,
    ValidationCheck,
    WidgetOrderE2EResult,
)
from chatbot.src.onboarding_v2.validation.backend_runtime import (
    build_backend_runtime_plan,
    build_backend_subprocess_env,
    launch_backend_runtime,
    prepare_backend_runtime,
    stop_backend_runtime,
    _run_optional_script,
)
from chatbot.src.onboarding_v2.validation.replay_evaluator import (
    evaluate_backend_workspace_static,
    evaluate_frontend_workspace_static,
)
from chatbot.src.onboarding_v2.validation.flow_contracts import (
    build_conversation_scenarios as _build_conversation_scenarios_from_contract,
    build_validation_capability_contract,
)
from chatbot.src.onboarding_v2.validation.flow_evaluator import (
    classify_conversation_failure as _classify_conversation_failure_from_contract,
    evaluate_conversation_deterministic_failures as _evaluate_conversation_deterministic_failures_from_contract,
)
from chatbot.src.onboarding_v2.validation.signatures import build_failure_signature
from fastapi.testclient import TestClient


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
    conversation_validation: ConversationValidationResult


@dataclass(slots=True)
class _ResolvedValidationPaths:
    run_root: Path
    host_runtime_workspace: Path
    chatbot_runtime_workspace: Path
    live_logs_root: Path | None


class _RuntimeValidationSubprocessError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_origin: str = "platform_validation",
        failure_code: str = "runtime_validation_subprocess_failed",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_origin = failure_origin
        self.failure_code = failure_code
        self.diagnostics = dict(diagnostics or {})


class _ConversationLlmJudgeResponse(BaseModel):
    task_completion: str = "unknown"
    factual_alignment: str = "unknown"
    safety: str = "unknown"
    unsupported_behavior: str = "unknown"
    overall_pass: bool = True
    rationale: str = ""

    model_config = ConfigDict(extra="forbid")


class _ConversationTraceCallbackHandler(BaseCallbackHandler):
    raise_error = False

    def __init__(self, logger: ConversationRunLogger) -> None:
        self._logger = logger
        self._chain_names: dict[str, str] = {}
        self._tool_names: dict[str, str] = {}
        self._model_names: dict[str, str] = {}

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        del parent_run_id, tags, metadata, kwargs
        name = _callback_name(serialized, fallback="chain")
        self._chain_names[str(run_id)] = name
        self._logger.log_node_start(name, inputs)

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        del parent_run_id, kwargs
        name = self._chain_names.pop(str(run_id), "chain")
        self._logger.log_node_end(name, outputs)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, inputs=None, **kwargs):
        del parent_run_id, tags, metadata, kwargs
        name = _callback_name(serialized, fallback="tool")
        self._tool_names[str(run_id)] = name
        self._logger.log_tool_start(
            name,
            inputs if inputs is not None else input_str,
        )

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        del parent_run_id, kwargs
        name = self._tool_names.pop(str(run_id), "tool")
        self._logger.log_tool_end(name, output)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        del parent_run_id, tags, metadata, kwargs
        name = _callback_name(serialized, fallback="chat_model")
        self._model_names[str(run_id)] = name
        self._logger.log_model_start(name, messages)

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        del parent_run_id, kwargs
        name = self._model_names.pop(str(run_id), "chat_model")
        self._logger.log_model_end(name, response)


def _register_validation_runner_aliases() -> None:
    current_module = sys.modules.get(__name__)
    if current_module is None:
        return
    for alias in (
        "chatbot.src.onboarding_v2.validation.runner",
        "src.onboarding_v2.validation.runner",
    ):
        sys.modules[alias] = current_module
    for package_name in (
        "chatbot.src.onboarding_v2.validation",
        "src.onboarding_v2.validation",
    ):
        package = sys.modules.get(package_name)
        if package is not None:
            setattr(package, "runner", current_module)


_register_validation_runner_aliases()


def _get_server_fastapi_module():
    from chatbot import server_fastapi

    return server_fastapi


def _get_chat_endpoint_module():
    from chatbot.src.api.v1.endpoints import chat as chat_endpoint

    return chat_endpoint


def _emit_validation_event(event_callback: Any | None, **payload: Any) -> None:
    if event_callback is None:
        return
    event_callback(payload)


def _validation_check_status_from_payload(payload: Any) -> str:
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else dict(payload or {})
    passed_value = data.get("passed")
    if passed_value is True:
        return "passed"
    summary = str(data.get("failure_summary") or data.get("reason") or "")
    details = dict(data.get("details") or {}) if isinstance(data.get("details"), dict) else {}
    if "skipped because" in " ".join(summary.lower().split()) or str(details.get("skipped_reason") or "").strip():
        return "skipped"
    if str(data.get("status") or details.get("status") or "").strip() == "skipped":
        return "skipped"
    return "failed"


def _emit_validation_check_boundary(
    event_callback: Any | None,
    *,
    check_name: str,
    phase: str,
    status: str,
    summary: str,
) -> None:
    _emit_validation_event(
        event_callback,
        phase=f"validation_check_{check_name}_{phase}",
        event_type=f"validation_check_{phase}",
        summary=summary,
        details={
            "check_name": check_name,
            "status": status,
            "summary": summary,
        },
    )


def _append_text(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)


def _canonical_validation_runner_module() -> Any:
    return (
        sys.modules.get("chatbot.src.onboarding_v2.validation.runner")
        or sys.modules.get("src.onboarding_v2.validation.runner")
        or sys.modules[__name__]
    )


def _resolve_validation_paths(
    *,
    run_root: str | Path,
    host_runtime_workspace: str | Path,
    chatbot_runtime_workspace: str | Path,
    live_logs_root: str | Path | None,
) -> _ResolvedValidationPaths:
    return _ResolvedValidationPaths(
        run_root=Path(run_root).resolve(),
        host_runtime_workspace=Path(host_runtime_workspace).resolve(),
        chatbot_runtime_workspace=Path(chatbot_runtime_workspace).resolve(),
        live_logs_root=(
            Path(live_logs_root).resolve() if live_logs_root is not None else None
        ),
    )


def _runtime_harness_origin(
    *,
    chatbot_runtime_workspace: Path,
    harness_path: Path,
) -> str:
    workspace_root = chatbot_runtime_workspace.resolve()
    resolved_harness = harness_path.resolve()
    return (
        "workspace"
        if workspace_root == resolved_harness or workspace_root in resolved_harness.parents
        else "repo_fallback"
    )


def _runtime_context_payload(
    *,
    chatbot_runtime_workspace: Path,
    harness_path: Path,
) -> dict[str, Any]:
    workspace_root = chatbot_runtime_workspace.resolve()
    resolved_harness = harness_path.resolve()
    return {
        "resolved_chatbot_runtime_workspace": str(workspace_root),
        "runtime_harness_path": str(resolved_harness),
        "runtime_harness_origin": _runtime_harness_origin(
            chatbot_runtime_workspace=workspace_root,
            harness_path=resolved_harness,
        ),
    }


def _failure_result(
    summary: str,
    *,
    related_files: list[str] | None = None,
    failure_origin: str | None = None,
    failure_code: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "passed": False,
        "failure_summary": summary,
        "related_files": list(related_files or []),
    }
    if failure_origin is not None:
        payload["failure_origin"] = failure_origin
    if failure_code is not None:
        payload["failure_code"] = failure_code
    payload.update(extra)
    return payload


def _failure_metadata_from_context(context: Any) -> tuple[str | None, str | None]:
    if context is None:
        return None, None
    if isinstance(context, dict):
        return (
            _optional_text(context.get("failure_origin")),
            _optional_text(context.get("failure_code")),
        )
    return (
        _optional_text(getattr(context, "failure_origin", None)),
        _optional_text(getattr(context, "failure_code", None)),
    )


def _skipped_result(
    reason: str,
    *,
    upstream: Any | None = None,
    related_files: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    failure_origin, failure_code = _failure_metadata_from_context(upstream)
    return _failure_result(
        reason,
        related_files=related_files,
        failure_origin=failure_origin,
        failure_code=failure_code,
        **extra,
    )


def _platform_validation_failure_code(exc: Exception) -> str:
    message = str(exc).lower()
    if "resolved outside runtime workspace" in message or "resolved without a file origin" in message:
        return "runtime_module_origin_error"
    if "no module named" in message or "cannot import" in message:
        return "runtime_import_error"
    if "server_fastapi.app missing" in message:
        return "chatbot_runtime_app_missing"
    return "runtime_validation_platform_error"


def _subprocess_failure_code(message: str) -> str:
    normalized = str(message or "").lower()
    if "runtime_harness.py" in normalized and "no such file or directory" in normalized:
        return "runtime_harness_missing"
    if "returned no structured result" in normalized:
        return "runtime_validation_no_structured_result"
    return "runtime_validation_subprocess_failed"


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
    event_callback: Any | None = None,
    live_logs_root: str | Path | None = None,
    retrieval_status: dict[str, Any] | None = None,
) -> ValidationBundle:
    canonical_runner = _canonical_validation_runner_module()
    if getattr(canonical_runner, "run_validation", None) is not run_validation:
        return canonical_runner.run_validation(
            run_root=run_root,
            host_runtime_workspace=host_runtime_workspace,
            chatbot_runtime_workspace=chatbot_runtime_workspace,
            snapshot=snapshot,
            plan=plan,
            replay_result=replay_result,
            artifact_refs=artifact_refs,
            onboarding_credentials=onboarding_credentials,
            required_rechecks=required_rechecks,
            event_callback=event_callback,
            live_logs_root=live_logs_root,
            retrieval_status=retrieval_status,
        )
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
        event_callback=event_callback,
        live_logs_root=live_logs_root,
        retrieval_status=retrieval_status,
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
    event_callback: Any | None = None,
    live_logs_root: str | Path | None = None,
    retrieval_status: dict[str, Any] | None = None,
) -> ValidationRunResult:
    canonical_runner = _canonical_validation_runner_module()
    if getattr(canonical_runner, "run_validation_cycle", None) is not run_validation_cycle:
        return canonical_runner.run_validation_cycle(
            run_root=run_root,
            host_runtime_workspace=host_runtime_workspace,
            chatbot_runtime_workspace=chatbot_runtime_workspace,
            snapshot=snapshot,
            plan=plan,
            replay_result=replay_result,
            artifact_refs=artifact_refs,
            onboarding_credentials=onboarding_credentials,
            required_rechecks=required_rechecks,
            event_callback=event_callback,
            live_logs_root=live_logs_root,
            retrieval_status=retrieval_status,
        )
    resolved_paths = _resolve_validation_paths(
        run_root=run_root,
        host_runtime_workspace=host_runtime_workspace,
        chatbot_runtime_workspace=chatbot_runtime_workspace,
        live_logs_root=live_logs_root,
    )
    run_root = resolved_paths.run_root
    host_runtime_workspace = resolved_paths.host_runtime_workspace
    chatbot_runtime_workspace = resolved_paths.chatbot_runtime_workspace
    live_logs_root_path = resolved_paths.live_logs_root

    _emit_validation_check_boundary(
        event_callback,
        check_name="backend_runtime_prep",
        phase="started",
        status="running",
        summary="backend runtime prep started",
    )
    prep_result = prepare_backend_runtime(
        workspace=host_runtime_workspace,
        snapshot=snapshot,
        live_logs_root=live_logs_root_path,
        event_callback=event_callback,
    )
    _emit_validation_check_boundary(
        event_callback,
        check_name="backend_runtime_prep",
        phase="completed",
        status=_validation_check_status_from_payload(prep_result),
        summary=str(prep_result.failure_summary or "backend runtime prepared"),
    )
    runtime_state: BackendRuntimeState
    chatbot_runtime_boot: dict[str, Any]
    widget_bundle_fetch: dict[str, Any]
    host_auth_bootstrap: dict[str, Any]
    chatbot_adapter_auth: dict[str, Any]
    widget_order_e2e: WidgetOrderE2EResult
    conversation_validation: ConversationValidationResult
    if prep_result.passed:
        _emit_validation_check_boundary(
            event_callback,
            check_name="backend_runtime_boot",
            phase="started",
            status="running",
            summary="backend runtime boot started",
        )
        runtime_plan = build_backend_runtime_plan(
            workspace=host_runtime_workspace,
            snapshot=snapshot,
            plan=plan,
            prep_result=prep_result,
        )
        runtime_state = launch_backend_runtime(
            runtime_plan,
            log_path=(
                live_logs_root_path / "backend-launch.log"
                if live_logs_root_path is not None
                else None
            ),
        )
    else:
        runtime_plan = None
        runtime_state = _skipped_runtime_state(
            framework=snapshot.repo_profile.backend_framework,
            reason="backend runtime boot skipped because backend runtime prep failed",
            upstream=prep_result,
        )
    _emit_validation_check_boundary(
        event_callback,
        check_name="backend_runtime_boot",
        phase="completed",
        status=_validation_check_status_from_payload(runtime_state),
        summary=str(runtime_state.failure_summary or "backend runtime booted"),
    )

    if prep_result.passed and runtime_state.passed and runtime_plan is not None:
        _emit_validation_check_boundary(
            event_callback,
            check_name="chatbot_runtime_boot",
            phase="started",
            status="running",
            summary="chatbot runtime boot started",
        )
        chatbot_runtime_boot = validate_chatbot_runtime_boot(
            chatbot_runtime_workspace=chatbot_runtime_workspace,
            runtime_plan=runtime_plan,
            plan=plan,
        )
    else:
        chatbot_runtime_boot = _skipped_result(
            "chatbot runtime boot skipped because backend runtime boot failed"
            if prep_result.passed
            else "chatbot runtime boot skipped because backend runtime prep failed",
            upstream=runtime_state if prep_result.passed else prep_result,
        )
    _emit_validation_check_boundary(
        event_callback,
        check_name="chatbot_runtime_boot",
        phase="completed",
        status=_validation_check_status_from_payload(chatbot_runtime_boot),
        summary=str(chatbot_runtime_boot.get("failure_summary") or "chatbot runtime boot passed"),
    )

    if (
        prep_result.passed
        and runtime_state.passed
        and runtime_plan is not None
        and chatbot_runtime_boot.get("passed")
    ):
        _emit_validation_check_boundary(
            event_callback,
            check_name="widget_bundle_fetch",
            phase="started",
            status="running",
            summary="widget bundle fetch started",
        )
        widget_bundle_fetch = validate_widget_bundle_fetch(
            chatbot_runtime_workspace=chatbot_runtime_workspace,
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
            ),
            upstream=(
                chatbot_runtime_boot
                if prep_result.passed and runtime_state.passed
                else (runtime_state if prep_result.passed else prep_result)
            ),
        )
    _emit_validation_check_boundary(
        event_callback,
        check_name="widget_bundle_fetch",
        phase="completed",
        status=_validation_check_status_from_payload(widget_bundle_fetch),
        summary=str(widget_bundle_fetch.get("failure_summary") or "widget bundle fetch passed"),
    )

    if (
        prep_result.passed
        and runtime_state.passed
        and runtime_plan is not None
        and chatbot_runtime_boot.get("passed")
        and widget_bundle_fetch.get("passed")
    ):
        try:
            _emit_validation_check_boundary(
                event_callback,
                check_name="host_auth_bootstrap",
                phase="started",
                status="running",
                summary="host auth bootstrap started",
            )
            host_auth_bootstrap = validate_host_auth_bootstrap(
                run_root=run_root,
                host_runtime_workspace=host_runtime_workspace,
                runtime_plan=runtime_plan,
                runtime_state=runtime_state,
                snapshot=snapshot,
                plan=plan,
                onboarding_credentials=onboarding_credentials,
            )
            _emit_validation_check_boundary(
                event_callback,
                check_name="host_auth_bootstrap",
                phase="completed",
                status=_validation_check_status_from_payload(host_auth_bootstrap),
                summary=str(host_auth_bootstrap.get("failure_summary") or "host auth bootstrap passed"),
            )
            _emit_validation_check_boundary(
                event_callback,
                check_name="chatbot_adapter_auth",
                phase="started",
                status="running",
                summary="chatbot adapter auth started",
            )
            chatbot_adapter_auth = validate_chatbot_adapter_auth(
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                bootstrap_result=host_auth_bootstrap,
                plan=plan,
            )
            _emit_validation_check_boundary(
                event_callback,
                check_name="chatbot_adapter_auth",
                phase="completed",
                status=_validation_check_status_from_payload(chatbot_adapter_auth),
                summary=str(chatbot_adapter_auth.get("failure_summary") or "chatbot adapter auth passed"),
            )
            _emit_validation_check_boundary(
                event_callback,
                check_name="widget_order_e2e",
                phase="started",
                status="running",
                summary="widget order e2e started",
            )
            widget_order_e2e = validate_widget_order_e2e(
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                bootstrap_result=host_auth_bootstrap,
                adapter_auth_result=chatbot_adapter_auth,
                plan=plan,
            )
            widget_order_e2e = _coerce_widget_order_e2e_result(widget_order_e2e)
            _emit_validation_check_boundary(
                event_callback,
                check_name="widget_order_e2e",
                phase="completed",
                status=_validation_check_status_from_payload(widget_order_e2e),
                summary=str(widget_order_e2e.failure_summary or "widget order e2e passed"),
            )
            _emit_validation_check_boundary(
                event_callback,
                check_name="conversation_validation",
                phase="started",
                status="running",
                summary="conversation validation started",
            )
            conversation_validation = validate_conversation_runtime(
                run_root=run_root,
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                snapshot=snapshot,
                plan=plan,
                prep_result=prep_result,
                bootstrap_result=host_auth_bootstrap,
                adapter_auth_result=chatbot_adapter_auth,
                widget_order_e2e_result=widget_order_e2e,
                onboarding_credentials=onboarding_credentials,
                event_callback=event_callback,
                live_logs_root=live_logs_root_path,
            )
            _emit_validation_check_boundary(
                event_callback,
                check_name="conversation_validation",
                phase="completed",
                status=_validation_check_status_from_payload(conversation_validation),
                summary=str(conversation_validation.failure_summary or "conversation validation passed"),
            )
        finally:
            stop_backend_runtime(runtime_state)
    else:
        reason = (
            "backend runtime boot failed"
            if prep_result.passed
            else "backend runtime prep failed"
        )
        upstream_failure: Any = prep_result if not prep_result.passed else runtime_state
        if prep_result.passed and runtime_state.passed and not chatbot_runtime_boot.get("passed"):
            reason = "chatbot runtime boot failed"
            upstream_failure = chatbot_runtime_boot
        elif (
            prep_result.passed
            and runtime_state.passed
            and chatbot_runtime_boot.get("passed")
            and not widget_bundle_fetch.get("passed")
        ):
            reason = "widget bundle fetch failed"
            upstream_failure = widget_bundle_fetch
        host_auth_bootstrap = _skipped_result(
            "host auth bootstrap skipped because " + reason,
            upstream=upstream_failure,
        )
        chatbot_adapter_auth = _skipped_result(
            "chatbot adapter auth skipped because " + reason,
            upstream=upstream_failure,
        )
        upstream_failure_origin, upstream_failure_code = _failure_metadata_from_context(
            upstream_failure
        )
        widget_order_e2e = WidgetOrderE2EResult(
            passed=False,
            failure_summary="widget order e2e skipped because " + reason,
            failure_origin=upstream_failure_origin,
            failure_code=upstream_failure_code,
            related_files=[],
        )
        fixture_manifest = dict(prep_result.fixture_manifest or {})
        if upstream_failure_origin and "failure_origin" not in fixture_manifest:
            fixture_manifest["failure_origin"] = upstream_failure_origin
        if upstream_failure_code and "failure_code" not in fixture_manifest:
            fixture_manifest["failure_code"] = upstream_failure_code
        conversation_validation = ConversationValidationResult(
            passed=False,
            failure_summary="conversation validation skipped because " + reason,
            failure_origin=upstream_failure_origin,
            failure_code=upstream_failure_code,
            fixture_manifest=fixture_manifest,
            related_files=[],
        )
        _emit_validation_check_boundary(
            event_callback,
            check_name="host_auth_bootstrap",
            phase="completed",
            status=_validation_check_status_from_payload(host_auth_bootstrap),
            summary=str(host_auth_bootstrap.get("failure_summary") or "host auth bootstrap skipped"),
        )
        _emit_validation_check_boundary(
            event_callback,
            check_name="chatbot_adapter_auth",
            phase="completed",
            status=_validation_check_status_from_payload(chatbot_adapter_auth),
            summary=str(chatbot_adapter_auth.get("failure_summary") or "chatbot adapter auth skipped"),
        )
        _emit_validation_check_boundary(
            event_callback,
            check_name="widget_order_e2e",
            phase="completed",
            status=_validation_check_status_from_payload(widget_order_e2e),
            summary=str(widget_order_e2e.failure_summary or "widget order e2e skipped"),
        )
        _emit_validation_check_boundary(
            event_callback,
            check_name="conversation_validation",
            phase="completed",
            status=_validation_check_status_from_payload(conversation_validation),
            summary=str(conversation_validation.failure_summary or "conversation validation skipped"),
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
        *_build_retrieval_validation_checks(
            plan=plan,
            retrieval_status=retrieval_status,
        ),
        ValidationCheck(
            name="conversation_validation",
            passed=conversation_validation.passed,
            summary=conversation_validation.failure_summary or "conversation validation passed",
            blocking=False,
            details=conversation_validation.model_dump(mode="json"),
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

    advisory_failures = [
        check.name for check in checks if (not check.blocking and not check.passed)
    ]
    first_failure = next((check for check in checks if check.blocking and not check.passed), None)
    related_artifacts = [
        ref.model_dump(mode="json") if hasattr(ref, "model_dump") else ref
        for ref in artifact_refs.values()
        if ref is not None
    ]
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
        advisory_failures=advisory_failures,
        failure_signature=(
            None
            if first_failure is None
            else build_failure_signature(
                check_name=first_failure.name, summary=first_failure.summary
            )
        ),
        failure_summary=None if first_failure is None else first_failure.summary,
        failure_origin=(
            _optional_text(first_failure.details.get("failure_origin"))
            if first_failure is not None and isinstance(first_failure.details, dict)
            else None
        ),
        failure_code=(
            _optional_text(first_failure.details.get("failure_code"))
            if first_failure is not None and isinstance(first_failure.details, dict)
            else None
        ),
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
        conversation_validation=conversation_validation,
    )


def _build_retrieval_validation_checks(
    *,
    plan: IntegrationPlan,
    retrieval_status: dict[str, Any] | None,
) -> list[ValidationCheck]:
    if retrieval_status is None:
        return []
    status_map = dict((retrieval_status or {}).get("corpora") or {})
    checks: list[ValidationCheck] = []
    corpus_plans = [] if plan.retrieval_index_plan is None else list(plan.retrieval_index_plan.corpora)
    for corpus_plan in corpus_plans:
        payload = dict(status_map.get(corpus_plan.corpus) or {})
        passed = (
            str(payload.get("status") or "") == "completed"
            and bool(payload.get("smoke_passed", True))
            and int(payload.get("documents_indexed") or 0) >= int(corpus_plan.minimum_expected_documents)
        )
        summary = (
            f"{corpus_plan.corpus} retrieval ready"
            if passed
            else f"{corpus_plan.corpus} retrieval unavailable"
        )
        checks.append(
            ValidationCheck(
                name=f"retrieval_{corpus_plan.corpus}",
                passed=passed,
                summary=summary,
                blocking=False,
                details={
                    "collection_alias": corpus_plan.collection_alias,
                    "minimum_expected_documents": corpus_plan.minimum_expected_documents,
                    **payload,
                },
            )
        )
    return checks


def validate_host_auth_bootstrap(
    *,
    run_root: Path,
    host_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    runtime_state: BackendRuntimeState | None = None,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    onboarding_credentials: dict[str, str] | None = None,
) -> dict[str, Any]:
    del run_root, host_runtime_workspace, snapshot
    base_url = _runtime_base_url(
        runtime_plan,
        chat_auth_contract_path=plan.host_backend.chat_auth_contract_path,
    ).rstrip("/")
    credentials = {
        "email": "test1@example.com",
        "password": "password123",
    }
    credentials.update(
        {key: value for key, value in (onboarding_credentials or {}).items() if value}
    )
    login_path = str(plan.host_backend.login_endpoint or "").strip()
    if login_path and not login_path.startswith("/"):
        login_path = "/" + login_path
    login_url = f"{base_url}{login_path}" if login_path else None
    bootstrap_url = f"{base_url}{plan.host_backend.chat_auth_contract_path}"
    related_files = _stable_paths(
        [
            "backend/chat_auth.py",
            plan.host_backend.route_target,
            plan.host_backend.auth_handler_source,
            plan.host_backend.generated_handler_path,
        ]
    )
    backend_stderr_tail = _truncate_text((runtime_state.stderr if runtime_state else ""), limit=2000)

    login_response: Any | None = None
    login_error = ""
    bootstrap_response: Any | None = None
    bootstrap_error = ""
    payload: dict[str, Any] = {}

    with httpx.Client(follow_redirects=True, timeout=10.0) as client:
        if login_url:
            try:
                login_response = client.post(login_url, json=credentials)
            except httpx.HTTPError as exc:
                login_error = str(exc)
        else:
            login_error = "planned login endpoint unavailable"
        try:
            bootstrap_response = client.post(bootstrap_url)
        except httpx.HTTPError as exc:
            bootstrap_error = str(exc)
            bootstrap_response = None
        try:
            payload = {} if bootstrap_response is None else bootstrap_response.json()
        except ValueError:
            payload = {}

    bootstrap_mode = (
        "real_host_session"
        if login_response is not None and login_response.status_code == 200
        else "validation_bridge"
    )
    passed, summary = _evaluate_bootstrap_contract(
        bootstrap_status=None if bootstrap_response is None else bootstrap_response.status_code,
        payload=payload,
    )
    failure_origin: str | None
    failure_code: str | None
    if passed:
        failure_origin = "login" if bootstrap_mode == "validation_bridge" else None
        failure_code = None
        summary = "host auth bootstrap passed"
    elif bootstrap_response is None:
        failure_origin = "host_contract"
        failure_code = "bootstrap_request_failed"
        summary = bootstrap_error or "host auth bootstrap request failed"
    elif bootstrap_response.status_code != 200:
        failure_origin = "host_contract"
        failure_code = "bootstrap_http_status_failed"
    elif not bool(payload.get("authenticated")):
        failure_origin = "host_contract"
        failure_code = "bootstrap_contract_missing_authenticated"
    elif not str(payload.get("site_id") or "").strip():
        failure_origin = "host_contract"
        failure_code = "bootstrap_contract_missing_site_id"
    elif not str(payload.get("access_token") or "").strip():
        failure_origin = "host_contract"
        failure_code = "bootstrap_contract_missing_access_token"
    elif not str((payload.get("user") or {}).get("id") or "").strip():
        failure_origin = "host_contract"
        failure_code = "bootstrap_contract_missing_user_id"
    elif payload:
        failure_origin = "host_contract"
        failure_code = "bootstrap_contract_invalid"
    else:
        failure_origin = "host_contract"
        failure_code = "bootstrap_request_failed"
    return {
        "passed": passed,
        "failure_summary": summary,
        "bootstrap_payload": payload,
        "login_status": None if login_response is None else login_response.status_code,
        "bootstrap_status": None if bootstrap_response is None else bootstrap_response.status_code,
        "login_url": login_url,
        "bootstrap_url": bootstrap_url,
        "auth_handler_source": plan.host_backend.auth_handler_source,
        "session_cookies": _client_cookies_dict(client),
        "bootstrap_mode": bootstrap_mode,
        "failure_origin": failure_origin,
        "failure_code": failure_code,
        "login_response_text": _truncate_text(
            login_error or str(getattr(login_response, "text", "") or ""),
        ),
        "bootstrap_response_text": _truncate_text(
            bootstrap_error or str(getattr(bootstrap_response, "text", "") or ""),
        ),
        "backend_stderr_tail": backend_stderr_tail,
        "related_files": related_files,
    }


def _validate_chatbot_adapter_auth_inprocess(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    bootstrap_result: dict[str, Any],
    plan: IntegrationPlan,
) -> dict[str, Any]:
    if not bootstrap_result.get("passed"):
        return _skipped_result(
            "chatbot adapter auth skipped because host auth bootstrap failed"
        )
    auth_context, auth_failure = _build_bridge_auth_context(
        bootstrap_result=bootstrap_result,
        plan=plan,
        user_id="__bridge__",
    )
    related_files = [
        f"{plan.chatbot_bridge.adapter_package}/adapter.py",
        f"{plan.chatbot_bridge.adapter_package}/auth.py",
        plan.chatbot_bridge.setup_target,
    ]
    if auth_context is None:
        return _failure_result(
            auth_failure or "chatbot adapter auth missing transport credentials",
            related_files=related_files,
            failure_origin="host_contract",
            failure_code="bridge_auth_context_missing",
        )

    module_origins: dict[str, str] = {}
    try:
        _, _, adapter_setup, _, module_origins = _load_runtime_validation_modules(
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        )
    except Exception as exc:
        return _failure_result(
            f"chatbot adapter auth failed: {exc}",
            related_files=related_files,
            failure_origin="platform_validation",
            failure_code=_platform_validation_failure_code(exc),
            module_origins=module_origins or None,
        )
    try:
        adapter = adapter_setup.resolve_site_adapter(plan.chatbot_bridge.site_key)
    except Exception as exc:
        return _failure_result(
            f"chatbot adapter auth failed: {exc}",
            related_files=related_files,
            failure_origin="generated_runtime",
            failure_code="runtime_registry_resolution_failed",
            module_origins=module_origins,
        )
    try:
        validated_user = asyncio.run(adapter.validate_auth(auth_context))
    except Exception as exc:
        return _failure_result(
            f"chatbot adapter auth failed: {exc}",
            related_files=related_files,
            failure_origin="generated_runtime",
            failure_code="adapter_auth_validation_failed",
            module_origins=module_origins,
        )
    user_id = str(getattr(validated_user, "id", "") or "").strip()
    success_result = {
        "passed": bool(user_id),
        "failure_summary": "chatbot adapter auth passed"
        if user_id
        else "chatbot adapter auth missing user.id",
        "failure_origin": None if user_id else "generated_runtime",
        "failure_code": None if user_id else "validated_user_missing_id",
        "validated_user": validated_user.model_dump(mode="json"),
        "related_files": related_files,
    }
    if module_origins:
        success_result["module_origins"] = module_origins
    return success_result


def validate_chatbot_adapter_auth(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    bootstrap_result: dict[str, Any],
    plan: IntegrationPlan,
) -> dict[str, Any]:
    related_files = [
        f"{plan.chatbot_bridge.adapter_package}/adapter.py",
        f"{plan.chatbot_bridge.adapter_package}/auth.py",
        plan.chatbot_bridge.setup_target,
    ]
    if not bootstrap_result.get("passed"):
        return _skipped_result(
            "chatbot adapter auth skipped because host auth bootstrap failed"
        )
    try:
        envelope = _run_runtime_validation_subprocess(
            action="adapter_auth",
            chatbot_runtime_workspace=chatbot_runtime_workspace,
            runtime_plan=runtime_plan,
            plan=plan,
            payload={
                "bootstrap_result": bootstrap_result,
            },
        )
    except _RuntimeValidationSubprocessError as exc:
        return _failure_result(
            f"chatbot adapter auth failed: {exc}",
            related_files=related_files,
            failure_origin=exc.failure_origin,
            failure_code=exc.failure_code,
            **exc.diagnostics,
        )
    except Exception as exc:
        return _failure_result(
            f"chatbot adapter auth failed: {exc}",
            related_files=related_files,
            failure_origin="platform_validation",
            failure_code="runtime_validation_subprocess_failed",
        )
    result = dict(envelope.get("result") or {})
    if "related_files" not in result:
        result["related_files"] = related_files
    return result


def _validate_chatbot_runtime_boot_inprocess(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
) -> dict[str, Any]:
    del runtime_plan
    related_files = [
        "server_fastapi.py",
        "src/tools/adapter_order_tools.py",
        "src/tools/order_tools.py",
    ]
    try:
        runtime_server_fastapi, _, _, _, module_origins = _load_runtime_validation_modules(
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        )
    except Exception as exc:
        return _failure_result(
            f"chatbot runtime boot failed: {exc}",
            related_files=related_files,
            failure_origin="platform_validation",
            failure_code=_platform_validation_failure_code(exc),
        )
    app = getattr(runtime_server_fastapi, "app", None)
    if app is None:
        return _failure_result(
            "chatbot runtime boot failed: server_fastapi.app missing",
            related_files=related_files,
            failure_origin="generated_runtime",
            failure_code="chatbot_runtime_app_missing",
            module_origins=module_origins,
        )
    return {
        "passed": True,
        "failure_summary": "chatbot runtime boot passed",
        "module_origins": module_origins,
        "related_files": related_files,
    }


def validate_chatbot_runtime_boot(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
) -> dict[str, Any]:
    related_files = [
        "server_fastapi.py",
        "src/tools/adapter_order_tools.py",
        "src/tools/order_tools.py",
    ]
    try:
        envelope = _run_runtime_validation_subprocess(
            action="chatbot_runtime_boot",
            chatbot_runtime_workspace=chatbot_runtime_workspace,
            runtime_plan=runtime_plan,
            plan=plan,
            payload={},
        )
    except _RuntimeValidationSubprocessError as exc:
        return _failure_result(
            f"chatbot runtime boot failed: {exc}",
            related_files=related_files,
            failure_origin=exc.failure_origin,
            failure_code=exc.failure_code,
            **exc.diagnostics,
        )
    except Exception as exc:
        return _failure_result(
            f"chatbot runtime boot failed: {exc}",
            related_files=related_files,
            failure_origin="platform_validation",
            failure_code="runtime_validation_subprocess_failed",
        )
    result = dict(envelope.get("result") or {})
    if "related_files" not in result:
        result["related_files"] = related_files
    return result


def _validate_widget_bundle_fetch_inprocess(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
) -> dict[str, Any]:
    chatbot_base_url = str(plan.host_frontend.chatbot_server_base_url or "").strip().rstrip("/")
    widget_path = "/widget.js"
    host_base_url = _runtime_base_url(
        runtime_plan,
        chat_auth_contract_path=plan.host_backend.chat_auth_contract_path,
    ).rstrip("/")

    if not chatbot_base_url:
        return _failure_result(
            "widget bundle fetch failed: chatbotServerBaseUrl is empty",
            related_files=[plan.host_frontend.mount_target],
            failure_origin="generated_runtime",
            failure_code="widget_base_url_missing",
            target_url=widget_path,
        )

    target_url = f"{chatbot_base_url}{widget_path}"
    chatbot_origin = urlparse(chatbot_base_url)
    host_origin = urlparse(host_base_url)
    if (
        chatbot_origin.scheme == host_origin.scheme
        and chatbot_origin.netloc == host_origin.netloc
    ):
        return _failure_result(
            "widget bundle fetch failed: resolved to host origin",
            related_files=[plan.host_frontend.mount_target],
            failure_origin="generated_runtime",
            failure_code="widget_resolved_to_host_origin",
            target_url=target_url,
        )

    try:
        server_fastapi, _, _, _, module_origins = _load_runtime_validation_modules(
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        )
    except Exception as exc:
        return _failure_result(
            f"widget bundle fetch failed: {exc}",
            related_files=[plan.host_frontend.mount_target],
            failure_origin="platform_validation",
            failure_code=_platform_validation_failure_code(exc),
            target_url=target_url,
        )
    client = TestClient(server_fastapi.app, base_url=chatbot_base_url)
    response = client.get(widget_path)
    passed = (
        response.status_code == 200
        and "javascript" in response.headers.get("content-type", "").lower()
        and "order-cs-widget" in response.text
    )
    result = {
        "passed": passed,
        "failure_summary": (
            "widget bundle fetch passed"
            if passed
            else f"widget bundle fetch failed with status {response.status_code}"
        ),
        "failure_origin": None if passed else "generated_runtime",
        "failure_code": None if passed else "widget_bundle_fetch_http_status_failed",
        "target_url": target_url,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "related_files": [
            plan.host_frontend.mount_target,
            "chatbot/src/api/v1/endpoints/chat.py",
            "chatbot/frontend/shared_widget/web-component.tsx",
        ],
    }
    if module_origins:
        result["module_origins"] = module_origins
    return result


def validate_widget_bundle_fetch(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
) -> dict[str, Any]:
    try:
        envelope = _run_runtime_validation_subprocess(
            action="widget_bundle_fetch",
            chatbot_runtime_workspace=chatbot_runtime_workspace,
            runtime_plan=runtime_plan,
            plan=plan,
            payload={},
        )
    except _RuntimeValidationSubprocessError as exc:
        return _failure_result(
            f"widget bundle fetch failed: {exc}",
            related_files=[plan.host_frontend.mount_target],
            failure_origin=exc.failure_origin,
            failure_code=exc.failure_code,
            target_url="/widget.js",
            **exc.diagnostics,
        )
    except Exception as exc:
        return _failure_result(
            f"widget bundle fetch failed: {exc}",
            related_files=[plan.host_frontend.mount_target],
            failure_origin="platform_validation",
            failure_code="runtime_validation_subprocess_failed",
            target_url="/widget.js",
        )
    result = dict(envelope.get("result") or {})
    if "related_files" not in result:
        result["related_files"] = [plan.host_frontend.mount_target]
    return result


def _validate_widget_order_e2e_inprocess(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    bootstrap_result: dict[str, Any],
    adapter_auth_result: dict[str, Any],
    plan: IntegrationPlan,
) -> WidgetOrderE2EResult:

    if not bootstrap_result.get("passed"):
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary="widget order e2e skipped because host auth bootstrap failed",
            failure_origin="host_contract",
            failure_code="host_auth_bootstrap_failed",
            related_files=[],
        )
    if not adapter_auth_result.get("passed"):
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary="widget order e2e skipped because chatbot adapter auth failed",
            failure_origin=str(adapter_auth_result.get("failure_origin") or "generated_runtime"),
            failure_code=str(adapter_auth_result.get("failure_code") or "chatbot_adapter_auth_failed"),
            related_files=[],
        )

    try:
        runtime_server_fastapi, runtime_chat_endpoint, adapter_setup, _, module_origins = _load_runtime_validation_modules(
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        )
    except Exception as exc:
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary=f"widget order e2e failed: {exc}",
            failure_origin="platform_validation",
            failure_code=_platform_validation_failure_code(exc),
            related_files=_widget_order_related_files(plan),
        )
    try:
        adapter = adapter_setup.resolve_site_adapter(plan.chatbot_bridge.site_key)
    except Exception as exc:
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary=f"widget order e2e failed: {exc}",
            failure_origin="generated_runtime",
            failure_code="runtime_registry_resolution_failed",
            related_files=_widget_order_related_files(plan),
        )
    auth_context, auth_failure = _build_bridge_auth_context(
        bootstrap_result=bootstrap_result,
        plan=plan,
        user_id=str(
            (adapter_auth_result.get("validated_user") or {}).get("id") or "__bridge__"
        ),
    )
    if auth_context is None:
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary=auth_failure or "widget order e2e auth context failed",
            failure_origin="host_contract",
            failure_code="bridge_auth_context_missing",
            related_files=_widget_order_related_files(plan),
        )
    try:
        sample_context = _acquire_widget_order_sample(
            adapter=adapter,
            auth_context=auth_context,
            plan=plan,
        )
    except Exception as exc:
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary=f"widget order sample acquisition failed: {exc}",
            failure_origin="upstream_fixture",
            failure_code="widget_order_sample_acquisition_failed",
            scenario_mode="sample_acquisition_failed",
            related_files=_widget_order_related_files(plan),
        )
    capability_contract = build_validation_capability_contract(
        plan=plan,
        fixture_manifest={
            "enabled_retrieval_corpora": list(plan.host_frontend.enabled_retrieval_corpora or []),
            "widget_features": dict(plan.host_frontend.widget_features or {}),
        },
        sample_context=sample_context,
    )
    flow_reports = _collect_widget_order_flow_report(
        adapter=adapter,
        auth_context=auth_context,
        plan=plan,
        sample_context=sample_context,
        server_fastapi=runtime_server_fastapi,
        chat_endpoint=runtime_chat_endpoint,
    )
    result = _evaluate_widget_order_flow_report(
        plan=plan,
        flow_reports=flow_reports,
        capability_contract=capability_contract,
        sample_context=sample_context,
    )
    return result.model_copy(
        update={
            "failure_origin": None if result.passed else "generated_runtime",
            "failure_code": None if result.passed else "widget_order_flow_failed",
            "module_origins": module_origins,
        }
    )


def validate_widget_order_e2e(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    bootstrap_result: dict[str, Any],
    adapter_auth_result: dict[str, Any],
    plan: IntegrationPlan,
) -> WidgetOrderE2EResult:
    if not bootstrap_result.get("passed"):
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary="widget order e2e skipped because host auth bootstrap failed",
            failure_origin="host_contract",
            failure_code="host_auth_bootstrap_failed",
            related_files=_widget_order_related_files(plan),
        )
    if not adapter_auth_result.get("passed"):
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary="widget order e2e skipped because chatbot adapter auth failed",
            failure_origin=str(adapter_auth_result.get("failure_origin") or "generated_runtime"),
            failure_code=str(adapter_auth_result.get("failure_code") or "chatbot_adapter_auth_failed"),
            related_files=_widget_order_related_files(plan),
        )
    try:
        envelope = _run_runtime_validation_subprocess(
            action="widget_order_e2e",
            chatbot_runtime_workspace=chatbot_runtime_workspace,
            runtime_plan=runtime_plan,
            plan=plan,
            payload={
                "bootstrap_result": bootstrap_result,
                "adapter_auth_result": adapter_auth_result,
            },
        )
    except _RuntimeValidationSubprocessError as exc:
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary=f"widget order e2e failed: {exc}",
            failure_origin=exc.failure_origin,
            failure_code=exc.failure_code,
            module_origins=dict(exc.diagnostics.get("module_origins") or {})
            if isinstance(exc.diagnostics, dict)
            else {},
            resolved_chatbot_runtime_workspace=_optional_text(
                (exc.diagnostics or {}).get("resolved_chatbot_runtime_workspace")
            )
            if isinstance(exc.diagnostics, dict)
            else None,
            runtime_harness_path=_optional_text(
                (exc.diagnostics or {}).get("runtime_harness_path")
            )
            if isinstance(exc.diagnostics, dict)
            else None,
            runtime_harness_origin=_optional_text(
                (exc.diagnostics or {}).get("runtime_harness_origin")
            )
            if isinstance(exc.diagnostics, dict)
            else None,
            related_files=_widget_order_related_files(plan),
        )
    except Exception as exc:
        return WidgetOrderE2EResult(
            passed=False,
            failure_summary=f"widget order e2e failed: {exc}",
            failure_origin="platform_validation",
            failure_code="runtime_validation_subprocess_failed",
            related_files=_widget_order_related_files(plan),
        )
    return _coerce_widget_order_e2e_result(envelope.get("result") or {})


def _validate_conversation_runtime_inprocess(
    *,
    run_root: Path,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    prep_result: BackendRuntimePrepResult,
    bootstrap_result: dict[str, Any],
    adapter_auth_result: dict[str, Any],
    widget_order_e2e_result: WidgetOrderE2EResult | None = None,
    onboarding_credentials: dict[str, str] | None = None,
    event_callback: Any | None = None,
    live_logs_root: str | Path | None = None,
) -> ConversationValidationResult:
    if not bootstrap_result.get("passed"):
        return ConversationValidationResult(
            passed=False,
            failure_summary="conversation validation skipped because host auth bootstrap failed",
            failure_origin="host_contract",
            failure_code="host_auth_bootstrap_failed",
            fixture_manifest=dict(prep_result.fixture_manifest or {}),
            related_files=_widget_order_related_files(plan),
        )
    if not adapter_auth_result.get("passed"):
        return ConversationValidationResult(
            passed=False,
            failure_summary="conversation validation skipped because chatbot adapter auth failed",
            failure_origin=str(adapter_auth_result.get("failure_origin") or "generated_runtime"),
            failure_code=str(adapter_auth_result.get("failure_code") or "chatbot_adapter_auth_failed"),
            fixture_manifest=dict(prep_result.fixture_manifest or {}),
            related_files=_widget_order_related_files(plan),
        )

    fixture_manifest = _build_runtime_fixture_manifest(
        chatbot_runtime_workspace=chatbot_runtime_workspace,
        runtime_plan=runtime_plan,
        plan=plan,
        prep_result=prep_result,
        bootstrap_result=bootstrap_result,
        adapter_auth_result=adapter_auth_result,
        onboarding_credentials=onboarding_credentials,
    )
    capability_contract = build_validation_capability_contract(
        plan=plan,
        fixture_manifest=fixture_manifest,
        sample_context={
            "sampled_order_id": getattr(widget_order_e2e_result, "sampled_order_id", None),
            "sampled_option_id": getattr(widget_order_e2e_result, "sampled_option_id", None),
            "scenario_mode": getattr(widget_order_e2e_result, "scenario_mode", None),
        },
        widget_order_e2e_result=widget_order_e2e_result,
    )
    fixture_manifest["validation_capability_contract"] = capability_contract.model_dump(
        mode="json"
    )
    if not fixture_manifest.get("available"):
        return ConversationValidationResult(
            passed=False,
            failure_summary=str(fixture_manifest.get("reason") or "fixture_unavailable"),
            failure_origin=_optional_text(fixture_manifest.get("failure_origin")),
            failure_code=_optional_text(fixture_manifest.get("failure_code")),
            fixture_manifest=fixture_manifest,
            validation_capability_contract=capability_contract.model_dump(mode="json"),
            related_files=_widget_order_related_files(plan),
        )

    try:
        with _patched_chatbot_runtime_env(runtime_plan=runtime_plan, plan=plan):
            runtime_server_fastapi, runtime_chat_endpoint, _, _, module_origins = _load_runtime_validation_modules(
                chatbot_runtime_workspace=chatbot_runtime_workspace
            )
    except Exception as exc:
        fixture_manifest["failure_origin"] = "platform_validation"
        fixture_manifest["failure_code"] = _platform_validation_failure_code(exc)
        return ConversationValidationResult(
            passed=False,
            failure_summary=f"conversation validation failed: {exc}",
            failure_origin="platform_validation",
            failure_code=_platform_validation_failure_code(exc),
            fixture_manifest=fixture_manifest,
            validation_capability_contract=capability_contract.model_dump(mode="json"),
            related_files=_widget_order_related_files(plan),
        )
    with _patched_chatbot_runtime_env(runtime_plan=runtime_plan, plan=plan):
        fixture_manifest["module_origins"] = module_origins

        transcripts_dir = run_root / "conversation-validation"
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        live_logs_root_path = Path(live_logs_root).resolve() if live_logs_root is not None else None
        if live_logs_root_path is not None:
            live_logs_root_path.mkdir(parents=True, exist_ok=True)
        scenarios = _build_conversation_scenarios(
            fixture_manifest=fixture_manifest,
            capability_contract=capability_contract,
        )
        previous_states: dict[str, dict[str, Any]] = {}
        results: list[ConversationScenarioResult] = []
        transcript_contents: dict[str, str] = {}
        trace_contents: dict[str, str] = {}

        for scenario in scenarios:
            scenario_log_path = (
                live_logs_root_path / f"conversation-{scenario['scenario_id']}.log"
                if live_logs_root_path is not None
                else None
            )
            _emit_validation_event(
                event_callback,
                phase="conversation_scenario_start",
                event_type="conversation_validation_scenario_started",
                summary=f"conversation scenario {scenario['scenario_id']} started",
                details={
                    "scenario_id": scenario["scenario_id"],
                    "mode": scenario["mode"],
                    "log_path": str(scenario_log_path) if scenario_log_path is not None else None,
                    "status": "running",
                },
            )
            _append_text(
                scenario_log_path,
                json.dumps(
                    {
                        "event": "start",
                        "scenario_id": scenario["scenario_id"],
                        "mode": scenario["mode"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
            )
            if scenario["scenario_id"] == "unauthenticated_chat_request":
                result, transcript_text = asyncio.run(
                    _run_unauthenticated_conversation_scenario(
                        runtime_server_fastapi=runtime_server_fastapi,
                        fixture_manifest=fixture_manifest,
                        scenario=scenario,
                        transcripts_dir=transcripts_dir,
                    )
                )
            else:
                previous_state = None
                previous_state_from = str(scenario.get("previous_state_from") or "").strip()
                if previous_state_from:
                    previous_state = previous_states.get(previous_state_from)
                result, transcript_text, trace_text, final_state = asyncio.run(
                    _run_authenticated_conversation_scenario(
                        runtime_server_fastapi=runtime_server_fastapi,
                        runtime_chat_endpoint=runtime_chat_endpoint,
                        fixture_manifest=fixture_manifest,
                        scenario=scenario,
                        previous_state=previous_state,
                        transcripts_dir=transcripts_dir,
                    )
                )
                trace_contents[scenario["scenario_id"]] = trace_text
                if final_state:
                    previous_states[scenario["scenario_id"]] = final_state
            result = result.model_copy(
                update={
                    "log_path": str(scenario_log_path) if scenario_log_path is not None else result.log_path
                }
            )
            results.append(result)
            transcript_contents[scenario["scenario_id"]] = transcript_text
            _append_text(
                scenario_log_path,
                json.dumps(
                    {
                        "event": "finish",
                        "scenario_id": scenario["scenario_id"],
                        "final_verdict": result.final_verdict,
                        "transcript_path": result.transcript_path,
                        "trace_path": result.trace_path,
                    },
                    ensure_ascii=False,
                )
                + "\n",
            )
            _emit_validation_event(
                event_callback,
                phase="conversation_scenario_finish",
                event_type="conversation_validation_scenario_completed",
                summary=f"conversation scenario {scenario['scenario_id']} completed",
                details={
                    "scenario_id": scenario["scenario_id"],
                    "mode": scenario["mode"],
                    "status": "completed" if result.final_verdict == "pass" else "failed",
                    "log_path": str(scenario_log_path) if scenario_log_path is not None else None,
                    "transcript_path": result.transcript_path,
                    "trace_path": result.trace_path,
                    "final_verdict": result.final_verdict,
                },
            )

        passed = all(result.final_verdict == "pass" for result in results)
        failure_categories = sorted(
            {
                str(result.failure_category).strip()
                for result in results
                if str(result.failure_category or "").strip()
            }
        )
        failure_summary = None if passed else "one or more conversation scenarios failed"
        if failure_summary and failure_categories:
            failure_summary = f"{failure_summary}: {', '.join(failure_categories)}"
        return ConversationValidationResult(
            passed=passed,
            failure_summary=failure_summary,
            failure_origin=None if passed else "generated_runtime",
            failure_code=None if passed else "conversation_scenarios_failed",
            fixture_manifest=fixture_manifest,
            validation_capability_contract=capability_contract.model_dump(mode="json"),
            scenarios=results,
            transcript_contents=transcript_contents,
            trace_contents=trace_contents,
            related_files=_widget_order_related_files(plan),
        )


def validate_conversation_runtime(
    *,
    run_root: Path,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    prep_result: BackendRuntimePrepResult,
    bootstrap_result: dict[str, Any],
    adapter_auth_result: dict[str, Any],
    widget_order_e2e_result: WidgetOrderE2EResult | None = None,
    onboarding_credentials: dict[str, str] | None = None,
    event_callback: Any | None = None,
    live_logs_root: str | Path | None = None,
) -> ConversationValidationResult:
    if not bootstrap_result.get("passed"):
        return ConversationValidationResult(
            passed=False,
            failure_summary="conversation validation skipped because host auth bootstrap failed",
            failure_origin="host_contract",
            failure_code="host_auth_bootstrap_failed",
            fixture_manifest=dict(prep_result.fixture_manifest or {}),
            related_files=_widget_order_related_files(plan),
        )
    if not adapter_auth_result.get("passed"):
        return ConversationValidationResult(
            passed=False,
            failure_summary="conversation validation skipped because chatbot adapter auth failed",
            failure_origin=str(adapter_auth_result.get("failure_origin") or "generated_runtime"),
            failure_code=str(adapter_auth_result.get("failure_code") or "chatbot_adapter_auth_failed"),
            fixture_manifest=dict(prep_result.fixture_manifest or {}),
            related_files=_widget_order_related_files(plan),
        )
    try:
        envelope = _run_runtime_validation_subprocess(
            action="conversation_runtime",
            chatbot_runtime_workspace=chatbot_runtime_workspace,
            runtime_plan=runtime_plan,
            plan=plan,
            payload={
                "run_root": str(run_root),
                "snapshot": snapshot.model_dump(mode="json"),
                "prep_result": prep_result.model_dump(mode="json"),
                "bootstrap_result": bootstrap_result,
                "adapter_auth_result": adapter_auth_result,
                "widget_order_e2e_result": widget_order_e2e_result.model_dump(mode="json")
                if widget_order_e2e_result is not None
                else None,
                "onboarding_credentials": dict(onboarding_credentials or {}),
                "live_logs_root": str(live_logs_root) if live_logs_root is not None else None,
            },
        )
    except _RuntimeValidationSubprocessError as exc:
        fixture_manifest = dict(prep_result.fixture_manifest or {})
        fixture_manifest.update(dict(exc.diagnostics or {}))
        return ConversationValidationResult(
            passed=False,
            failure_summary=f"conversation validation failed: {exc}",
            failure_origin=exc.failure_origin,
            failure_code=exc.failure_code,
            fixture_manifest=fixture_manifest,
            related_files=_widget_order_related_files(plan),
        )
    except Exception as exc:
        return ConversationValidationResult(
            passed=False,
            failure_summary=f"conversation validation failed: {exc}",
            failure_origin="platform_validation",
            failure_code="runtime_validation_subprocess_failed",
            fixture_manifest=dict(prep_result.fixture_manifest or {}),
            related_files=_widget_order_related_files(plan),
        )
    for payload in list(envelope.get("events") or []):
        _emit_validation_event(event_callback, **dict(payload))
    result_payload = dict(envelope.get("result") or {})
    runtime_context = _pop_runtime_context_fields(result_payload)
    if runtime_context:
        fixture_manifest = dict(result_payload.get("fixture_manifest") or {})
        fixture_manifest.update(runtime_context)
        result_payload["fixture_manifest"] = fixture_manifest
    return ConversationValidationResult.model_validate(result_payload)


async def _run_unauthenticated_conversation_scenario(
    *,
    runtime_server_fastapi: Any,
    fixture_manifest: dict[str, Any],
    scenario: dict[str, Any],
    transcripts_dir: Path,
) -> tuple[ConversationScenarioResult, str]:
    conversation_id = f"conv-{uuid4().hex[:12]}"
    transcript_path = transcripts_dir / f"{scenario['scenario_id']}.json"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_server_fastapi.app),
        base_url="http://chatbot.validation",
    ) as client:
        response = await client.post(
            "/api/v1/chat/stream",
            json={
                "message": scenario["prompt"],
                "site_id": fixture_manifest.get("site_id"),
                "capability_profile": fixture_manifest.get("capability_profile"),
            },
        )
    deterministic_failures: list[str] = []
    if response.status_code != 401:
        deterministic_failures.append(f"expected 401, got {response.status_code}")
    transcript_payload = {
        "scenario_id": scenario["scenario_id"],
        "status_code": response.status_code,
        "body": response.text,
        "mode": scenario["mode"],
        "conversation_id": conversation_id,
    }
    transcript_text = json.dumps(transcript_payload, ensure_ascii=False, indent=2)
    transcript_path.write_text(transcript_text, encoding="utf-8")
    result = _finalize_conversation_scenario_result(
        scenario_id=scenario["scenario_id"],
        mode=scenario["mode"],
        prompt=scenario["prompt"],
        final_answer=response.text.strip(),
        transcript_path=str(transcript_path),
        trace_path=None,
        expected_tool_names=[],
        observed_tool_names=[],
        deterministic_failures=deterministic_failures,
        sampled_order_id=None,
        sampled_option_id=None,
        conversation_id=conversation_id,
    )
    return result, transcript_text


async def _run_authenticated_conversation_scenario(
    *,
    runtime_server_fastapi: Any,
    runtime_chat_endpoint: Any,
    fixture_manifest: dict[str, Any],
    scenario: dict[str, Any],
    previous_state: dict[str, Any] | None,
    transcripts_dir: Path,
) -> tuple[ConversationScenarioResult, str, str, dict[str, Any] | None]:
    conversation_id = str(
        (previous_state or {}).get("conversation_id")
        or scenario.get("conversation_id")
        or f"conv-{uuid4().hex[:12]}"
    )
    trace_logger = ConversationRunLogger(
        conversation_id=conversation_id,
        turn_id=f"validation-{scenario['scenario_id']}",
        user_id=_coerce_int(
            ((fixture_manifest.get("bootstrap_payload") or {}).get("user") or {}).get("id")
        ),
        provider=None,
        model=None,
        base_dir=str(transcripts_dir),
    )
    trace_logger.set_input(scenario["prompt"], previous_state or {})
    callback_handler = _ConversationTraceCallbackHandler(trace_logger)
    transcript_path = transcripts_dir / f"{scenario['scenario_id']}.json"

    with _patched_stream_callbacks(runtime_chat_endpoint, callback_handler):
        response = await _stream_chat_request(
            runtime_server_fastapi=runtime_server_fastapi,
            scenario=scenario,
            fixture_manifest=fixture_manifest,
            previous_state=previous_state,
            conversation_id=conversation_id,
        )

    final_state = response["metadata_state"]
    trace_path = trace_logger.finalize(
        final_state=final_state,
        success=response["status_code"] == 200 and not response["error_events"],
        error_message=None if response["status_code"] == 200 else f"chat status {response['status_code']}",
    )
    trace_text = _read_text_if_exists(Path(trace_path))
    observed_tool_names = _augment_observed_tool_names(
        response=response,
        observed_tool_names=_extract_observed_tool_names(trace_text),
    )
    scenario_contract = ConversationScenarioContract.model_validate(
        scenario.get("scenario_contract")
        or {
            "scenario_id": scenario["scenario_id"],
            "mode": scenario["mode"],
            "prompt": str(scenario.get("prompt") or ""),
            "expected_milestones": list(scenario.get("expected_milestones") or []),
            "allowed_paths": list(scenario.get("allowed_paths") or []),
            "sampled_order_id": _optional_text(scenario.get("sampled_order_id")),
            "sampled_option_id": _optional_text(scenario.get("sampled_option_id")),
            "previous_state_from": _optional_text(scenario.get("previous_state_from")),
        }
    )
    deterministic_failures, observed_milestones = (
        _evaluate_conversation_deterministic_failures_from_contract(
            scenario_contract=scenario_contract,
            response=response,
            observed_tool_names=observed_tool_names,
        )
    )
    transcript_payload = {
        "scenario_id": scenario["scenario_id"],
        "conversation_id": conversation_id,
        "mode": scenario["mode"],
        "prompt": scenario["prompt"],
        "status_code": response["status_code"],
        "response_text": response.get("response_text"),
        "raw_events": response["raw_events"],
        "final_answer": response["final_answer"],
        "metadata_state": response["metadata_state"],
        "ui_interrupts": response["ui_interrupts"],
        "tool_status_events": response["tool_status_events"],
        "observed_tool_names": observed_tool_names,
    }
    transcript_text = json.dumps(transcript_payload, ensure_ascii=False, indent=2)
    transcript_path.write_text(transcript_text, encoding="utf-8")
    result = _finalize_conversation_scenario_result(
        scenario_id=scenario["scenario_id"],
        mode=scenario["mode"],
        prompt=scenario["prompt"],
        final_answer=response["final_answer"],
        transcript_path=str(transcript_path),
        trace_path=trace_path,
        expected_tool_names=list(scenario.get("expected_tool_names") or []),
        observed_tool_names=observed_tool_names,
        expected_milestones=list(scenario_contract.expected_milestones),
        observed_milestones=observed_milestones,
        allowed_paths=list(scenario_contract.allowed_paths),
        deterministic_failures=deterministic_failures,
        sampled_order_id=_optional_text(scenario.get("sampled_order_id")),
        sampled_option_id=_optional_text(scenario.get("sampled_option_id")),
        conversation_id=conversation_id,
    )
    return result, transcript_text, trace_text, final_state


async def _stream_chat_request(
    *,
    runtime_server_fastapi: Any,
    scenario: dict[str, Any],
    fixture_manifest: dict[str, Any],
    previous_state: dict[str, Any] | None,
    conversation_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message": scenario["prompt"],
        "site_id": fixture_manifest.get("site_id"),
        "capability_profile": fixture_manifest.get("capability_profile"),
    }
    if fixture_manifest.get("access_token"):
        payload["access_token"] = fixture_manifest.get("access_token")
    if previous_state:
        payload["previous_state"] = previous_state
    if scenario.get("resume_payload"):
        payload["resume_payload"] = scenario["resume_payload"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_server_fastapi.app),
        base_url="http://chatbot.validation",
        cookies=fixture_manifest.get("session_cookies") or {},
        timeout=30.0,
    ) as client:
        async with client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
            raw_events, response_text = await _collect_sse_events(response)

    return _extract_stream_outcome(
        status_code=response.status_code,
        raw_events=raw_events,
        conversation_id=conversation_id,
        response_text=response_text,
    )


async def _collect_sse_events(response: httpx.Response) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    raw_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            continue
        raw_lines.append(line)
        if not line.startswith("data: "):
            continue
        try:
            events.append(json.loads(line[len("data: ") :]))
        except json.JSONDecodeError:
            events.append({"type": "unparsed", "raw": line[len("data: ") :]})
    return events, "\n".join(raw_lines)


def _extract_stream_outcome(
    *,
    status_code: int,
    raw_events: list[dict[str, Any]],
    conversation_id: str,
    response_text: str = "",
) -> dict[str, Any]:
    final_answer_parts: list[str] = []
    metadata_state: dict[str, Any] | None = None
    ui_interrupts: list[dict[str, Any]] = []
    tool_status_events: list[dict[str, Any]] = []
    error_events: list[dict[str, Any]] = []
    for event in raw_events:
        event_type = str(event.get("type") or "")
        if event_type == "text_chunk":
            final_answer_parts.append(str(event.get("content") or ""))
        elif event_type == "metadata":
            state = event.get("state")
            if isinstance(state, dict):
                metadata_state = state
        elif event_type == "ui_action":
            ui_interrupts.append(event)
        elif event_type == "tool_status":
            tool_status_events.append(event)
        elif event_type == "error":
            error_events.append(event)
    final_answer = "".join(final_answer_parts).strip()
    if not final_answer and ui_interrupts:
        final_answer = str(ui_interrupts[-1].get("message") or "").strip()
    if metadata_state is not None and "conversation_id" not in metadata_state:
        metadata_state["conversation_id"] = conversation_id
    return {
        "status_code": status_code,
        "raw_events": raw_events,
        "response_text": response_text,
        "final_answer": final_answer,
        "metadata_state": metadata_state,
        "ui_interrupts": ui_interrupts,
        "tool_status_events": tool_status_events,
        "error_events": error_events,
    }


def _build_runtime_fixture_manifest(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
    prep_result: BackendRuntimePrepResult,
    bootstrap_result: dict[str, Any],
    adapter_auth_result: dict[str, Any],
    onboarding_credentials: dict[str, str] | None,
) -> dict[str, Any]:
    manifest = dict(prep_result.fixture_manifest or {})
    module_origins: dict[str, str] = {}
    auth = dict(manifest.get("auth") or {})
    seed_source = dict(manifest.get("seed_source") or {})
    credentials = {
        "email": "test1@example.com",
        "password": "password123",
    }
    credentials.update({key: value for key, value in (onboarding_credentials or {}).items() if value})
    auth.setdefault("email", credentials.get("email"))
    auth.setdefault("password", credentials.get("password"))
    manifest["auth"] = auth
    manifest["site_id"] = plan.chatbot_bridge.site_key
    manifest["capability_profile"] = str(plan.host_frontend.capability_profile or "order_cs_only")
    manifest["enabled_retrieval_corpora"] = list(plan.host_frontend.enabled_retrieval_corpora or [])
    manifest["widget_features"] = dict(plan.host_frontend.widget_features or {})
    auth_material, auth_failure = _resolve_bridge_auth_material(
        bootstrap_result=bootstrap_result,
        plan=plan,
    )
    manifest["auth_transport"] = _normalized_auth_transport(plan.chatbot_bridge.auth_contract.transport)
    manifest["access_token"] = str((auth_material or {}).get("access_token") or "")
    manifest["bootstrap_payload"] = dict(bootstrap_result.get("bootstrap_payload") or {})
    manifest["session_cookies"] = dict((auth_material or {}).get("cookies") or {})
    manifest["auth_metadata"] = dict((auth_material or {}).get("metadata") or {})
    if auth_failure:
        manifest["available"] = False
        manifest["reason"] = auth_failure
        manifest["error_summary"] = auth_failure
        manifest["failure_origin"] = "host_contract"
        manifest["failure_code"] = "bridge_auth_material_missing"
        manifest["validation_capability_contract"] = build_validation_capability_contract(
            plan=plan,
            fixture_manifest=manifest,
        ).model_dump(mode="json")
        manifest["orders"] = dict(manifest.get("orders") or {})
        manifest["seed_source"] = seed_source
        return manifest

    try:
        _, _, adapter_setup, _, module_origins = _load_runtime_validation_modules(
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        )
    except Exception as exc:
        error_summary = str(exc)
        manifest["available"] = False
        manifest["reason"] = "runtime fixture bootstrap failed"
        manifest["error_summary"] = error_summary
        manifest["failure_origin"] = "platform_validation"
        manifest["failure_code"] = _platform_validation_failure_code(exc)
        manifest["orders"] = dict(manifest.get("orders") or {})
        manifest["seed_source"] = seed_source
        if module_origins:
            manifest["module_origins"] = module_origins
        manifest["validation_capability_contract"] = build_validation_capability_contract(
            plan=plan,
            fixture_manifest=manifest,
        ).model_dump(mode="json")
        return manifest
    try:
        adapter = adapter_setup.resolve_site_adapter(plan.chatbot_bridge.site_key)
    except Exception as exc:
        error_summary = str(exc)
        manifest["available"] = False
        manifest["reason"] = "runtime adapter registry resolution failed"
        manifest["error_summary"] = error_summary
        manifest["failure_origin"] = "generated_runtime"
        manifest["failure_code"] = "runtime_registry_resolution_failed"
        manifest["orders"] = dict(manifest.get("orders") or {})
        manifest["seed_source"] = seed_source
        manifest["module_origins"] = module_origins
        manifest["validation_capability_contract"] = build_validation_capability_contract(
            plan=plan,
            fixture_manifest=manifest,
        ).model_dump(mode="json")
        return manifest
    try:
        response_contract = getattr(adapter, "response_contract", None) or plan.chatbot_bridge.response_contract
        auth_context = _auth_context_from_material(
            auth_material=auth_material or {},
            site_id=plan.chatbot_bridge.site_key,
            user_id=str(((adapter_auth_result.get("validated_user") or {}).get("id")) or "__bridge__"),
        )
        headers = _build_generated_auth_headers(adapter=adapter, auth_context=auth_context)
        raw_orders = asyncio.run(adapter.client.list_orders(headers))
        order_candidates = _extract_order_candidates(raw_orders)
        if not order_candidates and manifest.get("deferred_seed_strategy") == "runtime_order_probe":
            seed_path_text = str(
                (seed_source.get("seed_path") or prep_result.seed_source_path or "")
            ).strip()
            if seed_path_text:
                seed_result = _run_optional_script(
                    name="seed",
                    script_path=Path(seed_path_text),
                    framework=runtime_plan.framework,
                    backend_root=Path(
                        str(prep_result.backend_root or runtime_plan.backend_root)
                    ).resolve(),
                    python_executable=Path(
                        str(prep_result.python_executable or sys.executable)
                    ).resolve(),
                    env=build_backend_subprocess_env(
                        backend_root=Path(
                            str(prep_result.backend_root or runtime_plan.backend_root)
                        ).resolve()
                    ),
                    missing_stdout="seed script not found; skipped seed",
                )
                seed_source["runtime_seeded"] = bool(seed_result.passed)
                if seed_result.stdout:
                    seed_source["runtime_seed_stdout"] = seed_result.stdout
                if seed_result.stderr:
                    seed_source["runtime_seed_stderr"] = seed_result.stderr
                if seed_result.log_path:
                    seed_source["runtime_seed_log_path"] = seed_result.log_path
                manifest["seed_source"] = seed_source
                if not seed_result.passed:
                    manifest["available"] = False
                    manifest["reason"] = "runtime fixtures unavailable: seed script failed"
                    manifest["error_summary"] = (
                        str(seed_result.stderr or seed_result.stdout or "seed failed").strip()
                    )
                    manifest["failure_origin"] = "upstream_fixture"
                    manifest["failure_code"] = "fixture_seed_failed"
                    manifest["orders"] = dict(manifest.get("orders") or {})
                    manifest["module_origins"] = module_origins
                    manifest["validation_capability_contract"] = build_validation_capability_contract(
                        plan=plan,
                        fixture_manifest=manifest,
                    ).model_dump(mode="json")
                    return manifest
                raw_orders = asyncio.run(adapter.client.list_orders(headers))
                order_candidates = _extract_order_candidates(raw_orders)
        order_ids = [
            order_id
            for order_id in (
                resolve_visible_order_id_from_contract(response_contract, item)
                for item in order_candidates
                if isinstance(item, dict)
            )
            if order_id
        ]
        option_ids = [option_id for option_id in (_extract_option_id(item) for item in order_candidates) if option_id]
        if order_ids:
            manifest["available"] = True
            manifest["orders"] = {
                "lookup_order_id": str(order_ids[0]),
                "status_order_id": str(order_ids[1] if len(order_ids) > 1 else order_ids[0]),
                "cancel_order_id": str(order_ids[2] if len(order_ids) > 2 else order_ids[0]),
                "refund_order_id": str(order_ids[3] if len(order_ids) > 3 else order_ids[0]),
                "exchange_order_id": str(order_ids[4] if len(order_ids) > 4 else order_ids[0]),
                "exchange_new_option_id": str(option_ids[0] if option_ids else "synthetic-option-1"),
            }
            manifest.pop("reason", None)
            manifest.pop("error_summary", None)
            manifest.pop("failure_origin", None)
            manifest.pop("failure_code", None)
        else:
            manifest["available"] = False
            manifest["reason"] = "runtime fixtures unavailable: no orders returned"
            manifest["failure_origin"] = "upstream_fixture"
            manifest["failure_code"] = "fixture_orders_missing"
            manifest["error_summary"] = "adapter.client.list_orders returned no usable orders"
            manifest["orders"] = dict(manifest.get("orders") or {})
        manifest["seed_source"] = seed_source
        manifest["module_origins"] = module_origins
        manifest["validation_capability_contract"] = build_validation_capability_contract(
            plan=plan,
            fixture_manifest=manifest,
        ).model_dump(mode="json")
    except Exception as exc:
        error_summary = str(exc)
        manifest["available"] = False
        manifest["reason"] = "runtime fixtures unavailable: upstream order seed failed"
        manifest["error_summary"] = error_summary
        manifest["failure_origin"] = "upstream_fixture"
        manifest["failure_code"] = "fixture_upstream_list_orders_failed"
        manifest["orders"] = dict(manifest.get("orders") or {})
        manifest["seed_source"] = seed_source
        if module_origins:
            manifest["module_origins"] = module_origins
        manifest["validation_capability_contract"] = build_validation_capability_contract(
            plan=plan,
            fixture_manifest=manifest,
        ).model_dump(mode="json")
    return manifest


def _build_conversation_scenarios(
    *,
    fixture_manifest: dict[str, Any],
    capability_contract: ValidationCapabilityContract | None = None,
) -> list[dict[str, Any]]:
    return _build_conversation_scenarios_from_contract(
        fixture_manifest=fixture_manifest,
        capability_contract=capability_contract,
    )


def _evaluate_conversation_deterministic_failures(
    *,
    scenario: dict[str, Any],
    response: dict[str, Any],
    observed_tool_names: list[str],
) -> list[str]:
    scenario_contract = ConversationScenarioContract.model_validate(
        scenario.get("scenario_contract")
        or {
            "scenario_id": scenario["scenario_id"],
            "mode": scenario["mode"],
            "prompt": str(scenario.get("prompt") or ""),
            "expected_milestones": list(scenario.get("expected_milestones") or []),
            "allowed_paths": list(scenario.get("allowed_paths") or []),
            "sampled_order_id": _optional_text(scenario.get("sampled_order_id")),
            "sampled_option_id": _optional_text(scenario.get("sampled_option_id")),
            "previous_state_from": _optional_text(scenario.get("previous_state_from")),
        }
    )
    failures, _ = _evaluate_conversation_deterministic_failures_from_contract(
        scenario_contract=scenario_contract,
        response=response,
        observed_tool_names=observed_tool_names,
    )
    return failures


def _classify_conversation_failure(deterministic_failures: list[str]) -> str | None:
    return _classify_conversation_failure_from_contract(deterministic_failures)


def _finalize_conversation_scenario_result(
    *,
    scenario_id: str,
    mode: str,
    prompt: str,
    final_answer: str,
    transcript_path: str | None,
    trace_path: str | None,
    expected_tool_names: list[str],
    observed_tool_names: list[str],
    deterministic_failures: list[str],
    sampled_order_id: str | None,
    sampled_option_id: str | None,
    expected_milestones: list[str] | None = None,
    observed_milestones: list[str] | None = None,
    allowed_paths: list[list[str]] | None = None,
    conversation_id: str | None = None,
) -> ConversationScenarioResult:
    deterministic_passed = not deterministic_failures
    llm_judgement: dict[str, Any] = {}
    llm_passed: bool | None = None
    final_verdict = "fail"
    failure_category = _classify_conversation_failure(deterministic_failures)
    if deterministic_passed:
        llm_judgement = _run_conversation_llm_judge(
            prompt=prompt,
            final_answer=final_answer,
            expected_tool_names=expected_tool_names,
            observed_tool_names=observed_tool_names,
            transcript_path=transcript_path,
            trace_path=trace_path,
        )
        llm_passed = bool(llm_judgement.get("overall_pass"))
        final_verdict = "pass" if llm_passed else "advisory_fail"
    return ConversationScenarioResult(
        scenario_id=scenario_id,
        mode=mode,
        conversation_id=str(conversation_id or f"conv-{uuid4().hex[:12]}"),
        deterministic_passed=deterministic_passed,
        llm_passed=llm_passed,
        final_verdict=final_verdict,
        failure_category=failure_category,
        transcript_path=transcript_path,
        trace_path=trace_path,
        sampled_or_fixture_order_id=sampled_order_id,
        sampled_or_fixture_option_id=sampled_option_id,
        deterministic_failures=list(deterministic_failures),
        expected_tool_names=list(expected_tool_names),
        observed_tool_names=list(observed_tool_names),
        expected_milestones=list(expected_milestones or []),
        observed_milestones=list(observed_milestones or []),
        allowed_paths=list(allowed_paths or []),
        llm_judgement=llm_judgement,
    )


def _run_conversation_llm_judge(
    *,
    prompt: str,
    final_answer: str,
    expected_tool_names: list[str],
    observed_tool_names: list[str],
    transcript_path: str | None,
    trace_path: str | None,
) -> dict[str, Any]:
    if os.getenv("ONBOARDING_V2_ENABLE_LLM", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "task_completion": "skipped",
            "factual_alignment": "skipped",
            "safety": "skipped",
            "unsupported_behavior": "skipped",
            "overall_pass": True,
            "rationale": "llm judge skipped because onboarding_v2 llm is disabled",
        }
    response = invoke_structured_stage(
        stage="validation",
        phase="conversation-judge",
        provider="openai",
        model=os.getenv("ONBOARDING_V2_VALIDATION_JUDGE_MODEL", "gpt-5.2"),
        system_prompt=(
            "You are judging a chatbot runtime validation scenario. "
            "Return strict JSON with task_completion, factual_alignment, safety, "
            "unsupported_behavior, overall_pass, rationale. Fail when the answer "
            "is evasive, hallucinates actions, or mismatches the observed tools."
        ),
        payload={
            "prompt": prompt,
            "final_answer": final_answer,
            "expected_tool_names": expected_tool_names,
            "observed_tool_names": observed_tool_names,
            "transcript_path": transcript_path,
            "trace_path": trace_path,
        },
        response_model=_ConversationLlmJudgeResponse,
        fallback_payload={
            "task_completion": "judge_unavailable",
            "factual_alignment": "judge_unavailable",
            "safety": "judge_unavailable",
            "unsupported_behavior": "judge_unavailable",
            "overall_pass": True,
            "rationale": "llm judge fallback applied",
        },
    )
    return response.model_dump(mode="json")


def _collect_widget_order_flow_report(
    *,
    adapter: Any,
    auth_context: AuthenticatedContext,
    plan: IntegrationPlan,
    sample_context: dict[str, Any],
    server_fastapi: Any,
    chat_endpoint: Any,
) -> dict[str, dict[str, Any]]:
    status_input = importlib.import_module("src.adapters.schema").GetOrderStatusInput(
        orderId=str(sample_context["sampled_order_id"])
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

    with _patched_runtime_adapter_resolution(chat_endpoint=chat_endpoint, adapter=adapter):
        client = TestClient(server_fastapi.app)
        flow_reports["list_orders"] = _exercise_widget_order_flow(
            client=client,
            server_fastapi=server_fastapi,
            site_id=plan.chatbot_bridge.site_key,
            access_token=str(auth_context.accessToken or ""),
            session_cookies=dict(auth_context.cookies or {}),
            conversation_id="conv-widget-list-orders",
            message="request_list_orders",
            step_specs=[
                _widget_step(
                    "show_order_list",
                    "request_list_orders",
                    ui_data=[dict(sample_context["sampled_order_ui_item"])],
                    requires_selection=True,
                )
            ],
            resume_payloads=[],
        )
        flow_reports["cancel"] = _exercise_widget_order_flow(
            client=client,
            server_fastapi=server_fastapi,
            site_id=plan.chatbot_bridge.site_key,
            access_token=str(auth_context.accessToken or ""),
            session_cookies=dict(auth_context.cookies or {}),
            conversation_id="conv-widget-cancel",
            message="request_cancel_order",
            step_specs=[
                _widget_step(
                    "show_order_list",
                    "request_cancel_order",
                    ui_data=[dict(sample_context["sampled_order_ui_item"])],
                    requires_selection=True,
                    prior_action="cancel",
                ),
                _widget_step(
                    "confirm_order_action",
                    "confirm_cancel_order",
                    action="cancel",
                    order_id=str(sample_context["sampled_order_id"]),
                ),
            ],
            resume_payloads=[{"selected_order_ids": [str(sample_context["sampled_order_id"])]}],
        )
        flow_reports["refund"] = _exercise_widget_order_flow(
            client=client,
            server_fastapi=server_fastapi,
            site_id=plan.chatbot_bridge.site_key,
            access_token=str(auth_context.accessToken or ""),
            session_cookies=dict(auth_context.cookies or {}),
            conversation_id="conv-widget-refund",
            message="request_refund_order",
            step_specs=[
                _widget_step(
                    "show_order_list",
                    "request_refund_order",
                    ui_data=[dict(sample_context["sampled_order_ui_item"])],
                    requires_selection=True,
                    prior_action="refund",
                ),
                _widget_step(
                    "confirm_order_action",
                    "confirm_refund_order",
                    action="refund",
                    order_id=str(sample_context["sampled_order_id"]),
                ),
            ],
            resume_payloads=[{"selected_order_ids": [str(sample_context["sampled_order_id"])]}],
        )
        flow_reports["exchange"] = _exercise_widget_order_flow(
            client=client,
            server_fastapi=server_fastapi,
            site_id=plan.chatbot_bridge.site_key,
            access_token=str(auth_context.accessToken or ""),
            session_cookies=dict(auth_context.cookies or {}),
            conversation_id="conv-widget-exchange",
            message="request_exchange_order",
            step_specs=[
                _widget_step(
                    "show_order_list",
                    "request_exchange_order",
                    ui_data=[dict(sample_context["sampled_order_ui_item"])],
                    requires_selection=True,
                    prior_action="exchange",
                ),
                _widget_step(
                    "show_option_list",
                    "request_exchange_option",
                    action="select_option",
                    ui_data=_sample_option_items(str(sample_context["sampled_option_id"])),
                    prior_action="exchange",
                ),
                _widget_step(
                    "confirm_order_action",
                    "confirm_exchange_order",
                    action="exchange",
                    order_id=str(sample_context["sampled_order_id"]),
                    new_option_id=str(sample_context["sampled_option_id"]),
                ),
            ],
            resume_payloads=[
                {"selected_order_ids": [str(sample_context["sampled_order_id"])]},
                {"new_option_id": str(sample_context["sampled_option_id"])},
            ],
        )
    return flow_reports


def _evaluate_widget_order_flow_report(
    *,
    plan: IntegrationPlan,
    flow_reports: dict[str, dict[str, Any]],
    capability_contract: ValidationCapabilityContract | None = None,
    sample_context: dict[str, Any] | None = None,
) -> WidgetOrderE2EResult:
    sample_context = dict(sample_context or {})
    capability_contract = capability_contract or build_validation_capability_contract(
        plan=plan,
        fixture_manifest={
            "enabled_retrieval_corpora": list(plan.host_frontend.enabled_retrieval_corpora or []),
            "widget_features": dict(plan.host_frontend.widget_features or {}),
        },
        sample_context=sample_context,
    )
    required_step_flows = [("list_orders", ["show_order_list"])]
    if "cancel" in capability_contract.available_actions:
        cancel_steps = ["confirm_order_action"]
        if capability_contract.requires_order_selection_for_actions:
            cancel_steps.insert(0, "show_order_list")
        required_step_flows.append(("cancel", cancel_steps))
    if "refund" in capability_contract.available_actions:
        refund_steps = ["confirm_order_action"]
        if capability_contract.requires_order_selection_for_actions:
            refund_steps.insert(0, "show_order_list")
        required_step_flows.append(("refund", refund_steps))
    if "exchange" in capability_contract.available_actions:
        exchange_steps = ["confirm_order_action"]
        if capability_contract.requires_option_selection_for_exchange:
            exchange_steps.insert(0, "show_option_list")
        if capability_contract.requires_order_selection_for_actions:
            exchange_steps.insert(0, "show_order_list")
        required_step_flows.append(("exchange", exchange_steps))
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
                validation_capability_contract=capability_contract.model_dump(mode="json"),
                sampled_order_id=_optional_text(sample_context.get("sampled_order_id")),
                sampled_option_id=_optional_text(sample_context.get("sampled_option_id")),
                scenario_mode=_optional_text(sample_context.get("scenario_mode")),
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
            validation_capability_contract=capability_contract.model_dump(mode="json"),
            sampled_order_id=_optional_text(sample_context.get("sampled_order_id")),
            sampled_option_id=_optional_text(sample_context.get("sampled_option_id")),
            scenario_mode=_optional_text(sample_context.get("scenario_mode")),
            related_files=_widget_order_related_files(plan),
        )
    covered_flows.insert(1, "get_order_status")

    return WidgetOrderE2EResult(
        passed=True,
        failure_summary="widget order e2e passed",
        covered_flows=covered_flows,
        flow_reports=flow_reports,
        validation_capability_contract=capability_contract.model_dump(mode="json"),
        sampled_order_id=_optional_text(sample_context.get("sampled_order_id")),
        sampled_option_id=_optional_text(sample_context.get("sampled_option_id")),
        scenario_mode=_optional_text(sample_context.get("scenario_mode")),
        related_files=_widget_order_related_files(plan),
    )


def _acquire_widget_order_sample(
    *,
    adapter: Any,
    auth_context: AuthenticatedContext,
    plan: IntegrationPlan,
) -> dict[str, Any]:
    list_orders = getattr(getattr(adapter, "client", None), "list_orders", None)
    if not callable(list_orders):
        raise RuntimeError("generated adapter client missing list_orders")
    headers = _build_generated_auth_headers(adapter=adapter, auth_context=auth_context)
    raw_orders = asyncio.run(list_orders(headers))
    order_candidates = _extract_order_candidates(raw_orders)
    if not order_candidates:
        raise RuntimeError("generated adapter list_orders returned no orders")
    raw_order = order_candidates[0]
    response_contract = getattr(adapter, "response_contract", None) or plan.chatbot_bridge.response_contract
    sampled_order_id = resolve_visible_order_id_from_contract(response_contract, raw_order)
    if not sampled_order_id:
        raise RuntimeError("generated adapter list_orders did not provide an order id")

    status_input = importlib.import_module("src.adapters.schema").GetOrderStatusInput(
        orderId=str(sampled_order_id)
    )
    order_status = asyncio.run(adapter.get_order_status(auth_context, status_input))

    sampled_option_id = _extract_option_id(raw_order)
    scenario_mode = "sampled_order_with_sampled_option"
    if not sampled_option_id:
        sampled_option_id = "synthetic-option-1"
        scenario_mode = "sampled_order_with_synthetic_option"

    return {
        "sampled_order_id": str(sampled_order_id),
        "sampled_option_id": str(sampled_option_id),
        "sampled_order_ui_item": _build_sample_order_ui_item(order_status),
        "scenario_mode": scenario_mode,
    }


def _build_generated_auth_headers(
    *,
    adapter: Any,
    auth_context: AuthenticatedContext,
) -> dict[str, str]:
    adapter_module = str(adapter.__class__.__module__)
    auth_module = importlib.import_module(adapter_module.rsplit(".", 1)[0] + ".auth")
    return auth_module.build_generated_auth_headers(auth_context)


def _extract_order_candidates(raw_orders: Any) -> list[dict[str, Any]]:
    if isinstance(raw_orders, list):
        return [item for item in raw_orders if isinstance(item, dict)]
    if isinstance(raw_orders, dict):
        for key in ("orders", "items", "results", "data"):
            value = raw_orders.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if any(key in raw_orders for key in ("id", "order_id", "orderId")):
            return [raw_orders]
    return []


def _extract_order_id(raw_order: dict[str, Any]) -> str | None:
    for key in ("order_id", "orderId", "id"):
        value = raw_order.get(key)
        if value not in (None, ""):
            return str(value)
    nested_order = raw_order.get("order")
    if isinstance(nested_order, dict):
        return _extract_order_id(nested_order)
    return None


def _extract_option_id(raw_order: dict[str, Any]) -> str | None:
    candidates = [
        raw_order.get("option_id"),
        raw_order.get("optionId"),
        raw_order.get("selected_option_id"),
        raw_order.get("selectedOptionId"),
        raw_order.get("variant_id"),
        raw_order.get("variantId"),
    ]
    product = raw_order.get("product")
    if isinstance(product, dict):
        candidates.extend(
            [
                product.get("option_id"),
                product.get("optionId"),
                product.get("variant_id"),
                product.get("variantId"),
            ]
        )
    option = raw_order.get("option")
    if isinstance(option, dict):
        candidates.extend([option.get("id"), option.get("option_id")])
    for value in candidates:
        if value not in (None, ""):
            return str(value)
    return None


def _build_sample_order_ui_item(order_status: Any) -> dict[str, Any]:
    order = getattr(order_status, "order", None)
    items = list(getattr(order, "items", None) or [])
    first_item = items[0] if items else None
    total_price = getattr(getattr(order, "totalPrice", None), "amount", None)
    status = getattr(getattr(order, "status", None), "value", None) or getattr(order, "status", None)
    return {
        "order_id": str(getattr(order, "orderId", "") or ""),
        "date": str(getattr(order, "orderedAt", "") or ""),
        "status": str(status or ""),
        "product_name": str(getattr(first_item, "productTitle", "") or ""),
        "amount": total_price,
    }


def _sample_option_items(selected_option_id: str) -> list[dict[str, Any]]:
    secondary_option_id = (
        f"{selected_option_id}-alt" if selected_option_id != "synthetic-option-1" else "synthetic-option-2"
    )
    return [
        _sample_option_item(str(selected_option_id)),
        _sample_option_item(str(secondary_option_id)),
    ]


def _exercise_widget_order_flow(
    *,
    client: Any,
    server_fastapi: Any,
    site_id: str,
    access_token: str,
    session_cookies: dict[str, str] | None,
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
                "message": message if index == 0 else "resume_interrupt",
                "site_id": site_id,
            }
            if access_token:
                request_payload["access_token"] = access_token
            if index > 0:
                request_payload["previous_state"] = {
                    "conversation_id": conversation_id,
                    "pending_interrupt": pending_interrupt,
                }
                request_payload["resume_payload"] = resume_payloads[index - 1]
            response = client.post(
                "/api/v1/chat/stream",
                json=request_payload,
                cookies=session_cookies or None,
            )
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


def _sample_option_item(option_id: str) -> dict[str, Any]:
    return {
        "option_id": option_id,
        "label": f"option-{option_id}",
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


def _skipped_runtime_state(
    *,
    framework: str,
    reason: str,
    upstream: Any | None = None,
) -> BackendRuntimeState:
    failure_origin, failure_code = _failure_metadata_from_context(upstream)
    return BackendRuntimeState(
        framework=framework,
        passed=False,
        failure_summary=reason,
        failure_origin=failure_origin,
        failure_code=failure_code,
        related_files=["backend/manage.py", "backend/chat_auth.py"]
        if framework == "django"
        else ["chat_auth.py"],
    )


def _pop_runtime_context_fields(payload: dict[str, Any]) -> dict[str, Any]:
    runtime_context: dict[str, Any] = {}
    for key in (
        "resolved_chatbot_runtime_workspace",
        "runtime_harness_path",
        "runtime_harness_origin",
    ):
        value = payload.pop(key, None)
        if value is not None:
            runtime_context[key] = value
    return runtime_context


def _coerce_widget_order_e2e_result(
    value: WidgetOrderE2EResult | dict[str, Any],
) -> WidgetOrderE2EResult:
    if isinstance(value, WidgetOrderE2EResult):
        return value
    payload = dict(value or {})
    runtime_context = _pop_runtime_context_fields(payload)
    flow_reports = dict(payload.get("flow_reports") or {})
    legacy_module_origins = flow_reports.pop("module_origins", None)
    payload.setdefault("covered_flows", [])
    payload["flow_reports"] = flow_reports
    if runtime_context:
        payload.update(runtime_context)
    if isinstance(legacy_module_origins, dict) and "module_origins" not in payload:
        payload["module_origins"] = {
            str(key): str(item) for key, item in legacy_module_origins.items()
        }
    payload.setdefault("module_origins", {})
    payload.setdefault("related_files", [])
    payload.setdefault("failure_summary", "widget order e2e failed")
    payload.setdefault("passed", False)
    return WidgetOrderE2EResult.model_validate(payload)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _callback_name(serialized: Any, *, fallback: str) -> str:
    if isinstance(serialized, dict):
        for key in ("name", "id"):
            value = serialized.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(serialized, str) and serialized.strip():
        return serialized.strip()
    return fallback


def _extract_observed_tool_names(trace_text: str) -> list[str]:
    observed: list[str] = []
    for line in trace_text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        timeline = payload.get("timeline") or {}
        for item in list(timeline.get("tools") or []):
            if item.get("event") != "start":
                continue
            tool_name = _optional_text(item.get("tool"))
            if tool_name and tool_name not in observed:
                observed.append(tool_name)
    return observed


def _augment_observed_tool_names(
    *,
    response: dict[str, Any],
    observed_tool_names: list[str],
) -> list[str]:
    observed = list(observed_tool_names)
    metadata_state = response.get("metadata_state") or {}
    order_context = metadata_state.get("order_context") or {}
    fallback_tool_name = _optional_text(order_context.get("last_tool"))
    if fallback_tool_name:
        normalized_tool_name = {
            "get_user_orders": "list_orders",
        }.get(fallback_tool_name, fallback_tool_name)
        if normalized_tool_name not in observed:
            observed.append(normalized_tool_name)
    return observed


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _evaluate_bootstrap_contract(
    *,
    bootstrap_status: int | None,
    payload: dict[str, Any],
) -> tuple[bool, str]:
    if bootstrap_status != 200:
        return False, f"host auth bootstrap failed with status {bootstrap_status}"
    if not bool(payload.get("authenticated")):
        return False, "host auth bootstrap missing authenticated=true"
    if not str(payload.get("site_id") or "").strip():
        return False, "host auth bootstrap missing site_id"
    if not str(payload.get("access_token") or "").strip():
        return False, "host auth bootstrap missing access_token"
    if not str((payload.get("user") or {}).get("id") or "").strip():
        return False, "host auth bootstrap missing user.id"
    return True, "host auth bootstrap passed"


def _truncate_text(value: str, *, limit: int = 1000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def _stable_paths(values: list[str | None]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = str(value or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def _client_cookies_dict(client: Any) -> dict[str, str]:
    cookies = getattr(client, "cookies", None)
    if cookies is None:
        return {}
    try:
        return dict(cookies)
    except Exception:
        return {}


def _chatbot_runtime_env_overrides(
    *,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
) -> dict[str, str]:
    env_var = str(plan.chatbot_bridge.host_base_url_env_var or "").strip()
    if not env_var:
        return {}
    return {
        env_var: _runtime_base_url(
            runtime_plan,
            chat_auth_contract_path=plan.host_backend.chat_auth_contract_path,
        )
    }


def _normalized_auth_transport(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized == "session_token_cookie":
        return "session_cookie"
    return normalized or "session_cookie"


def _resolve_bridge_auth_material(
    *,
    bootstrap_result: dict[str, Any],
    plan: IntegrationPlan,
) -> tuple[dict[str, Any] | None, str | None]:
    payload = dict(bootstrap_result.get("bootstrap_payload") or {})
    cookies = dict(bootstrap_result.get("session_cookies") or {})
    auth_contract = plan.chatbot_bridge.auth_contract
    transport = _normalized_auth_transport(auth_contract.transport)
    access_token = str(payload.get("access_token") or "").strip()
    session_cookie_name = str(auth_contract.session_cookie_name or "").strip()
    csrf_cookie_name = str(auth_contract.csrf_cookie_name or "").strip()
    csrf_header_name = str(auth_contract.csrf_header_name or "").strip()

    if (
        transport == "session_cookie"
        and not session_cookie_name
        and access_token
        and not cookies
    ):
        transport = "bearer_token"

    if transport == "bearer_token":
        if not access_token:
            return None, "missing bearer access_token for bridge auth"
        return {
            "auth_transport": transport,
            "access_token": access_token,
            "cookies": cookies,
            "metadata": {},
        }, None

    if not session_cookie_name:
        return None, "missing session_cookie_name in bridge auth contract"
    session_cookie_value = str(cookies.get(session_cookie_name) or "").strip()
    if not session_cookie_value:
        return None, f"missing session cookie {session_cookie_name} for bridge auth"

    metadata: dict[str, Any] = {}
    if transport == "cookie_plus_csrf":
        if not csrf_cookie_name or not csrf_header_name:
            return None, "missing csrf contract fields for bridge auth"
        csrf_token = str(
            payload.get("csrf_token")
            or cookies.get(csrf_cookie_name)
            or ""
        ).strip()
        if not csrf_token:
            return None, f"missing csrf token {csrf_cookie_name} for bridge auth"
        metadata["csrf_token"] = csrf_token
        metadata["csrf_header_name"] = csrf_header_name

    return {
        "auth_transport": transport,
        "access_token": "",
        "cookies": cookies,
        "metadata": metadata,
    }, None


def _auth_context_from_material(
    *,
    auth_material: dict[str, Any],
    site_id: str,
    user_id: str,
) -> AuthenticatedContext:
    return AuthenticatedContext(
        siteId=site_id,
        userId=str(user_id or "__bridge__"),
        accessToken=str(auth_material.get("access_token") or "") or None,
        cookies=dict(auth_material.get("cookies") or {}) or None,
        metadata=dict(auth_material.get("metadata") or {}) or None,
    )


def _build_bridge_auth_context(
    *,
    bootstrap_result: dict[str, Any],
    plan: IntegrationPlan,
    user_id: str,
) -> tuple[AuthenticatedContext | None, str | None]:
    auth_material, failure_summary = _resolve_bridge_auth_material(
        bootstrap_result=bootstrap_result,
        plan=plan,
    )
    if auth_material is None:
        return None, failure_summary
    return _auth_context_from_material(
        auth_material=auth_material,
        site_id=plan.chatbot_bridge.site_key,
        user_id=user_id,
    ), None


@contextmanager
def _patched_chatbot_runtime_env(
    *,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
):
    overrides = _chatbot_runtime_env_overrides(runtime_plan=runtime_plan, plan=plan)
    if not overrides:
        yield {}
        return
    with patch.dict(os.environ, overrides, clear=False):
        yield overrides


def _resolve_runtime_validation_harness_path(*, chatbot_runtime_workspace: Path) -> Path:
    chatbot_runtime_workspace = chatbot_runtime_workspace.resolve()
    workspace_harness = (
        chatbot_runtime_workspace
        / "src"
        / "onboarding_v2"
        / "validation"
        / "runtime_harness.py"
    )
    if workspace_harness.exists():
        return workspace_harness.resolve()
    return Path(__file__).resolve().with_name("runtime_harness.py")


def _run_runtime_validation_subprocess(
    *,
    action: str,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
    payload: dict[str, Any],
) -> dict[str, Any]:
    chatbot_runtime_workspace = chatbot_runtime_workspace.resolve()
    harness_path = _resolve_runtime_validation_harness_path(
        chatbot_runtime_workspace=chatbot_runtime_workspace,
    )
    runtime_context = _runtime_context_payload(
        chatbot_runtime_workspace=chatbot_runtime_workspace,
        harness_path=harness_path,
    )
    payload_path = Path("/tmp") / f"runtime-validation-{uuid4().hex}.json"
    payload_path.write_text(
        json.dumps(
            {
                "action": action,
                "chatbot_runtime_workspace": str(chatbot_runtime_workspace),
                "runtime_plan": runtime_plan.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
                "payload": payload,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(chatbot_runtime_workspace)
    env.update(_chatbot_runtime_env_overrides(runtime_plan=runtime_plan, plan=plan))
    command = [sys.executable, str(harness_path), "--payload", str(payload_path)]
    try:
        result = subprocess.run(
            command,
            cwd=str(chatbot_runtime_workspace),
            env=env,
            capture_output=True,
            text=True,
        )
    finally:
        payload_path.unlink(missing_ok=True)
    marker = "__RUNTIME_VALIDATION_JSON__"
    envelope: dict[str, Any] | None = None
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(marker):
            envelope = json.loads(line[len(marker) :])
            break
    if result.returncode != 0:
        failure = (
            envelope.get("error") if envelope else result.stderr.strip() or result.stdout.strip()
        )
        traceback_text = (
            str(envelope.get("traceback") or "").strip() if isinstance(envelope, dict) else ""
        )
        message = failure or f"runtime validation subprocess failed: exit {result.returncode}"
        if traceback_text:
            message = f"{message}\n{traceback_text}"
        raise _RuntimeValidationSubprocessError(
            message,
            failure_origin="platform_validation",
            failure_code=_subprocess_failure_code(message),
            diagnostics=runtime_context,
        )
    if envelope is None:
        message = "runtime validation subprocess returned no structured result"
        raise _RuntimeValidationSubprocessError(
            message,
            failure_origin="platform_validation",
            failure_code=_subprocess_failure_code(message),
            diagnostics=runtime_context,
        )
    if not envelope.get("ok", False):
        message = str(envelope.get("error") or "runtime validation subprocess failed")
        traceback_text = str(envelope.get("traceback") or "").strip()
        if traceback_text:
            message = f"{message}\n{traceback_text}"
        raise _RuntimeValidationSubprocessError(
            message,
            failure_origin="platform_validation",
            failure_code=_subprocess_failure_code(message),
            diagnostics=runtime_context,
        )
    result_payload = envelope.get("result")
    if isinstance(result_payload, dict):
        for key, value in runtime_context.items():
            result_payload.setdefault(key, value)
    return envelope


def _runtime_module_origin(module: Any) -> str:
    origin = getattr(module, "__file__", None)
    return str(Path(origin).resolve()) if origin else "<unknown>"


def _assert_runtime_module_origin(
    *,
    label: str,
    module: Any,
    chatbot_runtime_workspace: Path,
) -> str:
    origin = _runtime_module_origin(module)
    if origin == "<unknown>":
        raise RuntimeError(f"{label} resolved without a file origin")
    workspace_root = chatbot_runtime_workspace.resolve()
    origin_path = Path(origin)
    if workspace_root != origin_path and workspace_root not in origin_path.parents:
        raise RuntimeError(
            f"{label} resolved outside runtime workspace: {origin}"
        )
    return origin


def _drop_runtime_validation_import_cache() -> None:
    prefixes = [
        "server_fastapi",
        "src.api",
        "src.adapters.setup",
        "src.adapters.base",
        "src.runtime_auth",
        "chatbot.src.api",
        "chatbot.src.adapters.setup",
        "chatbot.src.adapters.base",
        "chatbot.src.runtime_auth",
    ]
    for prefix in prefixes:
        _drop_import_cache(prefix)


def _load_runtime_validation_modules(
    *,
    chatbot_runtime_workspace: Path,
) -> tuple[Any, Any, Any, Any, dict[str, str]]:
    chatbot_runtime_workspace = chatbot_runtime_workspace.resolve()
    with _prepend_path(chatbot_runtime_workspace):
        _drop_runtime_validation_import_cache()
        _repair_runtime_src_namespace(chatbot_runtime_workspace=chatbot_runtime_workspace)
        runtime_server_fastapi = importlib.import_module("server_fastapi")
        runtime_chat_endpoint = importlib.import_module("src.api.v1.endpoints.chat")
        adapter_setup = importlib.import_module("src.adapters.setup")
        adapter_base = importlib.import_module("src.adapters.base")
        _repair_runtime_src_namespace(chatbot_runtime_workspace=chatbot_runtime_workspace)
    module_origins = {
        "server_fastapi": _assert_runtime_module_origin(
            label="server_fastapi",
            module=runtime_server_fastapi,
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        ),
        "chat_endpoint": _assert_runtime_module_origin(
            label="src.api.v1.endpoints.chat",
            module=runtime_chat_endpoint,
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        ),
        "adapter_setup": _assert_runtime_module_origin(
            label="src.adapters.setup",
            module=adapter_setup,
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        ),
        "adapter_base": _assert_runtime_module_origin(
            label="src.adapters.base",
            module=adapter_base,
            chatbot_runtime_workspace=chatbot_runtime_workspace,
        ),
    }
    return (
        runtime_server_fastapi,
        runtime_chat_endpoint,
        adapter_setup,
        adapter_base,
        module_origins,
    )


def _load_runtime_chat_modules(*, chatbot_runtime_workspace: Path) -> tuple[Any, Any]:
    chatbot_runtime_workspace = chatbot_runtime_workspace.resolve()
    with _prepend_path(chatbot_runtime_workspace):
        _drop_runtime_chat_import_cache()
        _repair_runtime_src_namespace(chatbot_runtime_workspace=chatbot_runtime_workspace)
        runtime_server_fastapi = importlib.import_module("server_fastapi")
        runtime_chat_endpoint = importlib.import_module("chatbot.src.api.v1.endpoints.chat")
        _repair_runtime_src_namespace(chatbot_runtime_workspace=chatbot_runtime_workspace)
    return runtime_server_fastapi, runtime_chat_endpoint


@contextmanager
def _patched_stream_callbacks(runtime_chat_endpoint: Any, callback_handler: BaseCallbackHandler):
    original = runtime_chat_endpoint._build_stream_config

    def _wrapped_build_stream_config(*args, **kwargs):
        config = original(*args, **kwargs)
        callbacks = list(config.get("callbacks") or [])
        callbacks.append(callback_handler)
        config["callbacks"] = callbacks
        return config

    with patch.object(runtime_chat_endpoint, "_build_stream_config", _wrapped_build_stream_config):
        yield


@contextmanager
def _patched_runtime_adapter_resolution(*, chat_endpoint: Any, adapter: Any):
    runtime_auth_fn = getattr(chat_endpoint, "resolve_runtime_auth", None)
    runtime_auth_module_name = getattr(runtime_auth_fn, "__module__", "").strip()
    if not runtime_auth_module_name:
        raise AttributeError("chat endpoint missing resolve_runtime_auth")
    runtime_auth_module = importlib.import_module(runtime_auth_module_name)
    with patch.object(runtime_auth_module, "_resolve_adapter", lambda site_id: adapter):
        yield


def _runtime_base_url(
    runtime_plan: BackendRuntimePlan,
    *,
    chat_auth_contract_path: str = "/api/chat/auth-token",
) -> str:
    if runtime_plan.listen_port:
        return f"http://127.0.0.1:{runtime_plan.listen_port}"
    readiness_url = runtime_plan.readiness_url
    marker = str(chat_auth_contract_path or "").strip() or "/api/chat/auth-token"
    if readiness_url.endswith(marker):
        return readiness_url.removesuffix(marker)
    return readiness_url.rsplit("/", 1)[0]


def _load_generated_adapter(
    *,
    chatbot_runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
    plan: IntegrationPlan,
):
    module_prefix = f"src.adapters.generated.{plan.chatbot_bridge.site_key}"
    with _prepend_path(chatbot_runtime_workspace):
        _drop_generated_adapter_import_cache(module_prefix)
        _repair_runtime_src_namespace(chatbot_runtime_workspace=chatbot_runtime_workspace)
        adapter_module = importlib.import_module(f"{module_prefix}.adapter")
        client_module = importlib.import_module(f"{module_prefix}.client")
        _repair_runtime_src_namespace(chatbot_runtime_workspace=chatbot_runtime_workspace)
        adapter_class = getattr(
            adapter_module,
            f"Generated{_class_name(plan.chatbot_bridge.site_key)}Adapter",
        )
        client_class = getattr(
            client_module, f"Generated{_class_name(plan.chatbot_bridge.site_key)}Client"
        )
        return adapter_class(
            client=client_class(
                base_url=_runtime_base_url(
                    runtime_plan,
                    chat_auth_contract_path=plan.host_backend.chat_auth_contract_path,
                )
            )
        )


def _drop_generated_adapter_import_cache(module_prefix: str) -> None:
    prefixes = [
        module_prefix,
        "src.adapters.generated",
        "src.adapters.setup",
        "src.runtime_auth",
        module_prefix.replace("src.", "chatbot.src.", 1),
        "chatbot.src.adapters.generated",
        "chatbot.src.adapters.setup",
        "chatbot.src.runtime_auth",
    ]
    seen: set[str] = set()
    for prefix in prefixes:
        if prefix in seen:
            continue
        seen.add(prefix)
        _drop_import_cache(prefix)


def _drop_runtime_chat_import_cache() -> None:
    prefixes = [
        "server_fastapi",
        "src.api",
        "src.adapters.generated",
        "src.adapters.setup",
        "src.runtime_auth",
        "chatbot.src.api",
        "chatbot.src.adapters.generated",
        "chatbot.src.adapters.setup",
        "chatbot.src.runtime_auth",
    ]
    for prefix in prefixes:
        _drop_import_cache(prefix)


def _repair_runtime_src_namespace(*, chatbot_runtime_workspace: Path) -> None:
    chatbot_runtime_workspace = chatbot_runtime_workspace.resolve()
    workspace_src = str((chatbot_runtime_workspace / "src").resolve())
    repo_src = str(Path(__file__).resolve().parents[2])
    workspace_adapters = str((chatbot_runtime_workspace / "src" / "adapters").resolve())
    repo_adapters = str((Path(__file__).resolve().parents[2] / "adapters").resolve())
    workspace_api = str((chatbot_runtime_workspace / "src" / "api").resolve())
    repo_api = str((Path(__file__).resolve().parents[2] / "api").resolve())
    chatbot_pkg = sys.modules.get("chatbot")

    namespace_paths = {
        "src": (workspace_src, repo_src),
        "chatbot.src": (workspace_src, repo_src),
        "src.adapters": (workspace_adapters, repo_adapters),
        "chatbot.src.adapters": (workspace_adapters, repo_adapters),
        "src.api": (workspace_api, repo_api),
        "chatbot.src.api": (workspace_api, repo_api),
    }

    for module_name, candidates in namespace_paths.items():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        path_entries = list(getattr(module, "__path__", []) or [])
        normalized = [str(Path(entry).resolve()) for entry in path_entries]
        merged: list[str] = []
        for candidate in (*candidates, *normalized):
            if candidate not in merged:
                merged.append(candidate)
        module.__path__ = merged
        if chatbot_pkg is not None and module_name == "chatbot.src":
            setattr(chatbot_pkg, "src", module)

    for module_name in (
        "chatbot.src.onboarding_v2",
        "chatbot.src.onboarding_v2.validation",
        "chatbot.src.onboarding_v2.validation.runner",
    ):
        _reattach_parent_module(module_name)

    if "chatbot.src.graph" not in sys.modules:
        try:
            importlib.import_module("chatbot.src.graph")
        except ModuleNotFoundError:
            pass
    _reattach_parent_module("chatbot.src.graph")


def _reattach_parent_module(module_name: str) -> None:
    module = sys.modules.get(module_name)
    if module is None or "." not in module_name:
        return
    parent_name, attr_name = module_name.rsplit(".", 1)
    parent = sys.modules.get(parent_name)
    if parent is None:
        return
    setattr(parent, attr_name, module)


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
