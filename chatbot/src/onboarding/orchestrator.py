from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_contracts import RunState
from .agent_orchestrator import AgentOrchestrator
from .approval_store import ApprovalStore
from .exporter import export_runtime_patch
from .overlay_generator import generate_overlay_scaffold
from .role_runner import RoleRunner, build_llm_role_runner
from .run_generator import generate_run_bundle
from .slack_bridge import InMemorySlackBridge
from .smoke_runner import load_smoke_plan, run_smoke_tests, summarize_smoke_results
from .runtime_runner import prepare_runtime_workspace
from .manifest import OverlayManifest
from .template_generator import (
    generate_chat_auth_template,
    generate_frontend_mount_patch,
    generate_order_adapter_template,
    generate_product_adapter_template,
)


def run_onboarding_generation(
    *,
    site: str,
    source_root: str | Path,
    generated_root: str | Path,
    runtime_root: str | Path,
    run_id: str,
    agent_version: str,
    slack_bridge: InMemorySlackBridge | None = None,
    role_runner: RoleRunner | None = None,
    approval_decisions: dict[str, str] | None = None,
    approval_store: ApprovalStore | None = None,
    use_llm_roles: bool = False,
    llm_provider: str = "openai",
    llm_model: str = "gpt-4o-mini",
) -> dict[str, Any]:
    bridge = slack_bridge
    agent = AgentOrchestrator(run_id=run_id)
    approvals = approval_decisions
    active_role_runner = role_runner or (
        build_llm_role_runner(provider=llm_provider, model=llm_model)
        if use_llm_roles
        else RoleRunner(
        responders={
            "Analyzer": lambda context: {
                "claim": f"Detected onboarding-relevant structure for {context['site']}",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "pass detected capabilities to planner",
                "blocking_issue": "none",
            },
            "Planner": lambda context: {
                "claim": f"Need {', '.join(context['recommended_outputs'])} generation",
                "evidence": context["evidence"],
                "confidence": 0.82,
                "risk": "medium",
                "next_action": "ask generator to create overlay scaffold and templates",
                "blocking_issue": "none",
            },
            "Generator": lambda context: {
                "claim": "Prepared overlay artifact proposal",
                "evidence": context["evidence"],
                "confidence": 0.81,
                "risk": "medium",
                "next_action": "materialize proposed files and patches",
                "blocking_issue": "none",
                "metadata": {
                    "proposed_files": context["proposed_files"],
                    "proposed_patches": context["proposed_patches"],
                },
            },
            "Validator": lambda context: {
                "claim": "Smoke validation finished",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "low" if context["passed"] else "high",
                "next_action": "prepare export approval" if context["passed"] else "send to diagnostician",
                "blocking_issue": "none" if context["passed"] else "smoke failures detected",
            },
            "Diagnostician": lambda context: {
                "claim": "Validation failed and needs another attempt",
                "evidence": context["evidence"],
                "confidence": 0.75,
                "risk": "medium",
                "next_action": "retry_validation" if context["retry_count"] < context["retry_budget"] else "request_human_review",
                "blocking_issue": "none" if context["retry_count"] < context["retry_budget"] else "retry budget exhausted",
                "metadata": {
                    "should_retry": context["retry_count"] < context["retry_budget"],
                },
            },
        }
    ))

    if bridge is not None:
        bridge.post_run_root(
            run_id=run_id,
            site=site,
            source_root=str(source_root),
            goal="generate onboarding overlay",
            current_state=agent.state,
            approval_status="not_requested",
        )

    agent.mark_analysis_started()
    run_root = generate_run_bundle(
        site=site,
        source_root=source_root,
        generated_root=generated_root,
        run_id=run_id,
        agent_version=agent_version,
    )
    manifest = OverlayManifest.model_validate_json((run_root / "manifest.json").read_text(encoding="utf-8"))
    analysis = manifest.analysis
    analyzer_context = {
        "site": site,
        "analysis": analysis,
        "evidence": _build_analysis_evidence(analysis),
    }
    analyzer_message = active_role_runner.run_role("Analyzer", analyzer_context)

    if bridge is not None:
        bridge.post_agent_message(
            event=active_role_runner.build_event(
                run_id=run_id,
                event_type="analysis.completed",
                state=RunState.ANALYZING,
                message=analyzer_message,
                created_at=datetime.now(timezone.utc).isoformat(),
            ),
            message=analyzer_message,
        )

        bridge.post_approval_request(
            run_id=run_id,
            approval_type=agent.request_analysis_approval(
                summary="Analysis is ready for review",
                recommended_option="approve",
            )["approval_type"],
            summary="Analysis is ready for review",
            recommended_option="approve",
            risk_if_approved="downstream plan depends on this analysis",
            risk_if_rejected="run stops before generation",
            available_actions=["approve", "reject"],
        )

    elif approvals is not None or approval_store is not None:
        agent.request_analysis_approval(
            summary="Analysis is ready for review",
            recommended_option="approve",
        )
        if approval_store is not None:
            approval_store.create_request(run_id=run_id, approval_type="analysis")

    approval_result = _apply_approval_decision(
        agent=agent,
        approval_type="analysis",
        decisions=approvals,
        approval_store=approval_store,
    )
    if approval_result != "approved":
        return _build_run_result(
            run_root=run_root,
            runtime_workspace=None,
            agent=agent,
            bridge=bridge,
        )
    recommended_outputs = [
        output
        for output in [
            "chat_auth",
            "order_adapter",
            "product_adapter",
            "frontend_patch",
        ]
    ]
    planner_context = {
        "site": site,
        "analysis": analysis,
        "recommended_outputs": recommended_outputs,
        "evidence": _build_planning_evidence(analysis, recommended_outputs, manifest.status),
    }
    planner_message = active_role_runner.run_role("Planner", planner_context)
    if bridge is not None:
        bridge.post_agent_message(
            event=active_role_runner.build_event(
                run_id=run_id,
                event_type="plan.completed",
                state=RunState.PLANNING,
                message=planner_message,
                created_at=datetime.now(timezone.utc).isoformat(),
            ),
            message=planner_message,
        )

    proposed_files = _build_proposed_files(recommended_outputs)
    proposed_patches = _build_proposed_patches(recommended_outputs)
    generator_context = {
        "site": site,
        "analysis": analysis,
        "recommended_outputs": recommended_outputs,
        "proposed_files": proposed_files,
        "proposed_patches": proposed_patches,
        "evidence": _build_generation_evidence(
            analysis=analysis,
            recommended_outputs=recommended_outputs,
            proposed_files=proposed_files,
            proposed_patches=proposed_patches,
        ),
    }
    generator_message = active_role_runner.run_role("Generator", generator_context)
    if bridge is not None:
        bridge.post_agent_message(
            event=active_role_runner.build_event(
                run_id=run_id,
                event_type="generation.completed",
                state=RunState.GENERATING,
                message=generator_message,
                created_at=datetime.now(timezone.utc).isoformat(),
            ),
            message=generator_message,
        )

    generate_overlay_scaffold(run_root)
    agent.mark_plan_completed()
    proposed_files = list(generator_message.metadata.get("proposed_files") or proposed_files)
    proposed_patches = list(generator_message.metadata.get("proposed_patches") or proposed_patches)
    _materialize_generator_proposals(
        run_root=run_root,
        proposed_files=proposed_files,
        proposed_patches=proposed_patches,
    )

    if bridge is not None:
        bridge.post_approval_request(
            run_id=run_id,
            approval_type=agent.request_apply_approval(
                summary="Overlay bundle is ready to apply",
                recommended_option="approve",
            )["approval_type"],
            summary="Overlay bundle is ready to apply",
            recommended_option="approve",
            risk_if_approved="runtime patch may fail",
            risk_if_rejected="run stops before validation",
            available_actions=["approve", "reject"],
        )
    else:
        agent.request_apply_approval(
            summary="Overlay bundle is ready to apply",
            recommended_option="approve",
        )
        if approval_store is not None:
            approval_store.create_request(run_id=run_id, approval_type="apply")

    approval_result = _apply_approval_decision(
        agent=agent,
        approval_type="apply",
        decisions=approvals,
        approval_store=approval_store,
    )
    if approval_result != "approved":
        return _build_run_result(
            run_root=run_root,
            runtime_workspace=None,
            agent=agent,
            bridge=bridge,
        )

    runtime_workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_root=runtime_root,
    )
    agent.mark_apply_completed()
    smoke_plan = load_smoke_plan(run_root)
    smoke_results = _run_validation_with_retries(
        run_id=run_id,
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=smoke_plan,
        agent=agent,
        bridge=bridge,
        role_runner=active_role_runner,
    )
    (run_root / "reports" / "smoke-results.json").write_text(
        json.dumps(smoke_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    smoke_summary = summarize_smoke_results(smoke_results)
    (run_root / "reports" / "smoke-summary.json").write_text(
        json.dumps(smoke_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not smoke_summary["passed"]:
        return _build_run_result(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            agent=agent,
            bridge=bridge,
        )

    validator_context = {
        "passed": smoke_summary["passed"],
        "smoke_results": smoke_results,
        "failure_count": smoke_summary["failure_count"],
        "failed_steps": smoke_summary["required_failures"] + smoke_summary["optional_failures"],
        "evidence": [
            f"smoke steps: {len(smoke_results)}",
            f"failures: {smoke_summary['failure_count']}",
            f"required failures: {smoke_summary['required_failures']}",
            f"optional failures: {smoke_summary['optional_failures']}",
            f"timed out steps: {smoke_summary['timed_out_steps']}",
        ],
    }
    validator_message = active_role_runner.run_role("Validator", validator_context)

    agent.mark_validation_completed()

    if bridge is not None:
        bridge.post_agent_message(
            event=active_role_runner.build_event(
                run_id=run_id,
                event_type="validation.completed",
                state=RunState.VALIDATING,
                message=validator_message,
                created_at=datetime.now(timezone.utc).isoformat(),
            ),
            message=validator_message,
        )
        bridge.post_approval_request(
            run_id=run_id,
            approval_type=agent.request_export_approval(
                summary="Export bundle is ready",
                recommended_option="approve",
            )["approval_type"],
            summary="Export bundle is ready",
            recommended_option="approve",
            risk_if_approved="patch export may still need manual review",
            risk_if_rejected="run remains local only",
            available_actions=["approve", "reject"],
        )
    else:
        agent.request_export_approval(
            summary="Export bundle is ready",
            recommended_option="approve",
        )
        if approval_store is not None:
            approval_store.create_request(run_id=run_id, approval_type="export")

    approval_result = _apply_approval_decision(
        agent=agent,
        approval_type="export",
        decisions=approvals,
        approval_store=approval_store,
    )
    if approval_result != "approved":
        return _build_run_result(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            agent=agent,
            bridge=bridge,
        )

    export_runtime_patch(
        source_root=source_root,
        runtime_workspace=runtime_workspace,
        report_root=run_root / "reports",
    )
    agent.mark_export_completed()

    return _build_run_result(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        agent=agent,
        bridge=bridge,
    )


def _apply_approval_decision(
    *,
    agent: AgentOrchestrator,
    approval_type: str,
    decisions: dict[str, str] | None,
    approval_store: ApprovalStore | None,
) -> str | None:
    if decisions is None and approval_store is None:
        decision = "approve"
    elif decisions is not None:
        decision = decisions.get(approval_type)
        if decision is None:
            return None
    else:
        consumed = approval_store.consume_decision(
            run_id=agent.run_id,
            approval_type=approval_type,
        )
        if consumed is None:
            return None
        decision = str(consumed.get("decision") or "")

    normalized = decision.strip().lower()
    if normalized == "approve":
        if approval_type == "analysis":
            agent.mark_analysis_completed()
        elif approval_type == "apply":
            agent.approve_apply()
        elif approval_type == "export":
            agent.approve_export()
        return "approved"

    if normalized == "reject":
        agent.reject_current_approval()
        return "rejected"

    raise ValueError(f"Unsupported approval decision for {approval_type}: {decision}")


def _run_validation_with_retries(
    *,
    run_id: str,
    run_root: Path,
    runtime_workspace: Path,
    smoke_plan,
    agent: AgentOrchestrator,
    bridge: InMemorySlackBridge | None,
    role_runner: RoleRunner,
) -> list[dict]:
    smoke_results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=smoke_plan,
    )
    while any(result.get("returncode") != 0 for result in smoke_results):
        failure_policy = _classify_failure_policy(smoke_results)
        failed_steps = failure_policy["failed_steps"]
        failure_signature = failure_policy["failure_signature"]
        if failure_policy["retryable"]:
            agent.mark_failure()
        else:
            agent.state = RunState.HUMAN_REVIEW_REQUIRED
        diagnoser_message = role_runner.run_role(
            "Diagnostician",
            {
                "run_id": run_id,
                "retry_count": agent.retry_count,
                "retry_budget": agent.retry_budget,
                "failure_signature": failure_signature,
                "failed_steps": failed_steps,
                "retryable": failure_policy["retryable"],
                "failure_summary": failure_policy["summary"],
                "smoke_results": smoke_results,
                "evidence": [
                    f"failed smoke steps: {sum(1 for result in smoke_results if result.get('returncode') != 0)}",
                    f"current state: {agent.state.value}",
                    f"failure signature: {failure_signature}",
                    f"retryable: {failure_policy['retryable']}",
                    f"timed out steps: {failure_policy['summary']['timed_out_steps']}",
                    f"missing scripts: {failure_policy['summary']['missing_scripts']}",
                ],
            },
        )
        _write_diagnostic_report(
            run_root=run_root,
            diagnoser_message=diagnoser_message,
            failure_policy=failure_policy,
            retry_count=agent.retry_count,
            retry_budget=agent.retry_budget,
        )
        if bridge is not None:
            bridge.post_agent_message(
                event=role_runner.build_event(
                    run_id=run_id,
                    event_type="diagnosis.completed",
                    state=RunState.DIAGNOSING,
                    message=diagnoser_message,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ),
                message=diagnoser_message,
            )

        should_retry = failure_policy["retryable"] and bool(diagnoser_message.metadata.get("should_retry"))
        if not should_retry or agent.state == RunState.HUMAN_REVIEW_REQUIRED:
            return smoke_results

        agent.state = RunState.VALIDATING
        smoke_results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=smoke_plan,
        )

    return smoke_results


def _classify_failure_policy(smoke_results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_smoke_results(smoke_results)
    failed_steps = [
        result.get("step_id") or result.get("step")
        for result in smoke_results
        if result.get("returncode") != 0
    ]
    failure_signature = "|".join(
        f"{result.get('step_id') or result.get('step')}:{result.get('returncode')}"
        for result in smoke_results
        if result.get("returncode") != 0
    )
    structural_markers = (
        "Smoke script not found:",
        "patch apply failed",
        "auth mismatch",
        "contract mismatch",
    )
    has_structural_failure = any(
        any(marker in (result.get("stderr") or "") for marker in structural_markers)
        for result in smoke_results
        if result.get("returncode") != 0
    )
    retryable = summary["failure_count"] > 0 and not has_structural_failure
    return {
        "failed_steps": failed_steps,
        "failure_signature": failure_signature,
        "retryable": retryable,
        "summary": summary,
    }


def _write_diagnostic_report(
    *,
    run_root: Path,
    diagnoser_message,
    failure_policy: dict[str, Any],
    retry_count: int,
    retry_budget: int,
) -> None:
    reports_root = run_root / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "failure_signature": failure_policy["failure_signature"],
        "failed_steps": failure_policy["failed_steps"],
        "retryable": failure_policy["retryable"],
        "summary": failure_policy["summary"],
        "retry_count": retry_count,
        "retry_budget": retry_budget,
        "final_action": diagnoser_message.next_action,
        "claim": diagnoser_message.claim,
        "blocking_issue": diagnoser_message.blocking_issue,
        "metadata": diagnoser_message.metadata,
        "evidence": diagnoser_message.evidence,
    }
    (reports_root / "diagnostic-report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_run_result(
    *,
    run_root: Path,
    runtime_workspace: Path | None,
    agent: AgentOrchestrator,
    bridge: InMemorySlackBridge | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_root": str(run_root),
        "runtime_workspace": str(runtime_workspace) if runtime_workspace is not None else None,
        "smoke_results_path": str(run_root / "reports" / "smoke-results.json"),
        "smoke_summary_path": str(run_root / "reports" / "smoke-summary.json"),
        "diagnostic_report_path": str(run_root / "reports" / "diagnostic-report.json"),
        "export_metadata_path": str(run_root / "reports" / "export-metadata.json"),
        "slack_message_count": len(bridge.messages) if bridge is not None else 0,
        "current_state": agent.state.value,
        "pending_approval": agent.pending_approval,
    }
    return result


def _build_analysis_evidence(analysis: dict[str, Any]) -> list[str]:
    auth = analysis.get("auth") or {}
    framework = analysis.get("framework") or {}
    return [
        f"backend framework: {framework.get('backend', 'unknown')}",
        f"frontend framework: {framework.get('frontend', 'unknown')}",
        f"auth style: {auth.get('auth_style', 'unknown')}",
        f"auth signals: {auth.get('signals') or []}",
        f"login entrypoints: {auth.get('login_entrypoints') or []}",
        f"me entrypoints: {auth.get('me_entrypoints') or []}",
        f"backend entrypoints: {analysis.get('backend_entrypoints') or []}",
        f"route prefixes: {analysis.get('route_prefixes') or []}",
        f"product api: {analysis.get('product_api') or []}",
        f"order api: {analysis.get('order_api') or []}",
        f"frontend mounts: {analysis.get('frontend_mount_points') or []}",
    ]


def _build_planning_evidence(
    analysis: dict[str, Any],
    recommended_outputs: list[str],
    manifest_status: str,
) -> list[str]:
    framework = analysis.get("framework") or {}
    auth = analysis.get("auth") or {}
    return [
        f"backend framework: {framework.get('backend', 'unknown')}",
        f"frontend framework: {framework.get('frontend', 'unknown')}",
        f"auth style: {auth.get('auth_style', 'unknown')}",
        f"route prefixes: {analysis.get('route_prefixes') or []}",
        f"recommended outputs: {recommended_outputs}",
        f"frontend mount points: {analysis.get('frontend_mount_points') or []}",
        f"status: {manifest_status}",
    ]


def _build_proposed_files(recommended_outputs: list[str]) -> list[str]:
    file_map = {
        "chat_auth": "files/backend/chat_auth.py",
        "order_adapter": "files/backend/order_adapter_client.py",
        "product_adapter": "files/backend/product_adapter_client.py",
    }
    return [file_map[item] for item in recommended_outputs if item in file_map]


def _build_proposed_patches(recommended_outputs: list[str]) -> list[str]:
    patch_map = {
        "frontend_patch": "patches/frontend_widget_mount.patch",
    }
    return [patch_map[item] for item in recommended_outputs if item in patch_map]


def _build_generation_evidence(
    *,
    analysis: dict[str, Any],
    recommended_outputs: list[str],
    proposed_files: list[str],
    proposed_patches: list[str],
) -> list[str]:
    return [
        f"recommended outputs: {recommended_outputs}",
        f"proposed files: {proposed_files}",
        f"proposed patches: {proposed_patches}",
        f"auth style: {(analysis.get('auth') or {}).get('auth_style', 'unknown')}",
        f"frontend mount points: {analysis.get('frontend_mount_points') or []}",
    ]


def _materialize_generator_proposals(
    *,
    run_root: Path,
    proposed_files: list[str],
    proposed_patches: list[str],
) -> None:
    file_generators = {
        "files/backend/chat_auth.py": generate_chat_auth_template,
        "files/backend/order_adapter_client.py": generate_order_adapter_template,
        "files/backend/product_adapter_client.py": generate_product_adapter_template,
    }
    patch_generators = {
        "patches/frontend_widget_mount.patch": generate_frontend_mount_patch,
    }

    for file_path in proposed_files:
        generator = file_generators.get(file_path)
        if generator is not None:
            generator(run_root)

    for patch_path in proposed_patches:
        generator = patch_generators.get(patch_path)
        if generator is not None:
            generator(run_root)
