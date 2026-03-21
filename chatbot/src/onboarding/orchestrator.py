from __future__ import annotations

import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from .agent_contracts import AgentMessage, RecoveryAttempt, RunState
from .agent_orchestrator import AgentOrchestrator
from .approval_store import ApprovalStore
from .backend_evaluator import evaluate_backend_workspace
from .codebase_mapper import (
    build_llm_codebase_interpretation_factory,
    write_codebase_map,
    write_llm_codebase_interpretation,
)
from .debug_logging import append_execution_trace, append_generation_log, append_onboarding_event, append_recovery_event, update_file_activity
from .exporter import export_patch_artifact, export_runtime_patch
from .frontend_evaluator import evaluate_frontend_workspace
from .overlay_generator import generate_overlay_scaffold
from .patch_planner import (
    build_llm_patch_proposal_factory,
    build_llm_patch_factory,
    write_patch_comparison_report,
    write_llm_first_patch_proposal,
    write_llm_patch_draft,
    write_patch_proposal,
    write_unified_diff_draft,
)
from .role_runner import ReliableLLMRoleRunner, RoleRunner, build_llm_role_runner
from .recovery_artifacts import write_recovered_smoke_plan
from .recovery_planner import build_recovery_plan
from .run_generator import generate_run_bundle
from .run_resume import analyze_run_checkpoint
from .runtime_completion_runner import (
    _build_backend_probe_plan,
    _build_chatbot_probe_plan,
    _build_frontend_probe_plan,
    _classify_probe_failure_reason,
    _collect_process_output,
    _launch_server_process,
    _probe_http_ready,
    _terminate_process,
    run_runtime_completion,
)
from .runtime_llm_repair import attempt_llm_runtime_repair, build_runtime_repair_factory
from .runtime_repair_toolkit import repair_python_import_from_traceback, rewrite_javascript_module_specifier
from .slack_bridge import InMemorySlackBridge
from .smoke_contract import SmokeTestPlan
from .smoke_runner import load_smoke_plan, run_smoke_tests, summarize_smoke_results
from .runtime_runner import prepare_runtime_workspace, simulate_runtime_merge
from .runtime_runner import simulate_candidate_patch_merge
from .manifest import OverlayManifest
from .template_generator import (
    generate_backend_route_patch,
    generate_backend_tool_registry,
    generate_chat_auth_template,
    generate_frontend_widget_artifact,
    generate_frontend_mount_patch,
    generate_order_adapter_template,
    generate_product_adapter_template,
)
from .redis_models import JobRecord, RunEventRecord, RunRecord
from .redis_store import RedisRunJobStore
from .worker_process import WorkerProcess


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
    generate_llm_patch_draft: bool = False,
    enable_runtime_completion_loop: bool = False,
    llm_patch_factory: Any | None = None,
    terminal_logger: Callable[[str], None] | None = None,
    event_store: RedisRunJobStore | None = None,
    onboarding_credentials: dict[str, str] | None = None,
    resume_from_existing: bool = False,
) -> dict[str, Any]:
    bridge = slack_bridge
    agent = AgentOrchestrator(run_id=run_id)
    approvals = approval_decisions
    fallback_role_runner = RoleRunner(
        responders={
            "Analyzer": lambda context: {
                "claim": f"{context['site']} 사이트에서 온보딩 관련 구조를 확인했습니다",
                "evidence": context["evidence"],
                "confidence": 0.8,
                "risk": "medium",
                "next_action": "확인된 capabilities를 Planner에 전달합니다",
                "blocking_issue": "없음",
            },
            "Planner": lambda context: {
                "claim": f"{', '.join(context['recommended_outputs'])} 생성을 우선 진행해야 합니다",
                "evidence": context["evidence"],
                "confidence": 0.82,
                "risk": "medium",
                "next_action": "Generator가 overlay scaffold와 템플릿 초안을 만들도록 요청합니다",
                "blocking_issue": "없음",
            },
            "Generator": lambda context: {
                "claim": "overlay artifact 제안 초안을 준비했습니다",
                "evidence": context["evidence"],
                "confidence": 0.81,
                "risk": "medium",
                "next_action": "제안된 파일과 patch를 실제 산출물로 생성합니다",
                "blocking_issue": "없음",
                "metadata": {
                    "proposed_files": context["proposed_files"],
                    "proposed_patches": context["proposed_patches"],
                },
            },
            "Validator": lambda context: {
                "claim": "스모크 검증을 완료했습니다",
                "evidence": context["evidence"],
                "confidence": 0.9,
                "risk": "low" if context["passed"] else "high",
                "next_action": "export 승인을 준비합니다" if context["passed"] else "Diagnostician으로 실패 원인을 전달합니다",
                "blocking_issue": "없음" if context["passed"] else "스모크 실패가 감지되었습니다",
            },
            "Diagnostician": lambda context: {
                "claim": "검증이 실패해 원인 분석과 재시도가 필요합니다",
                "evidence": context["evidence"],
                "confidence": 0.75,
                "risk": "medium",
                "next_action": "retry_validation" if context["retry_count"] < context["retry_budget"] else "request_human_review",
                "blocking_issue": "없음" if context["retry_count"] < context["retry_budget"] else "재시도 한도를 모두 사용했습니다",
                "metadata": {
                    "should_retry": context["retry_count"] < context["retry_budget"],
                },
            },
        }
    )
    active_role_runner = role_runner or (
        ReliableLLMRoleRunner(
            llm_runner=build_llm_role_runner(provider=llm_provider, model=llm_model),
            fallback_runner=fallback_role_runner,
        )
        if use_llm_roles
        else fallback_role_runner
    )

    role_attempts: dict[str, int] = defaultdict(int)
    llm_runtime_repair_factory = build_runtime_repair_factory(
        enabled=use_llm_roles or generate_llm_patch_draft,
        llm_factory=llm_patch_factory,
        provider=llm_provider,
        model=llm_model,
    )

    def _next_job_id(role_name: str) -> str:
        role_attempts[role_name] += 1
        return f"{run_id}:{role_name}:{role_attempts[role_name]}"

    def _run_role_with_events(
        role: str,
        context: dict[str, Any],
        *,
        job_started_payload: dict[str, Any] | None = None,
        job_completed_payload: dict[str, Any] | None = None,
    ) -> AgentMessage:
        job_id = _next_job_id(role)
        start_payload = {"details": "starting role"}
        if job_started_payload:
            start_payload.update(job_started_payload)
        _publish_job_event(
            event_store,
            run_id,
            job_id,
            role,
            "job.started",
            start_payload,
        )
        try:
            message = active_role_runner.run_role(role, context)
        except Exception as exc:
            _publish_job_event(
                event_store,
                run_id,
                job_id,
                role,
                "job.failed",
                {"error": str(exc)},
            )
            raise
        completed_payload = {
            "message": message.claim,
            "metadata": message.metadata or {},
        }
        if job_completed_payload:
            completed_payload.update(job_completed_payload)
        _publish_job_event(
            event_store,
            run_id,
            job_id,
            role,
            "job.completed",
            completed_payload,
        )
        return message

    resume_checkpoint: dict[str, Any] | None = None

    def finalize_result(*, runtime_workspace: Path | None) -> dict[str, Any]:
        _write_llm_role_execution_report(run_root=run_root, runner=active_role_runner)
        _write_llm_debug_artifacts(run_root=run_root, runner=active_role_runner)
        result = _build_run_result(
            run_id=run_id,
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            agent=agent,
            bridge=bridge,
            event_store=event_store,
        )
        result["resume_checkpoint"] = resume_checkpoint
        return result

    if bridge is not None:
        bridge.post_run_root(
            run_id=run_id,
            site=site,
            source_root=str(source_root),
            goal="generate onboarding overlay",
            current_state=agent.state,
            approval_status="not_requested",
        )

    existing_run_root = Path(generated_root) / site / run_id
    if resume_from_existing and existing_run_root.exists():
        checkpoint = analyze_run_checkpoint(existing_run_root)
        resume_checkpoint = {
            "run_root": checkpoint.run_root,
            "last_completed_stage": checkpoint.last_completed_stage,
            "failed_stage": checkpoint.failed_stage,
            "resume_from_stage": checkpoint.resume_from_stage,
            "reason": checkpoint.reason,
        }
        if checkpoint.resume_from_stage in {"validation", "export"}:
            run_root = existing_run_root
            manifest = OverlayManifest.model_validate_json((run_root / "manifest.json").read_text(encoding="utf-8"))
            analysis = manifest.analysis
            runtime_workspace = prepare_runtime_workspace(
                manifest=manifest,
                generated_run_root=run_root,
                runtime_root=runtime_root,
            )
            merge_simulation_path = simulate_runtime_merge(
                manifest=manifest,
                generated_run_root=run_root,
                runtime_workspace=runtime_workspace,
                report_root=run_root / "reports",
            )
            merge_simulation = json.loads(merge_simulation_path.read_text(encoding="utf-8"))
            if not merge_simulation.get("passed", True):
                agent.state = RunState.HUMAN_REVIEW_REQUIRED
                return finalize_result(runtime_workspace=runtime_workspace)
            if checkpoint.resume_from_stage == "validation":
                _run_validation_evaluation_jobs(
                    run_id=run_id,
                    runtime_workspace=runtime_workspace,
                    report_root=run_root / "reports",
                    event_store=event_store,
                )
                if _read_runtime_failure_summary(run_root):
                    agent.state = RunState.HUMAN_REVIEW_REQUIRED
                    return finalize_result(runtime_workspace=runtime_workspace)
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
                    event_store=event_store,
                    terminal_logger=terminal_logger,
                    run_role_with_events=_run_role_with_events,
                    llm_runtime_repair_factory=llm_runtime_repair_factory,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
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
                    return finalize_result(runtime_workspace=runtime_workspace)
                agent.mark_validation_completed()
            else:
                agent.mark_validation_completed()

            export_request, should_publish_export_request = _prepare_export_approval_request(
                agent=agent,
                run_id=run_id,
                approval_store=approval_store,
                event_store=event_store,
            )
            if bridge is not None and should_publish_export_request:
                bridge.post_approval_request(
                    run_id=run_id,
                    approval_type=export_request["approval_type"],
                    summary="Export bundle is ready",
                    recommended_option="approve",
                    risk_if_approved="patch export may still need manual review",
                    risk_if_rejected="run remains local only",
                    available_actions=["approve", "reject"],
                )
            approval_result = _apply_approval_decision(
                agent=agent,
                approval_type="export",
                decisions=approvals,
                approval_store=approval_store,
            )
            if approval_result != "approved":
                return finalize_result(runtime_workspace=runtime_workspace)

            export_source, selected_patch_path = _select_export_source(run_root)
            strategy_provenance = {
                "backend_strategy": str(analysis.get("backend_strategy") or (analysis.get("framework") or {}).get("backend") or "unknown"),
                "frontend_strategy": str(analysis.get("frontend_strategy") or (analysis.get("framework") or {}).get("frontend") or "unknown"),
            }
            recovery_provenance = _read_recovery_provenance(run_root)
            if export_source == "llm" and selected_patch_path is not None:
                export_patch_artifact(
                    patch_path=selected_patch_path,
                    report_root=run_root / "reports",
                    export_source="llm",
                    strategy_provenance=strategy_provenance,
                    recovery_provenance=recovery_provenance,
                )
            else:
                export_runtime_patch(
                    source_root=source_root,
                    runtime_workspace=runtime_workspace,
                    report_root=run_root / "reports",
                    strategy_provenance=strategy_provenance,
                    recovery_provenance=recovery_provenance,
                )
            agent.mark_export_completed()
            return finalize_result(runtime_workspace=runtime_workspace)

    agent.mark_analysis_started()
    run_root = generate_run_bundle(
        site=site,
        source_root=source_root,
        generated_root=generated_root,
        run_id=run_id,
        agent_version=agent_version,
        onboarding_credentials=onboarding_credentials,
    )
    if event_store is not None:
        event_store.create_run(
            RunRecord(
                run_id=run_id,
                metadata={
                    "site": site,
                    "source_root": str(source_root),
                    "generated_root": str(generated_root),
                },
            )
        )
        _publish_run_event(
            event_store,
            run_id,
            "run.created",
            {"site": site, "source_root": str(source_root)},
        )
    codebase_map_path = write_codebase_map(
        source_root=source_root,
        output_path=run_root / "reports" / "codebase-map.json",
    )
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="analysis",
        event="stage_started",
        summary="analysis stage started",
        details={"site": site, "source_root": str(source_root)},
    )
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="codebase_map_written",
        message="codebase map written",
        details={"path": str(codebase_map_path)},
    )
    manifest = OverlayManifest.model_validate_json((run_root / "manifest.json").read_text(encoding="utf-8"))
    analysis = manifest.analysis
    codebase_map = json.loads(codebase_map_path.read_text(encoding="utf-8"))
    append_execution_trace(
        report_root=run_root / "reports",
        event="analysis_started",
        status="started",
        run_id=run_id,
        details={"site": site},
    )
    _emit_terminal_log(
        terminal_logger,
        f"[analysis] started site={site} source_root={source_root}",
    )
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="analysis_started",
        message="analysis started",
        details={"site": site, "source_root": str(source_root)},
    )
    llm_codebase_interpretation: dict[str, Any] | None = None
    if use_llm_roles:
        interpretation_path = write_llm_codebase_interpretation(
            source_root=source_root,
            analysis=analysis,
            codebase_map=codebase_map,
            output_path=run_root / "reports" / "llm-codebase-interpretation.json",
            llm_factory=build_llm_codebase_interpretation_factory(provider=llm_provider, model=llm_model),
            provider=llm_provider,
            model=llm_model,
        )
        llm_codebase_interpretation = json.loads(interpretation_path.read_text(encoding="utf-8"))
        append_execution_trace(
            report_root=run_root / "reports",
            event="llm_codebase_interpretation_written",
            status=str(llm_codebase_interpretation.get("source") or "fallback"),
            run_id=run_id,
            related_files=[str(item.get("path") or "") for item in (llm_codebase_interpretation.get("ranked_candidates") or [])],
        )
        _emit_terminal_log(
            terminal_logger,
            _format_llm_codebase_log(llm_codebase_interpretation),
        )
        _emit_latest_llm_usage(
            run_root=run_root,
            terminal_logger=terminal_logger,
            component="llm_codebase_interpretation",
        )
    analyzer_context = {
        "site": site,
        "analysis": analysis,
        "evidence": _build_analysis_evidence(analysis),
    }
    analyzer_message = _run_role_with_events("Analyzer", analyzer_context)
    append_execution_trace(
        report_root=run_root / "reports",
        event="analysis_completed",
        status="completed",
        run_id=run_id,
        details={"source": str(getattr(active_role_runner, "execution_log", {}).get("Analyzer", {}).get("source") or "deterministic")},
    )
    _emit_role_log(
        terminal_logger=terminal_logger,
        runner=active_role_runner,
        role="Analyzer",
        message=analyzer_message,
    )

    has_explicit_analysis_decision = _has_explicit_approval_decision(
        decisions=approvals,
        approval_type="analysis",
    )
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
        if not has_explicit_analysis_decision:
            analysis_request = agent.request_analysis_approval(
                summary="Analysis is ready for review",
                recommended_option="approve",
            )
            should_publish_analysis_request = True
            if approval_store is not None:
                existing = approval_store.get_decision(run_id=run_id, approval_type="analysis")
                if existing is None:
                    approval_store.create_request(
                        run_id=run_id,
                        approval_type="analysis",
                        blocked_job_id=str(analysis_request.get("blocked_job_id") or ""),
                    )
                else:
                    should_publish_analysis_request = existing["status"] == "pending"
            _publish_approval_requested_event(event_store, run_id, analysis_request)
            if should_publish_analysis_request:
                bridge.post_approval_request(
                    run_id=run_id,
                    approval_type=analysis_request["approval_type"],
                    summary="Analysis is ready for review",
                    recommended_option="approve",
                    risk_if_approved="downstream plan depends on this analysis",
                    risk_if_rejected="run stops before generation",
                    available_actions=["approve", "reject"],
                )

    elif not has_explicit_analysis_decision and (approvals is not None or approval_store is not None):
        agent.request_analysis_approval(
            summary="Analysis is ready for review",
            recommended_option="approve",
        )
        if approval_store is not None:
            approval_store.create_request(
                run_id=run_id,
                approval_type="analysis",
                blocked_job_id=str(agent.pending_approval.get("blocked_job_id") if agent.pending_approval else ""),
            )
        _publish_approval_requested_event(event_store, run_id, agent.pending_approval)

    approval_result = _apply_approval_decision(
        agent=agent,
        approval_type="analysis",
        decisions=approvals,
        approval_store=approval_store,
    )
    if bridge is not None and has_explicit_analysis_decision and approval_result is not None:
        bridge.record_approval_decision(
            run_id=run_id,
            approval_type="analysis",
            decision=approval_result,
        )
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="analysis",
        event="stage_completed",
        summary="analysis stage completed",
        details={"site": site},
    )
    if approval_result != "approved":
        return finalize_result(runtime_workspace=None)
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="planning",
        event="stage_started",
        summary="planning stage started",
        details={"site": site},
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
    if use_llm_roles:
        patch_proposal_path = write_llm_first_patch_proposal(
            source_root=source_root,
            analysis=analysis,
            codebase_map=codebase_map,
            recommended_outputs=recommended_outputs,
            llm_codebase_interpretation=llm_codebase_interpretation,
            output_path=run_root / "reports" / "patch-proposal.json",
            execution_output_path=run_root / "reports" / "llm-patch-proposal-execution.json",
            llm_factory=build_llm_patch_proposal_factory(provider=llm_provider, model=llm_model),
            provider=llm_provider,
            model=llm_model,
        )
    else:
        patch_proposal_path = write_patch_proposal(
            analysis=analysis,
            codebase_map=codebase_map,
            recommended_outputs=recommended_outputs,
            output_path=run_root / "reports" / "patch-proposal.json",
        )
    patch_proposal = json.loads(patch_proposal_path.read_text(encoding="utf-8"))
    append_execution_trace(
        report_root=run_root / "reports",
        event="patch_proposal_written",
        status="completed",
        run_id=run_id,
        related_files=[str(item.get("path") or "") for item in (patch_proposal.get("target_files") or [])],
    )
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="patch_proposal_written",
        message="patch proposal written",
        details={
            "path": str(patch_proposal_path),
            "target_count": len(patch_proposal.get("target_files") or []),
        },
    )
    for target in patch_proposal.get("target_files") or []:
        file_path = str(target.get("path") or "")
        if not file_path:
            continue
        update_file_activity(
            report_root=run_root / "reports",
            file_path=file_path,
            activity_type="selected_by",
            activity_value="patch_proposal",
        )
        _emit_terminal_log(
            terminal_logger,
            f"[patch_proposal] file={file_path} reason={str(target.get('reason') or 'unknown')} intent={str(target.get('intent') or 'unknown')}",
        )
    if use_llm_roles:
        _emit_latest_llm_usage(
            run_root=run_root,
            terminal_logger=terminal_logger,
            component="llm_patch_proposal",
        )
    planner_context = {
        "site": site,
        "analysis": analysis,
        "recommended_outputs": recommended_outputs,
        "evidence": _build_planning_evidence(analysis, recommended_outputs, manifest.status),
    }
    planner_message = _run_role_with_events("Planner", planner_context)
    _emit_role_log(
        terminal_logger=terminal_logger,
        runner=active_role_runner,
        role="Planner",
        message=planner_message,
    )
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
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="planning",
        event="stage_completed",
        summary="planning stage completed",
        details={"recommended_outputs": len(recommended_outputs)},
    )
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="generation",
        event="stage_started",
        summary="generation stage started",
        details={"site": site},
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
    generator_message = _run_role_with_events("Generator", generator_context)
    _emit_role_log(
        terminal_logger=terminal_logger,
        runner=active_role_runner,
        role="Generator",
        message=generator_message,
    )
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
    declared_files = list(generator_message.metadata.get("proposed_files") or [])
    declared_patches = list(generator_message.metadata.get("proposed_patches") or [])
    fallback_proposed_files = list(proposed_files)
    proposed_files = declared_files or proposed_files
    proposed_patches = declared_patches or proposed_patches
    proposed_files = _ensure_patch_companion_files(
        proposed_files=proposed_files,
        proposed_patches=proposed_patches,
        fallback_files=fallback_proposed_files,
    )
    _materialize_generator_proposals(
        run_root=run_root,
        proposed_files=proposed_files,
        proposed_patches=proposed_patches,
    )
    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=run_root / "reports" / "patch-proposal.json",
        output_path=run_root / "patches" / "proposed.patch",
    )
    if generate_llm_patch_draft:
        write_llm_patch_draft(
            source_root=source_root,
            analysis=analysis,
            codebase_map=codebase_map,
            patch_proposal=patch_proposal,
            output_path=run_root / "patches" / "llm-proposed.patch",
            llm_factory=llm_patch_factory
            or build_llm_patch_factory(provider=llm_provider, model=llm_model),
            provider=llm_provider,
            model=llm_model,
        )
        _emit_generation_log(
            run_root=run_root,
            terminal_logger=terminal_logger,
            component="orchestrator",
            event="llm_patch_draft_finished",
            message="llm patch draft artifact written",
            details={"path": str(run_root / "patches" / "llm-proposed.patch")},
        )
        _emit_terminal_log(
            terminal_logger,
            f"[llm_patch_draft] written path={run_root / 'patches' / 'llm-proposed.patch'}",
        )
        _emit_latest_llm_usage(
            run_root=run_root,
            terminal_logger=terminal_logger,
            component="llm_patch_draft",
        )
        write_patch_comparison_report(
            run_root=run_root,
            output_path=run_root / "reports" / "patch-comparison.json",
        )
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="generation",
        event="stage_completed",
        summary="generation stage completed",
        details={"proposed_files": len(proposed_files), "proposed_patches": len(proposed_patches)},
    )

    has_explicit_apply_decision = _has_explicit_approval_decision(
        decisions=approvals,
        approval_type="apply",
    )
    if bridge is not None and not has_explicit_apply_decision:
        apply_request = agent.request_apply_approval(
            summary="Overlay bundle is ready to apply",
            recommended_option="approve",
        )
        should_publish_apply_request = True
        if approval_store is not None:
            existing = approval_store.get_decision(run_id=run_id, approval_type="apply")
            if existing is None:
                approval_store.create_request(
                    run_id=run_id,
                    approval_type="apply",
                    blocked_job_id=str(apply_request.get("blocked_job_id") or ""),
                )
            else:
                should_publish_apply_request = existing["status"] == "pending"
        _publish_approval_requested_event(event_store, run_id, apply_request)
        if should_publish_apply_request:
            bridge.post_approval_request(
                run_id=run_id,
                approval_type=apply_request["approval_type"],
                summary="Overlay bundle is ready to apply",
                recommended_option="approve",
                risk_if_approved="runtime patch may fail",
                risk_if_rejected="run stops before validation",
                available_actions=["approve", "reject"],
            )
    elif not has_explicit_apply_decision:
        agent.request_apply_approval(
            summary="Overlay bundle is ready to apply",
            recommended_option="approve",
        )
        if approval_store is not None:
            approval_store.create_request(
                run_id=run_id,
                approval_type="apply",
                blocked_job_id=str(agent.pending_approval.get("blocked_job_id") if agent.pending_approval else ""),
            )
        _publish_approval_requested_event(event_store, run_id, agent.pending_approval)

    approval_result = _apply_approval_decision(
        agent=agent,
        approval_type="apply",
        decisions=approvals,
        approval_store=approval_store,
    )
    if bridge is not None and has_explicit_apply_decision and approval_result is not None:
        bridge.record_approval_decision(
            run_id=run_id,
            approval_type="apply",
            decision=approval_result,
        )
    if approval_result != "approved":
        return finalize_result(runtime_workspace=None)

    runtime_workspace = prepare_runtime_workspace(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_root=runtime_root,
    )
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="validation",
        event="stage_started",
        summary="validation stage started",
        details={"runtime_workspace": str(runtime_workspace)},
    )
    if generate_llm_patch_draft:
        _emit_generation_log(
            run_root=run_root,
            terminal_logger=terminal_logger,
            component="orchestrator",
            event="llm_patch_simulation_started",
            message="llm patch simulation started",
            details={"patch_artifact": "patches/llm-proposed.patch"},
        )
        simulate_candidate_patch_merge(
            manifest=manifest,
            generated_run_root=run_root,
            runtime_root=runtime_root,
            report_root=run_root / "reports",
            patch_artifact="patches/llm-proposed.patch",
            report_name="llm-patch-simulation.json",
        )
        llm_patch_simulation = json.loads((run_root / "reports" / "llm-patch-simulation.json").read_text(encoding="utf-8"))
        _emit_generation_log(
            run_root=run_root,
            terminal_logger=terminal_logger,
            component="orchestrator",
            event="llm_patch_simulation_completed",
            message="llm patch simulation completed",
            details={"passed": bool(llm_patch_simulation.get("passed")), "report": str(run_root / "reports" / "llm-patch-simulation.json")},
        )
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="merge_simulation_started",
        message="merge simulation started",
        details={"workspace": str(runtime_workspace)},
    )
    merge_simulation_path = simulate_runtime_merge(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_workspace=runtime_workspace,
        report_root=run_root / "reports",
    )
    if generate_llm_patch_draft:
        write_patch_comparison_report(
            run_root=run_root,
            output_path=run_root / "reports" / "patch-comparison.json",
        )
    merge_simulation = json.loads(merge_simulation_path.read_text(encoding="utf-8"))
    proposed_patch_simulation = simulate_candidate_patch_merge(
        manifest=manifest,
        generated_run_root=run_root,
        runtime_root=runtime_root,
        report_root=run_root / "reports",
        patch_artifact="patches/proposed.patch",
        report_name="proposed-patch-simulation.json",
    )
    proposed_patch_payload = json.loads(proposed_patch_simulation.read_text(encoding="utf-8"))
    if proposed_patch_payload.get("failed_patch_artifacts"):
        merge_simulation["failed_patch_artifacts"] = list(merge_simulation.get("failed_patch_artifacts") or []) + list(
            proposed_patch_payload.get("failed_patch_artifacts") or []
        )
        merge_simulation["passed"] = False
        merge_simulation_path.write_text(
            json.dumps(merge_simulation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="merge_simulation_completed",
        message="merge simulation completed",
        details={"passed": bool(merge_simulation.get("passed", True)), "report": str(merge_simulation_path)},
    )
    _emit_terminal_log(
        terminal_logger,
        f"[merge_simulation] passed={bool(merge_simulation.get('passed', True))} report={merge_simulation_path}",
    )
    if not merge_simulation.get("passed", True):
        agent.state = RunState.HUMAN_REVIEW_REQUIRED
        return finalize_result(runtime_workspace=runtime_workspace)
    _run_validation_evaluation_jobs(
        run_id=run_id,
        runtime_workspace=runtime_workspace,
        report_root=run_root / "reports",
        event_store=event_store,
    )
    if _read_runtime_failure_summary(run_root):
        repaired = _attempt_runtime_validation_repair(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            agent=agent,
        )
        if repaired:
            _run_validation_evaluation_jobs(
                run_id=run_id,
                runtime_workspace=runtime_workspace,
                report_root=run_root / "reports",
                event_store=event_store,
            )
    if _read_runtime_failure_summary(run_root):
        agent.state = RunState.HUMAN_REVIEW_REQUIRED
        return finalize_result(runtime_workspace=runtime_workspace)
    agent.mark_apply_completed()
    smoke_plan = load_smoke_plan(run_root)
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="smoke_tests_started",
        message="smoke tests started",
        details={"step_count": len(getattr(smoke_plan, "steps", []))},
    )
    smoke_results = _run_validation_with_retries(
        run_id=run_id,
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        smoke_plan=smoke_plan,
        agent=agent,
        bridge=bridge,
        role_runner=active_role_runner,
        event_store=event_store,
        terminal_logger=terminal_logger,
        run_role_with_events=_run_role_with_events,
        llm_runtime_repair_factory=llm_runtime_repair_factory,
        llm_provider=llm_provider,
        llm_model=llm_model,
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
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="smoke_tests_completed",
        message="smoke tests completed",
        details={"passed": bool(smoke_summary["passed"]), "failure_count": int(smoke_summary["failure_count"])},
    )
    if not smoke_summary["passed"]:
        return finalize_result(runtime_workspace=runtime_workspace)

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
    validator_message = _run_role_with_events("Validator", validator_context)
    _emit_role_log(
        terminal_logger=terminal_logger,
        runner=active_role_runner,
        role="Validator",
        message=validator_message,
    )

    agent.mark_validation_completed()
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="validation",
        event="stage_completed",
        summary="validation stage completed",
        details={"passed": bool(smoke_summary["passed"])},
    )

    has_explicit_export_decision = _has_explicit_approval_decision(
        decisions=approvals,
        approval_type="export",
    )
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
        if not has_explicit_export_decision:
            export_request, should_publish_export_request = _prepare_export_approval_request(
                agent=agent,
                run_id=run_id,
                approval_store=approval_store,
                event_store=event_store,
            )
            if should_publish_export_request:
                bridge.post_approval_request(
                    run_id=run_id,
                    approval_type=export_request["approval_type"],
                    summary="Export bundle is ready",
                    recommended_option="approve",
                    risk_if_approved="patch export may still need manual review",
                    risk_if_rejected="run remains local only",
                    available_actions=["approve", "reject"],
                )
    elif not has_explicit_export_decision:
        _prepare_export_approval_request(
            agent=agent,
            run_id=run_id,
            approval_store=approval_store,
            event_store=event_store,
        )

    approval_result = _apply_approval_decision(
        agent=agent,
        approval_type="export",
        decisions=approvals,
        approval_store=approval_store,
    )
    if bridge is not None and has_explicit_export_decision and approval_result is not None:
        bridge.record_approval_decision(
            run_id=run_id,
            approval_type="export",
            decision=approval_result,
        )
    if approval_result != "approved":
        return finalize_result(runtime_workspace=runtime_workspace)

    export_source, selected_patch_path = _select_export_source(run_root)
    strategy_provenance = {
        "backend_strategy": str(analysis.get("backend_strategy") or (analysis.get("framework") or {}).get("backend") or "unknown"),
        "frontend_strategy": str(analysis.get("frontend_strategy") or (analysis.get("framework") or {}).get("frontend") or "unknown"),
    }
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="export",
        event="stage_started",
        summary="export stage started",
        details={"export_source": export_source},
    )
    recovery_provenance = _read_recovery_provenance(run_root)
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="export_started",
        message="export started",
        details={"export_source": export_source},
    )
    if export_source == "llm" and selected_patch_path is not None:
        export_patch_artifact(
            patch_path=selected_patch_path,
            report_root=run_root / "reports",
            export_source="llm",
            strategy_provenance=strategy_provenance,
            recovery_provenance=recovery_provenance,
        )
    else:
        export_runtime_patch(
            source_root=source_root,
            runtime_workspace=runtime_workspace,
            report_root=run_root / "reports",
            strategy_provenance=strategy_provenance,
            recovery_provenance=recovery_provenance,
        )
    agent.mark_export_completed()
    _emit_stage_event(
        run_root=run_root,
        run_id=run_id,
        stage="export",
        event="stage_completed",
        summary="export stage completed",
        details={"export_source": export_source},
    )
    _emit_generation_log(
        run_root=run_root,
        terminal_logger=terminal_logger,
        component="orchestrator",
        event="export_completed",
        message="export completed",
        details={"export_source": export_source, "metadata_path": str(run_root / "reports" / "export-metadata.json")},
    )
    if enable_runtime_completion_loop and runtime_workspace is not None:
        completion_result = _run_runtime_completion_with_retries(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            source_root=Path(source_root),
            site=site,
            run_id=run_id,
            agent=agent,
            terminal_logger=terminal_logger,
            strategy_provenance=strategy_provenance,
            llm_runtime_repair_factory=llm_runtime_repair_factory,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        if not completion_result.get("passed", False):
            agent.state = RunState.HUMAN_REVIEW_REQUIRED
            return finalize_result(runtime_workspace=runtime_workspace)

    return finalize_result(runtime_workspace=runtime_workspace)


def _ensure_patch_companion_files(
    *,
    proposed_files: list[str],
    proposed_patches: list[str],
    fallback_files: list[str],
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in proposed_files:
        path = str(item or "").strip()
        if not path or path in seen:
            continue
        merged.append(path)
        seen.add(path)

    companion_map = {
        "patches/backend_chat_auth_route.patch": ["files/backend/chat_auth.py"],
        "patches/frontend_widget_mount.patch": [
            path
            for path in fallback_files
            if path.startswith("files/frontend/src/chatbot/SharedChatbotWidget.")
        ],
    }
    for patch_path in proposed_patches:
        for companion in companion_map.get(str(patch_path or "").strip(), []):
            path = str(companion or "").strip()
            if not path or path in seen:
                continue
            merged.append(path)
            seen.add(path)
    return merged


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


def _has_explicit_approval_decision(
    *,
    decisions: dict[str, str] | None,
    approval_type: str,
) -> bool:
    if decisions is None:
        return False
    value = decisions.get(approval_type)
    return value is not None and bool(str(value).strip())


def _prepare_export_approval_request(
    *,
    agent: AgentOrchestrator,
    run_id: str,
    approval_store: ApprovalStore | None,
    event_store: RedisRunJobStore | None,
) -> tuple[dict[str, Any], bool]:
    export_request = agent.request_export_approval(
        summary="Export bundle is ready",
        recommended_option="approve",
    )
    should_publish_export_request = True
    if approval_store is not None:
        existing = approval_store.get_decision(run_id=run_id, approval_type="export")
        if existing is None:
            approval_store.create_request(
                run_id=run_id,
                approval_type="export",
                blocked_job_id=str(export_request.get("blocked_job_id") or ""),
            )
        else:
            should_publish_export_request = existing["status"] == "pending"
    _publish_approval_requested_event(event_store, run_id, export_request)
    return export_request, should_publish_export_request


def _run_validation_with_retries(
    *,
    run_id: str,
    run_root: Path,
    runtime_workspace: Path,
    smoke_plan,
    agent: AgentOrchestrator,
    bridge: InMemorySlackBridge | None,
    role_runner: RoleRunner,
    terminal_logger: Callable[[str], None] | None = None,
    event_store: RedisRunJobStore | None = None,
    run_role_with_events: Callable[..., AgentMessage] | None = None,
    llm_runtime_repair_factory: Callable[[], Any] | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> list[dict]:
    recovery_attempts: list[RecoveryAttempt] = []
    seen_retry_signatures: set[str] = set()
    llm_repair_signatures: set[str] = set()
    server_state = _start_validation_runtime_servers(
        runtime_workspace=runtime_workspace,
        run_root=run_root,
    )
    try:
        while True:
            startup_failures = _build_validation_server_failure_results(server_state)
            if startup_failures:
                llm_repair_result = _attempt_llm_runtime_repair_cycle(
                    run_root=run_root,
                    runtime_workspace=runtime_workspace,
                    llm_runtime_repair_factory=llm_runtime_repair_factory,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    failure_signature="|".join(
                        str(result.get("stderr") or result.get("step_id") or "validation_runtime_failure")
                        for result in startup_failures
                    ),
                    evidence_payload={
                        "stage": "validation_startup",
                        "startup_failures": startup_failures,
                        "backend_probe": server_state.get("backend") or {},
                        "frontend_probe": server_state.get("frontend") or {},
                    },
                    attempt_id=f"validation-{agent.retry_count + 1}",
                )
                if llm_repair_result.get("applied"):
                    _stop_validation_runtime_servers(server_state)
                    server_state = _start_validation_runtime_servers(
                        runtime_workspace=runtime_workspace,
                        run_root=run_root,
                    )
                    continue
                return startup_failures
            break
        smoke_results = _run_smoke_tests_with_optional_recovery(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=smoke_plan,
        )
        while any(result.get("returncode") != 0 for result in smoke_results):
            failure_policy = _classify_failure_policy(smoke_results)
            failed_steps = failure_policy["failed_steps"]
            failure_signature = failure_policy["failure_signature"]
            if failure_signature not in llm_repair_signatures:
                llm_repair_result = _attempt_llm_runtime_repair_cycle(
                    run_root=run_root,
                    runtime_workspace=runtime_workspace,
                    llm_runtime_repair_factory=llm_runtime_repair_factory,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    failure_signature=failure_signature,
                    evidence_payload={
                        "stage": "validation_smoke",
                        "smoke_results": smoke_results,
                        "failed_steps": failed_steps,
                        "failure_summary": failure_policy["summary"],
                    },
                    attempt_id=f"validation-smoke-{agent.retry_count + 1}",
                )
                llm_repair_signatures.add(failure_signature)
                if llm_repair_result.get("applied"):
                    _stop_validation_runtime_servers(server_state)
                    server_state = _start_validation_runtime_servers(
                        runtime_workspace=runtime_workspace,
                        run_root=run_root,
                    )
                    startup_failures = _build_validation_server_failure_results(server_state)
                    if startup_failures:
                        return startup_failures
                    smoke_results = _run_smoke_tests_with_optional_recovery(
                        run_root=run_root,
                        runtime_workspace=runtime_workspace,
                        plan=smoke_plan,
                    )
                    continue
            if failure_policy["retryable"]:
                agent.mark_failure()
            else:
                agent.state = RunState.HUMAN_REVIEW_REQUIRED
            diagnoser_context = {
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
            }
            if run_role_with_events is not None:
                diagnoser_message = run_role_with_events(
                    "Diagnostician",
                    diagnoser_context,
                    job_started_payload={
                        "failure_signature": failure_signature,
                        "retryable": failure_policy["retryable"],
                    },
                    job_completed_payload={"retryable": failure_policy["retryable"]},
                )
            else:
                diagnoser_message = role_runner.run_role("Diagnostician", diagnoser_context)
            _write_diagnostic_report(
                run_root=run_root,
                diagnoser_message=diagnoser_message,
                failure_policy=failure_policy,
                retry_count=agent.retry_count,
                retry_budget=agent.retry_budget,
            )
            recovery_payload = build_recovery_plan(
                {
                    "failure_signature": str(diagnoser_message.metadata.get("failure_signature") or failure_signature),
                    "retry_count": agent.retry_count,
                    "retry_budget": agent.retry_budget,
                    "failed_results": [result for result in smoke_results if result.get("returncode") != 0],
                    "backend_evaluation": _read_json_if_exists(run_root / "reports" / "backend-evaluation.json") or {},
                    "frontend_evaluation": _read_json_if_exists(run_root / "reports" / "frontend-evaluation.json") or {},
                }
            )
            recovery_artifact_path = run_root / "reports" / "recovery-plan.json"
            recovery_artifact_path.write_text(
                json.dumps(recovery_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _emit_role_log(
                terminal_logger=terminal_logger,
                runner=role_runner,
                role="Diagnostician",
                message=diagnoser_message,
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

            should_retry = (
                failure_policy["retryable"]
                and bool(diagnoser_message.metadata.get("should_retry"))
                and bool(recovery_payload.get("should_retry"))
            )
            stop_reason: str | None = None
            if failure_signature in seen_retry_signatures:
                should_retry = False
                stop_reason = "duplicate_failure_signature"
                agent.state = RunState.HUMAN_REVIEW_REQUIRED
            elif not failure_policy["retryable"]:
                stop_reason = "non_retryable_failure"
            elif agent.state == RunState.HUMAN_REVIEW_REQUIRED:
                stop_reason = "retry_budget_exhausted"
            elif not bool(diagnoser_message.metadata.get("should_retry")):
                stop_reason = "diagnostician_declined_retry"
            elif not bool(recovery_payload.get("should_retry")):
                stop_reason = "recovery_plan_declined_retry"

            recovery_attempts.append(
                RecoveryAttempt(
                    retry_count=agent.retry_count,
                    failure_signature=str(diagnoser_message.metadata.get("failure_signature") or failure_signature),
                    classification=str(
                        diagnoser_message.metadata.get("classification")
                        or recovery_payload.get("classification")
                        or ""
                    )
                    or None,
                    should_retry=should_retry,
                    stop_reason=stop_reason,
                    recovery_artifact_path=str(recovery_artifact_path),
                )
            )
            _write_recovery_attempts(run_root=run_root, attempts=recovery_attempts)
            if not should_retry or agent.state == RunState.HUMAN_REVIEW_REQUIRED:
                return smoke_results

            seen_retry_signatures.add(failure_signature)
            if recovery_payload.get("repair_actions"):
                append_recovery_event(
                    report_root=run_root / "reports",
                    component="repair_loop",
                    source="recovered_llm",
                    recovery_reason=str(recovery_payload.get("classification") or ""),
                )
            write_recovered_smoke_plan(
                run_root=run_root,
                smoke_steps=[step.model_dump() for step in smoke_plan.steps],
                recovery_payload=recovery_payload,
            )
            agent.state = RunState.VALIDATING
            smoke_results = _run_smoke_tests_with_optional_recovery(
                run_root=run_root,
                runtime_workspace=runtime_workspace,
                plan=smoke_plan,
                recovery_payload=recovery_payload,
            )

        return smoke_results
    finally:
        _stop_validation_runtime_servers(server_state)


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


def _start_validation_runtime_servers(
    *,
    runtime_workspace: Path,
    run_root: Path,
) -> dict[str, Any]:
    backend_plan = _build_backend_probe_plan(runtime_workspace)
    frontend_plan = _build_frontend_probe_plan(runtime_workspace)
    return {
        "backend": _launch_validation_runtime_server(plan=backend_plan, probe_name="backend"),
        "frontend": _launch_validation_runtime_server(plan=frontend_plan, probe_name="frontend"),
        "reports_root": run_root / "reports",
    }


def _stop_validation_runtime_servers(server_state: dict[str, Any]) -> None:
    for probe_name in ("frontend", "backend"):
        payload = server_state.get(probe_name) or {}
        process = payload.get("process")
        if isinstance(process, subprocess.Popen):
            _terminate_process(process)


def _build_validation_server_failure_results(server_state: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for probe_name in ("backend", "frontend"):
        payload = server_state.get(probe_name) or {}
        if payload.get("passed"):
            continue
        failures.append(
            {
                "step": f"validation-{probe_name}-runtime",
                "step_id": f"validation-{probe_name}-runtime",
                "required": True,
                "category": "runtime",
                "timed_out": False,
                "returncode": 1,
                "stdout": str(payload.get("stdout") or ""),
                "stderr": f"{payload.get('failure_reason') or f'{probe_name}_server_boot_failed'}: {payload.get('stderr') or payload.get('readiness_error') or ''}".strip(),
                "request": {
                    "type": "runtime_server_start",
                    "url": str((payload.get("plan") or {}).get("readiness_url") or ""),
                },
                "response": {
                    "status": None,
                    "stdout": str(payload.get("stdout") or ""),
                    "stderr": str(payload.get("stderr") or ""),
                },
                "exports": {},
            }
        )
    return failures


def _launch_validation_runtime_server(
    *,
    plan: dict[str, Any],
    probe_name: str,
) -> dict[str, Any]:
    command = plan.get("command")
    readiness_url = str(plan.get("readiness_url") or "")
    readiness_method = str(plan.get("readiness_method") or "GET").upper()
    readiness_expected_statuses = {
        int(status)
        for status in (plan.get("readiness_expected_statuses") or [200])
    }
    working_directory = Path(str(plan.get("working_directory") or "."))
    if not command:
        return {
            "plan": plan,
            "process": None,
            "passed": True,
            "status": "skipped",
            "failure_reason": None,
            "stdout": "",
            "stderr": "",
            "readiness": None,
            "readiness_error": None,
        }

    try:
        process = _launch_server_process(
            command=list(command),
            cwd=working_directory,
            env=dict(plan.get("environment") or {}),
        )
    except OSError as exc:
        return {
            "plan": plan,
            "process": None,
            "passed": False,
            "status": "boot_failed",
            "failure_reason": f"{probe_name}_server_boot_failed",
            "stdout": "",
            "stderr": str(exc),
            "readiness": None,
            "readiness_error": None,
        }

    if process.poll() is not None:
        stdout, stderr = _collect_process_output(process)
        return {
            "plan": plan,
            "process": process,
            "passed": False,
            "status": "boot_failed",
            "failure_reason": _classify_probe_failure_reason(
                probe_name=probe_name,
                stdout=stdout,
                stderr=stderr,
                default_reason=f"{probe_name}_server_boot_failed",
            ),
            "stdout": stdout,
            "stderr": stderr,
            "readiness": None,
            "readiness_error": None,
        }

    readiness = _probe_http_ready(
        readiness_url,
        method=readiness_method,
        accepted_statuses=readiness_expected_statuses,
        timeout_seconds=int(plan.get("readiness_timeout_seconds") or 2),
        attempts=int(plan.get("readiness_attempts") or 10),
        delay_seconds=float(plan.get("readiness_delay_seconds") or 0.2),
    )
    if not readiness.get("passed"):
        _terminate_process(process)
        stdout, stderr = _collect_process_output(process)
        return {
            "plan": plan,
            "process": None,
            "passed": False,
            "status": "readiness_failed",
            "failure_reason": f"{probe_name}_readiness_failed",
            "stdout": stdout,
            "stderr": stderr,
            "readiness": readiness,
            "readiness_error": readiness.get("error"),
        }

    return {
        "plan": plan,
        "process": process,
        "passed": True,
        "status": "ready",
        "failure_reason": None,
        "stdout": "",
        "stderr": "",
        "readiness": readiness,
        "readiness_error": None,
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


def _run_validation_evaluation_jobs(
    *,
    run_id: str,
    runtime_workspace: Path,
    report_root: Path,
    event_store: RedisRunJobStore | None,
) -> dict[str, Path]:
    if event_store is None:
        return {
            "backend": evaluate_backend_workspace(
                runtime_workspace=runtime_workspace,
                report_root=report_root,
            ),
            "frontend": evaluate_frontend_workspace(
                runtime_workspace=runtime_workspace,
                report_root=report_root,
            ),
        }

    jobs = [
        JobRecord(
            job_id=f"{run_id}:BackendEvaluator:1",
            run_id=run_id,
            payload={
                "job_type": "backend_evaluation",
                "role": "BackendEvaluator",
                "context": {
                    "runtime_workspace": str(runtime_workspace),
                    "report_root": str(report_root),
                },
            },
        ),
        JobRecord(
            job_id=f"{run_id}:FrontendEvaluator:1",
            run_id=run_id,
            payload={
                "job_type": "frontend_evaluation",
                "role": "FrontendEvaluator",
                "context": {
                    "runtime_workspace": str(runtime_workspace),
                    "report_root": str(report_root),
                },
            },
        ),
    ]
    for job in jobs:
        event_store.create_job(job)
        event_store.enqueue_ready_job(job.job_id)

    executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "backend_evaluation": lambda context: {
            "report_path": str(
                evaluate_backend_workspace(
                    runtime_workspace=context["runtime_workspace"],
                    report_root=context["report_root"],
                )
            )
        },
        "frontend_evaluation": lambda context: {
            "report_path": str(
                evaluate_frontend_workspace(
                    runtime_workspace=context["runtime_workspace"],
                    report_root=context["report_root"],
                )
            )
        },
    }
    workers = [
        WorkerProcess(
            worker_id=f"validation-worker-{index}",
            store=event_store,
            redis_client=event_store.redis_client,
            role_runner=None,
            job_executors=executors,
        )
        for index in (1, 2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker.consume_once, 30) for worker in workers]
        for future in futures:
            future.result()

    return {
        "backend": Path(json.loads(event_store.get_job(jobs[0].job_id)["result"])["report_path"]),
        "frontend": Path(json.loads(event_store.get_job(jobs[1].job_id)["result"])["report_path"]),
    }


def _build_run_result(
    *,
    run_id: str,
    run_root: Path,
    runtime_workspace: Path | None,
    agent: AgentOrchestrator,
    bridge: InMemorySlackBridge | None,
    event_store: RedisRunJobStore | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_root": str(run_root),
        "runtime_workspace": str(runtime_workspace) if runtime_workspace is not None else None,
        "smoke_results_path": str(run_root / "reports" / "smoke-results.json"),
        "smoke_summary_path": str(run_root / "reports" / "smoke-summary.json"),
        "diagnostic_report_path": str(run_root / "reports" / "diagnostic-report.json"),
        "llm_role_execution_path": str(run_root / "reports" / "llm-role-execution.json"),
        "codebase_map_path": str(run_root / "reports" / "codebase-map.json"),
        "llm_codebase_interpretation_path": str(run_root / "reports" / "llm-codebase-interpretation.json"),
        "patch_proposal_path": str(run_root / "reports" / "patch-proposal.json"),
        "llm_patch_proposal_execution_path": str(run_root / "reports" / "llm-patch-proposal-execution.json"),
        "merge_simulation_path": str(run_root / "reports" / "merge-simulation.json"),
        "backend_evaluation_path": str(run_root / "reports" / "backend-evaluation.json"),
        "frontend_evaluation_path": str(run_root / "reports" / "frontend-evaluation.json"),
        "frontend_build_validation_path": str(run_root / "reports" / "frontend-build-validation.json"),
        "runtime_completion_path": str(run_root / "reports" / "runtime-completion.json"),
        "recovery_artifact_path": str(run_root / "reports" / "recovery-plan.json"),
        "recovery_attempts_path": str(run_root / "reports" / "recovery-attempts.json"),
        "recovered_smoke_plan_path": str(run_root / "reports" / "recovered-smoke-plan.json"),
        "proposed_patch_path": str(run_root / "patches" / "proposed.patch"),
        "llm_proposed_patch_path": str(run_root / "patches" / "llm-proposed.patch"),
        "llm_patch_simulation_path": str(run_root / "reports" / "llm-patch-simulation.json"),
        "patch_comparison_path": str(run_root / "reports" / "patch-comparison.json"),
        "export_metadata_path": str(run_root / "reports" / "export-metadata.json"),
        "onboarding_event_log_path": str(run_root / "reports" / "execution-trace.jsonl"),
        "execution_trace_path": str(run_root / "reports" / "execution-trace.jsonl"),
        "generation_log_path": str(run_root / "reports" / "generation.log"),
        "file_activity_path": str(run_root / "reports" / "file-activity.json"),
        "llm_usage_path": str(run_root / "reports" / "llm-usage.json"),
        "run_event_stream": _run_event_stream_key(run_id) if event_store else None,
        "slack_message_count": len(bridge.messages) if bridge is not None else 0,
        "current_state": agent.state.value,
        "pending_approval": agent.pending_approval,
        "blocked_jobs": dict(agent.blocked_jobs),
        "final_recovery_source": _read_recovery_provenance(run_root).get("final_recovery_source"),
        "runtime_failure_summary": _read_runtime_failure_summary(run_root),
    }
    if bridge is not None:
        bridge.post_run_summary(
            run_id=agent.run_id,
            current_state=agent.state.value,
            pending_approval=agent.pending_approval,
            artifacts=_existing_summary_artifacts(run_root),
        )
        result["slack_message_count"] = len(bridge.messages)
    return result


def _run_event_stream_key(run_id: str) -> str:
    return f"onboarding:events:{run_id}"


def _write_recovery_attempts(*, run_root: Path, attempts: list[RecoveryAttempt]) -> None:
    path = run_root / "reports" / "recovery-attempts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([attempt.model_dump() for attempt in attempts], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _reserve_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    try:
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _read_site_from_run_root(*, run_root: Path, runtime_workspace: Path) -> str:
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        site = str(payload.get("site") or "").strip()
        if site:
            return site
    return runtime_workspace.parent.parent.name


def _rewrite_url_to_runtime_port(url: str | None, *, ports: dict[str, int]) -> str | None:
    if not url:
        return url
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if hostname not in {"127.0.0.1", "localhost"}:
        return url
    if parsed.port == 8000:
        netloc = f"{hostname}:{ports['backend']}"
    elif parsed.port == 8100:
        netloc = f"{hostname}:{ports['chatbot']}"
    elif parsed.port == 3000 and "frontend" in ports:
        netloc = f"{hostname}:{ports['frontend']}"
    else:
        return url
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _rewrite_smoke_value_for_runtime(value: Any, *, ports: dict[str, int]) -> Any:
    if isinstance(value, str):
        return _rewrite_url_to_runtime_port(value, ports=ports)
    if isinstance(value, dict):
        return {key: _rewrite_smoke_value_for_runtime(item, ports=ports) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_smoke_value_for_runtime(item, ports=ports) for item in value]
    return value


def _rewrite_smoke_plan_for_runtime(*, plan: SmokeTestPlan, ports: dict[str, int]) -> SmokeTestPlan:
    steps: list[dict[str, Any]] = []
    for step in plan.steps:
        step_payload = step.model_dump()
        for field in ("url", "headers", "body", "query", "env"):
            step_payload[field] = _rewrite_smoke_value_for_runtime(step_payload.get(field), ports=ports)
        steps.append(step_payload)
    return SmokeTestPlan(steps=steps)


def _smoke_plan_requires_frontend(plan: SmokeTestPlan) -> bool:
    return any(":3000" in str(step.url or "") for step in plan.steps)


def _start_smoke_runtime_process(*, plan: dict[str, Any], probe_name: str) -> tuple[subprocess.Popen[str] | None, dict[str, Any] | None]:
    command = plan.get("command")
    readiness_url = str(plan.get("readiness_url") or "")
    readiness_method = str(plan.get("readiness_method") or "GET").upper()
    readiness_expected_statuses = {
        int(status)
        for status in (plan.get("readiness_expected_statuses") or [200])
    }
    working_directory = Path(str(plan.get("working_directory") or "."))

    if not command:
        return None, {
            "step": "smoke-runtime-stack",
            "step_id": "smoke-runtime-stack",
            "strategy": "runtime_isolation",
            "required": True,
            "category": "runtime",
            "timed_out": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"{probe_name} command missing for isolated smoke runtime",
            "request": {},
            "response": {"status": None, "headers": {}, "body": ""},
            "exports": {},
        }

    try:
        process = _launch_server_process(
            command=list(command),
            cwd=working_directory,
            env=dict(plan.get("environment") or {}),
        )
    except OSError as exc:
        return None, {
            "step": "smoke-runtime-stack",
            "step_id": "smoke-runtime-stack",
            "strategy": "runtime_isolation",
            "required": True,
            "category": "runtime",
            "timed_out": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"{probe_name} boot failed: {exc}",
            "request": {},
            "response": {"status": None, "headers": {}, "body": ""},
            "exports": {},
        }

    if process.poll() is not None:
        stdout, stderr = _collect_process_output(process)
        failure_reason = _classify_probe_failure_reason(
            probe_name=probe_name,
            stdout=stdout,
            stderr=stderr,
            default_reason=f"{probe_name}_server_boot_failed",
        )
        return None, {
            "step": "smoke-runtime-stack",
            "step_id": "smoke-runtime-stack",
            "strategy": "runtime_isolation",
            "required": True,
            "category": "runtime",
            "timed_out": False,
            "returncode": 1,
            "stdout": stdout,
            "stderr": f"{probe_name} boot failed: {failure_reason}\n{stderr}".strip(),
            "request": {},
            "response": {"status": None, "headers": {}, "body": ""},
            "exports": {},
        }

    readiness = _probe_http_ready(
        readiness_url,
        method=readiness_method,
        accepted_statuses=readiness_expected_statuses,
        timeout_seconds=int(plan.get("readiness_timeout_seconds") or 2),
        attempts=int(plan.get("readiness_attempts") or 10),
        delay_seconds=float(plan.get("readiness_delay_seconds") or 0.2),
    )
    if readiness.get("passed"):
        return process, None

    _terminate_process(process)
    stdout, stderr = _collect_process_output(process)
    return None, {
        "step": "smoke-runtime-stack",
        "step_id": "smoke-runtime-stack",
        "strategy": "runtime_isolation",
        "required": True,
        "category": "runtime",
        "timed_out": False,
        "returncode": 1,
        "stdout": stdout,
        "stderr": (
            f"{probe_name} readiness failed for {readiness_url}: "
            f"{readiness.get('error') or 'unknown error'}\n{stderr}"
        ).strip(),
        "request": {},
        "response": {"status": readiness.get("status_code"), "headers": {}, "body": ""},
        "exports": {},
    }


def _run_smoke_tests_in_isolated_runtime(
    *,
    run_root: Path,
    runtime_workspace: Path,
    plan: SmokeTestPlan,
    recovery_payload: dict[str, Any] | None = None,
) -> list[dict]:
    site = _read_site_from_run_root(run_root=run_root, runtime_workspace=runtime_workspace)
    ports = {
        "backend": _reserve_loopback_port(),
        "chatbot": _reserve_loopback_port(),
    }
    if _smoke_plan_requires_frontend(plan):
        ports["frontend"] = _reserve_loopback_port()

    backend_base_url = f"http://127.0.0.1:{ports['backend']}"
    backend_plan = _build_backend_probe_plan(runtime_workspace, port=ports["backend"])
    chatbot_plan = _build_chatbot_probe_plan(
        runtime_workspace,
        site=site,
        port=ports["chatbot"],
        backend_base_url=backend_base_url,
    )
    frontend_plan = None
    if "frontend" in ports:
        frontend_plan = _build_frontend_probe_plan(
            runtime_workspace,
            chatbot_plan=chatbot_plan,
            port=ports["frontend"],
        )

    required_plans = [backend_plan, chatbot_plan]
    if frontend_plan is not None:
        required_plans.append(frontend_plan)
    if any(not plan_item.get("command") for plan_item in required_plans):
        try:
            return run_smoke_tests(
                run_root=run_root,
                runtime_workspace=runtime_workspace,
                plan=plan,
                recovery_payload=recovery_payload,
            )
        except TypeError as exc:
            if "recovery_payload" not in str(exc):
                raise
            return run_smoke_tests(
                run_root=run_root,
                runtime_workspace=runtime_workspace,
                plan=plan,
            )

    launched_processes: list[subprocess.Popen[str]] = []
    for probe_name, probe_plan in [("backend", backend_plan), ("chatbot", chatbot_plan), ("frontend", frontend_plan)]:
        if probe_plan is None:
            continue
        process, failure = _start_smoke_runtime_process(plan=probe_plan, probe_name=probe_name)
        if failure is not None:
            for launched_process in reversed(launched_processes):
                _terminate_process(launched_process)
            return [failure]
        assert process is not None
        launched_processes.append(process)

    isolated_plan = _rewrite_smoke_plan_for_runtime(plan=plan, ports=ports)
    try:
        return run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=isolated_plan,
            recovery_payload=recovery_payload,
        )
    except TypeError as exc:
        if "recovery_payload" not in str(exc):
            raise
        return run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=isolated_plan,
        )
    finally:
        for process in reversed(launched_processes):
            _terminate_process(process)


def _run_smoke_tests_with_optional_recovery(
    *,
    run_root: Path,
    runtime_workspace: Path,
    plan,
    recovery_payload: dict[str, Any] | None = None,
) -> list[dict]:
    return _run_smoke_tests_in_isolated_runtime(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=plan,
        recovery_payload=recovery_payload,
    )


def _read_recovery_provenance(run_root: Path) -> dict[str, str]:
    attempts_path = run_root / "reports" / "recovery-attempts.json"
    recovery_artifact_path = run_root / "reports" / "recovery-plan.json"
    final_recovery_source = ""
    if attempts_path.exists():
        attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
        if attempts:
            final_recovery_source = str(attempts[-1].get("classification") or "")
    if not final_recovery_source and recovery_artifact_path.exists():
        recovery_payload = json.loads(recovery_artifact_path.read_text(encoding="utf-8"))
        final_recovery_source = str(recovery_payload.get("classification") or "")
    return {
        "recovery_artifact_path": str(recovery_artifact_path),
        "final_recovery_source": final_recovery_source,
    }


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _attempt_runtime_validation_repair(
    *,
    run_root: Path,
    runtime_workspace: Path,
    agent: AgentOrchestrator,
) -> bool:
    backend_evaluation = _read_json_if_exists(run_root / "reports" / "backend-evaluation.json") or {}
    frontend_evaluation = _read_json_if_exists(run_root / "reports" / "frontend-evaluation.json") or {}
    recovery_payload = build_recovery_plan(
        {
            "failure_signature": "runtime_validation_failure",
            "retry_count": agent.retry_count,
            "retry_budget": agent.retry_budget,
            "failed_results": [],
            "backend_evaluation": backend_evaluation,
            "frontend_evaluation": frontend_evaluation,
        }
    )
    recovery_artifact_path = run_root / "reports" / "recovery-plan.json"
    recovery_artifact_path.write_text(
        json.dumps(recovery_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not recovery_payload.get("should_retry") or not recovery_payload.get("repair_actions"):
        append_recovery_event(
            report_root=run_root / "reports",
            component="repair_loop",
            source="hard_fallback",
            hard_fallback_reason=str(recovery_payload.get("classification") or "runtime_validation_failure"),
        )
        return False

    applied = _apply_repair_actions(
        runtime_workspace=runtime_workspace,
        recovery_payload=recovery_payload,
        backend_evaluation=backend_evaluation,
    )
    append_recovery_event(
        report_root=run_root / "reports",
        component="repair_loop",
        source="recovered_llm" if applied else "hard_fallback",
        recovery_reason=str(recovery_payload.get("classification") or "") if applied else None,
        hard_fallback_reason=None if applied else str(recovery_payload.get("classification") or "runtime_validation_failure"),
    )
    if applied:
        attempts = [
            RecoveryAttempt(
                retry_count=agent.retry_count,
                failure_signature="runtime_validation_failure",
                classification=str(recovery_payload.get("classification") or "") or None,
                should_retry=True,
                stop_reason=None,
                recovery_artifact_path=str(recovery_artifact_path),
            )
        ]
        _write_recovery_attempts(run_root=run_root, attempts=attempts)
    return applied


def _run_runtime_completion_with_retries(
    *,
    run_root: Path,
    runtime_workspace: Path,
    source_root: Path,
    site: str,
    run_id: str,
    agent: AgentOrchestrator,
    terminal_logger: Callable[[str], None] | None,
    strategy_provenance: dict[str, str],
    llm_runtime_repair_factory: Callable[[], Any] | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    backend_evaluation = _read_json_if_exists(run_root / "reports" / "backend-evaluation.json") or {}
    frontend_evaluation = _read_json_if_exists(run_root / "reports" / "frontend-evaluation.json") or {}
    retry_budget = max(1, agent.retry_budget - agent.retry_count)
    attempts_payload: list[dict[str, Any]] = []
    latest_result: dict[str, Any] = {
        "passed": False,
        "failure_reason": "runtime_completion_not_started",
    }

    for attempt_index in range(1, retry_budget + 1):
        latest_result = run_runtime_completion(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            site=site,
            run_id=run_id,
            terminal_logger=terminal_logger,
        )
        attempt_record: dict[str, Any] = {
            "attempt": attempt_index,
            "passed": bool(latest_result.get("passed", False)),
            "failure_reason": latest_result.get("failure_reason"),
            "backend_probe_status": (latest_result.get("backend_probe") or {}).get("status"),
            "frontend_probe_status": (latest_result.get("frontend_probe") or {}).get("status"),
            "mount_probe_passed": (latest_result.get("mount_probe") or {}).get("passed"),
        }
        attempts_payload.append(attempt_record)
        if latest_result.get("passed", False):
            recovery_provenance = _read_recovery_provenance(run_root)
            if attempts_payload and attempts_payload[-1].get("classification"):
                recovery_provenance = {
                    **recovery_provenance,
                    "final_recovery_source": str(attempts_payload[-1]["classification"]),
                }
            export_runtime_patch(
                source_root=source_root,
                runtime_workspace=runtime_workspace,
                report_root=run_root / "reports",
                strategy_provenance=strategy_provenance,
                recovery_provenance=recovery_provenance,
            )
            _write_runtime_completion_attempts(run_root=run_root, attempts=attempts_payload)
            return latest_result

        recovery_payload = build_recovery_plan(
            {
                "failure_signature": str(latest_result.get("failure_reason") or "runtime_completion_failed"),
                "retry_count": attempt_index - 1,
                "retry_budget": retry_budget,
                "failed_results": [],
                "backend_evaluation": backend_evaluation,
                "frontend_evaluation": frontend_evaluation,
            }
        )
        attempt_record["classification"] = recovery_payload.get("classification")
        attempt_record["should_retry"] = recovery_payload.get("should_retry", False)
        attempt_record["repair_actions"] = recovery_payload.get("repair_actions") or []

        llm_repair_result = _attempt_llm_runtime_repair_cycle(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            llm_runtime_repair_factory=llm_runtime_repair_factory,
            llm_provider=llm_provider,
            llm_model=llm_model,
            failure_signature=str(latest_result.get("failure_reason") or "runtime_completion_failed"),
            evidence_payload={
                "stage": "runtime_completion",
                "result": latest_result,
                "classification": recovery_payload.get("classification"),
            },
            attempt_id=f"runtime-completion-{attempt_index}",
        )
        attempt_record["llm_repair_applied"] = bool(llm_repair_result.get("applied"))
        attempt_record["llm_repair_patch_path"] = llm_repair_result.get("patch_path")
        if llm_repair_result.get("applied"):
            continue

        if not recovery_payload.get("should_retry", False):
            break
        applied = _apply_repair_actions(
            runtime_workspace=runtime_workspace,
            recovery_payload=recovery_payload,
            backend_evaluation=backend_evaluation,
            runtime_completion_result=latest_result,
        )
        attempt_record["repair_applied"] = applied
        if not applied:
            break

    _write_runtime_completion_attempts(run_root=run_root, attempts=attempts_payload)
    return latest_result


def _write_runtime_completion_attempts(*, run_root: Path, attempts: list[dict[str, Any]]) -> None:
    path = run_root / "reports" / "runtime-completion-attempts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(attempts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _attempt_llm_runtime_repair_cycle(
    *,
    run_root: Path,
    runtime_workspace: Path,
    llm_runtime_repair_factory: Callable[[], Any] | None,
    llm_provider: str | None,
    llm_model: str | None,
    failure_signature: str,
    evidence_payload: dict[str, Any],
    attempt_id: str,
) -> dict[str, Any]:
    return attempt_llm_runtime_repair(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        failure_signature=failure_signature,
        evidence_payload=evidence_payload,
        attempt_id=attempt_id,
        llm_factory=llm_runtime_repair_factory,
        provider=llm_provider,
        model=llm_model,
    )


def _apply_repair_actions(
    *,
    runtime_workspace: Path,
    recovery_payload: dict[str, Any],
    backend_evaluation: dict[str, Any],
    runtime_completion_result: dict[str, Any] | None = None,
) -> bool:
    applied = False
    for action in recovery_payload.get("repair_actions") or []:
        action_name = str(action.get("action") or "")
        if action_name == "create_chat_auth_module":
            framework = str(action.get("framework") or backend_evaluation.get("framework") or "unknown")
            target_path = runtime_workspace / str(action.get("target_path") or "backend/chat_auth.py")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(_build_runtime_chat_auth_stub(framework), encoding="utf-8")
            applied = True
        elif action_name == "repair_frontend_mount_target":
            applied = _repair_frontend_mount_target(runtime_workspace) or applied
        elif action_name == "repair_shared_widget_import":
            applied = _repair_shared_widget_import(runtime_workspace) or applied
        elif action_name == "repair_backend_entrypoint":
            applied = _repair_backend_entrypoint(
                runtime_workspace=runtime_workspace,
                runtime_completion_result=runtime_completion_result,
            ) or applied
    return applied


def _build_runtime_chat_auth_stub(framework: str) -> str:
    if framework == "flask":
        return (
            'from flask import Blueprint, jsonify\n\n'
            'chat_auth_bp = Blueprint("chat_auth", __name__)\n\n'
            '@chat_auth_bp.route("/api/chat/auth-token", methods=["POST"])\n'
            'def chat_auth_token():\n'
            '    return jsonify({"authenticated": True, "access_token": "runtime-token"})\n'
        )
    if framework == "fastapi":
        return (
            "from fastapi import APIRouter\n\n"
            'router = APIRouter(tags=["chat-auth"])\n\n'
            '@router.post("/api/chat/auth-token")\n'
            "def chat_auth_token():\n"
            '    return {"authenticated": True, "access_token": "runtime-token"}\n'
        )
    return (
        "from django.http import JsonResponse\n\n"
        "def chat_auth_token(request):\n"
        '    return JsonResponse({"authenticated": True, "access_token": "runtime-token"})\n'
    )


def _repair_frontend_mount_target(runtime_workspace: Path) -> bool:
    frontend_src = runtime_workspace / "frontend" / "src"
    if not frontend_src.exists():
        frontend_src = runtime_workspace / "src"
    frontend_src.mkdir(parents=True, exist_ok=True)

    widget_path = frontend_src / "chatbot" / "SharedChatbotWidget.jsx"
    widget_path.parent.mkdir(parents=True, exist_ok=True)
    if not widget_path.exists():
        widget_path.write_text(
            "export default function SharedChatbotWidget() {\n"
            '  return <div data-chatbot-status="authenticated">Chat ready</div>;\n'
            "}\n",
            encoding="utf-8",
        )

    mount_candidates = [
        frontend_src / "App.js",
        frontend_src / "App.jsx",
        frontend_src / "main.jsx",
        frontend_src / "main.js",
    ]
    mount_path = next((path for path in mount_candidates if path.exists()), frontend_src / "App.js")
    content = mount_path.read_text(encoding="utf-8") if mount_path.exists() else ""
    if 'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";' not in content:
        content = 'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n' + content
    if "<SharedChatbotWidget />" not in content:
        if "return <main>Home</main>;" in content:
            content = content.replace(
                "return <main>Home</main>;",
                "return <><main>Home</main><SharedChatbotWidget /></>;",
            )
        elif "return null;" in content:
            content = content.replace("return null;", "return <SharedChatbotWidget />;")
        else:
            content = content.rstrip() + "\n\nexport function RuntimeCompletionMountRepair() { return <SharedChatbotWidget />; }\n"
    mount_path.write_text(content, encoding="utf-8")
    return True


def _repair_shared_widget_import(runtime_workspace: Path) -> bool:
    frontend_src = runtime_workspace / "frontend" / "src"
    if not frontend_src.exists():
        frontend_src = runtime_workspace / "src"
    if not frontend_src.exists():
        return False

    repaired = False
    for widget_path in frontend_src.rglob("SharedChatbotWidget.*"):
        if not widget_path.is_file():
            continue
        content = widget_path.read_text(encoding="utf-8", errors="ignore")
        if '@shared-chatbot/ChatbotWidget' not in content:
            continue
        sibling_widget_path = widget_path.with_name("ChatbotWidget.jsx")
        if not sibling_widget_path.exists():
            sibling_widget_path.write_text(
                "export function HostedChatbotWidget() {\n"
                '  return <div data-chatbot-status="authenticated">Chat ready</div>;\n'
                "}\n\n"
                "export default HostedChatbotWidget;\n",
                encoding="utf-8",
            )
        repaired = rewrite_javascript_module_specifier(
            file_path=widget_path,
            broken_import='@shared-chatbot/ChatbotWidget',
            replacement_import='./ChatbotWidget',
        ) or repaired
    return repaired


def _repair_backend_entrypoint(
    *,
    runtime_workspace: Path,
    runtime_completion_result: dict[str, Any] | None,
) -> bool:
    backend_probe = (runtime_completion_result or {}).get("backend_probe") or {}
    stderr = str(backend_probe.get("stderr") or "")
    if not stderr.strip():
        return False

    repair_result = repair_python_import_from_traceback(
        workspace_root=runtime_workspace,
        stderr=stderr,
    )
    return bool(repair_result.get("applied", False))


def _publish_run_event(
    event_store: RedisRunJobStore | None,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if event_store is None:
        return
    event_store.append_event(
        RunEventRecord(
            run_id=run_id,
            event=event_type,
            payload=payload,
        )
    )


def _publish_job_event(
    event_store: RedisRunJobStore | None,
    run_id: str,
    job_id: str,
    role: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    data: dict[str, Any] = {"role": role, "job_id": job_id}
    if payload:
        data.update(payload)
    _publish_run_event(event_store, run_id, event_type, data)


def _publish_approval_requested_event(
    event_store: RedisRunJobStore | None,
    run_id: str,
    approval_payload: dict[str, Any] | None,
) -> None:
    if approval_payload is None:
        return
    _publish_run_event(
        event_store,
        run_id,
        "approval.requested",
        dict(approval_payload),
    )


def _existing_summary_artifacts(run_root: Path) -> dict[str, Path]:
    candidates = {
        "llm_role_execution": run_root / "reports" / "llm-role-execution.json",
        "llm_codebase_interpretation": run_root / "reports" / "llm-codebase-interpretation.json",
        "llm_patch_proposal_execution": run_root / "reports" / "llm-patch-proposal-execution.json",
        "patch_proposal": run_root / "reports" / "patch-proposal.json",
        "proposed_patch": run_root / "patches" / "proposed.patch",
        "llm_proposed_patch": run_root / "patches" / "llm-proposed.patch",
        "llm_patch_simulation": run_root / "reports" / "llm-patch-simulation.json",
        "patch_comparison": run_root / "reports" / "patch-comparison.json",
        "merge_simulation": run_root / "reports" / "merge-simulation.json",
        "backend_evaluation": run_root / "reports" / "backend-evaluation.json",
        "frontend_evaluation": run_root / "reports" / "frontend-evaluation.json",
        "frontend_build_validation": run_root / "reports" / "frontend-build-validation.json",
        "export_metadata": run_root / "reports" / "export-metadata.json",
        "execution_trace": run_root / "reports" / "execution-trace.jsonl",
        "file_activity": run_root / "reports" / "file-activity.json",
        "llm_usage": run_root / "reports" / "llm-usage.json",
    }
    return {
        key: path
        for key, path in candidates.items()
        if path.exists()
    }


def _read_runtime_failure_summary(run_root: Path) -> dict[str, str]:
    summary: dict[str, str] = {}

    backend_path = run_root / "reports" / "backend-evaluation.json"
    if backend_path.exists():
        try:
            backend_payload = json.loads(backend_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backend_payload = {}
        if backend_payload and not backend_payload.get("passed", True):
            reason = str(backend_payload.get("failure_reason") or "").strip()
            if not reason:
                failed_files = backend_payload.get("failed_files") or []
                reason = f"backend evaluation failed ({len(failed_files)} files)" if failed_files else "backend evaluation failed"
            summary["backend"] = reason
        backend_bootstrap = backend_payload.get("backend_bootstrap") or {}
        if backend_bootstrap.get("bootstrap_attempted") and not backend_bootstrap.get("bootstrap_passed", False):
            reason = str(backend_bootstrap.get("bootstrap_failure_reason") or "").strip()
            if reason:
                summary["backend"] = reason

    frontend_eval_path = run_root / "reports" / "frontend-evaluation.json"
    if frontend_eval_path.exists():
        try:
            frontend_payload = json.loads(frontend_eval_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            frontend_payload = {}
        if frontend_payload and not frontend_payload.get("passed", True):
            reason = str(frontend_payload.get("failure_reason") or "").strip()
            if not reason:
                artifact = frontend_payload.get("frontend_artifact") or {}
                errors = artifact.get("validation_errors") or frontend_payload.get("validation_errors") or []
                if errors:
                    reason = str(errors[0])
                else:
                    reason = "frontend evaluation failed"
            summary["frontend"] = reason
    frontend_build_path = run_root / "reports" / "frontend-build-validation.json"
    if frontend_build_path.exists():
        try:
            frontend_build_payload = json.loads(frontend_build_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            frontend_build_payload = {}
        reason = str(frontend_build_payload.get("bootstrap_failure_reason") or "").strip()
        if reason:
            summary["frontend"] = reason

    completion_path = run_root / "reports" / "runtime-completion.json"
    if completion_path.exists():
        try:
            completion_payload = json.loads(completion_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            completion_payload = {}
        if completion_payload and not completion_payload.get("passed", True):
            reason = str(completion_payload.get("failure_reason") or "").strip()
            if reason:
                summary["completion"] = reason

    return summary


def _write_llm_role_execution_report(*, run_root: Path, runner: Any) -> None:
    execution_log = getattr(runner, "execution_log", None)
    if not execution_log:
        return
    payload = {
        "roles": execution_log,
    }
    (run_root / "reports" / "llm-role-execution.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_llm_debug_artifacts(*, run_root: Path, runner: Any) -> None:
    writer = getattr(runner, "write_debug_artifacts", None)
    if writer is None:
        return
    writer(run_root / "reports")


def _select_export_source(run_root: Path) -> tuple[str, Path | None]:
    comparison_path = run_root / "reports" / "patch-comparison.json"
    if not comparison_path.exists():
        return ("runtime", None)

    payload = json.loads(comparison_path.read_text(encoding="utf-8"))
    if payload.get("recommended_source") != "llm":
        return ("runtime", None)

    simulation = payload.get("simulation") or {}
    if not bool(simulation.get("llm_passed")):
        return ("runtime", None)

    llm_patch_path = run_root / "patches" / "llm-proposed.patch"
    if not llm_patch_path.exists():
        return ("runtime", None)
    return ("llm", llm_patch_path)


def _emit_terminal_log(
    logger: Callable[[str], None] | None,
    message: str,
) -> None:
    if logger is None:
        return
    logger(message)


def _emit_generation_log(
    *,
    run_root: Path,
    terminal_logger: Callable[[str], None] | None,
    component: str,
    event: str,
    message: str,
    level: str = "INFO",
    details: dict[str, Any] | None = None,
) -> None:
    append_generation_log(
        report_root=run_root / "reports",
        level=level,
        component=component,
        event=event,
        message=message,
        details=details,
    )
    rendered_details = ""
    if details:
        rendered_details = " " + " ".join(f"{key}={value}" for key, value in details.items() if value is not None)
    _emit_terminal_log(terminal_logger, f"[{component}] {event} {message}{rendered_details}")


def _emit_stage_event(
    *,
    run_root: Path,
    run_id: str,
    stage: str,
    event: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    append_onboarding_event(
        report_root=run_root / "reports",
        run_id=run_id,
        component="orchestrator",
        stage=stage,
        event=event,
        severity="info",
        summary=summary,
        source="system",
        details=details,
    )


def _emit_role_log(
    *,
    terminal_logger: Callable[[str], None] | None,
    runner: Any,
    role: str,
    message: Any,
) -> None:
    execution = getattr(runner, "execution_log", {}).get(role, {})
    debug_payload = getattr(runner, "debug_log", {}).get(role, {})
    source = execution.get("source") or "deterministic"
    fallback_reason = execution.get("fallback_reason") or "none"
    _emit_terminal_log(
        terminal_logger,
        f"[role:{role}] source={source} fallback_reason={fallback_reason} claim={message.claim}",
    )
    usage = debug_payload.get("usage") or {}
    total_tokens = int(usage.get("total_tokens") or 0)
    if total_tokens > 0:
        _emit_terminal_log(
            terminal_logger,
            "[llm_usage] "
            f"component=role:{role} input={int(usage.get('input_tokens') or 0)} "
            f"output={int(usage.get('output_tokens') or 0)} "
            f"cached={int(usage.get('cached_input_tokens') or 0)} "
            f"total={total_tokens}",
        )


def _format_llm_codebase_log(payload: dict[str, Any]) -> str:
    ranked_candidates = payload.get("ranked_candidates") or []
    top_candidate = ranked_candidates[0]["path"] if ranked_candidates else "none"
    return (
        "[llm_codebase] "
        f"source={payload.get('source') or 'fallback'} "
        f"fallback_reason={payload.get('fallback_reason') or 'none'} "
        f"top_candidate={top_candidate}"
    )


def _emit_latest_llm_usage(
    *,
    run_root: Path,
    terminal_logger: Callable[[str], None] | None,
    component: str,
) -> None:
    usage_path = run_root / "reports" / "llm-usage.json"
    if terminal_logger is None or not usage_path.exists():
        return
    try:
        payload = json.loads(usage_path.read_text(encoding="utf-8"))
    except Exception:
        return
    calls = payload.get("calls") or []
    for item in reversed(calls):
        if item.get("component") != component:
            continue
        _emit_terminal_log(
            terminal_logger,
            "[llm_usage] "
            f"component={component} input={int(item.get('input_tokens') or 0)} "
            f"output={int(item.get('output_tokens') or 0)} "
            f"cached={int(item.get('cached_input_tokens') or 0)} "
            f"total={int(item.get('total_tokens') or 0)} "
            f"estimated_total=${float(item.get('estimated_total_cost_usd') or 0.0):.6f}",
        )
        return


def _build_analysis_evidence(analysis: dict[str, Any]) -> list[str]:
    auth = analysis.get("auth") or {}
    framework = analysis.get("framework") or {}
    return [
        f"백엔드 프레임워크: {framework.get('backend', 'unknown')}",
        f"프론트엔드 프레임워크: {framework.get('frontend', 'unknown')}",
        f"인증 방식: {auth.get('auth_style', 'unknown')}",
        f"인증 신호: {auth.get('signals') or []}",
        f"로그인 엔트리포인트: {auth.get('login_entrypoints') or []}",
        f"내 정보 엔트리포인트: {auth.get('me_entrypoints') or []}",
        f"백엔드 엔트리포인트: {analysis.get('backend_entrypoints') or []}",
        f"라우트 프리픽스: {analysis.get('route_prefixes') or []}",
        f"상품 API: {analysis.get('product_api') or []}",
        f"주문 API: {analysis.get('order_api') or []}",
        f"프론트엔드 마운트 지점: {analysis.get('frontend_mount_points') or []}",
    ]


def _build_planning_evidence(
    analysis: dict[str, Any],
    recommended_outputs: list[str],
    manifest_status: str,
) -> list[str]:
    framework = analysis.get("framework") or {}
    auth = analysis.get("auth") or {}
    return [
        f"백엔드 프레임워크: {framework.get('backend', 'unknown')}",
        f"프론트엔드 프레임워크: {framework.get('frontend', 'unknown')}",
        f"인증 방식: {auth.get('auth_style', 'unknown')}",
        f"라우트 프리픽스: {analysis.get('route_prefixes') or []}",
        f"권장 산출물: {recommended_outputs}",
        f"프론트엔드 마운트 지점: {analysis.get('frontend_mount_points') or []}",
        f"현재 상태: {manifest_status}",
    ]


def _build_proposed_files(recommended_outputs: list[str]) -> list[str]:
    file_map = {
        "chat_auth": "files/backend/chat_auth.py",
        "order_adapter": "files/backend/order_adapter_client.py",
        "product_adapter": "files/backend/product_adapter_client.py",
        "frontend_patch": "files/frontend/src/chatbot/SharedChatbotWidget.jsx",
    }
    proposed = [file_map[item] for item in recommended_outputs if item in file_map]
    if any(item in recommended_outputs for item in {"order_adapter", "product_adapter"}):
        proposed.append("files/backend/tool_registry.py")
    return list(dict.fromkeys(proposed))


def _build_proposed_patches(recommended_outputs: list[str]) -> list[str]:
    patch_map = {
        "chat_auth": "patches/backend_chat_auth_route.patch",
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
        f"권장 산출물: {recommended_outputs}",
        f"제안 파일: {proposed_files}",
        f"제안 patch: {proposed_patches}",
        f"인증 방식: {(analysis.get('auth') or {}).get('auth_style', 'unknown')}",
        f"프론트엔드 마운트 지점: {analysis.get('frontend_mount_points') or []}",
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
        "files/backend/tool_registry.py": generate_backend_tool_registry,
        "files/frontend/src/chatbot/SharedChatbotWidget.jsx": generate_frontend_widget_artifact,
    }
    patch_generators = {
        "patches/backend_chat_auth_route.patch": generate_backend_route_patch,
        "patches/frontend_widget_mount.patch": generate_frontend_mount_patch,
    }
    materialized_frontend_artifacts: list[dict[str, str]] = []
    generated_files: list[str] = []
    patch_targets: list[str] = []

    for file_path in proposed_files:
        generator = file_generators.get(file_path)
        if generator is not None:
            result = generator(run_root)
            if file_path not in generated_files:
                generated_files.append(file_path)
            if isinstance(result, dict) and result.get("type") == "widget":
                materialized_frontend_artifacts.append(
                    {
                        "type": str(result.get("type") or "widget"),
                        "path": str(
                            Path(str(result.get("path") or "")).relative_to(run_root).as_posix()
                        ),
                        "source": "llm",
                    }
                )

    for patch_path in proposed_patches:
        generator = patch_generators.get(patch_path)
        if generator is not None:
            generator(run_root)
            if patch_path not in patch_targets:
                patch_targets.append(patch_path)

    if generated_files or patch_targets:
        _update_manifest_generated_outputs(
            run_root=run_root,
            generated_files=generated_files,
            patch_targets=patch_targets,
        )

    if materialized_frontend_artifacts:
        _update_manifest_frontend_artifacts(
            run_root=run_root,
            frontend_artifacts=materialized_frontend_artifacts,
        )


def _update_manifest_frontend_artifacts(
    *,
    run_root: Path,
    frontend_artifacts: list[dict[str, str]],
) -> None:
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frontend_artifacts"] = frontend_artifacts
    generated_files = list(manifest.get("generated_files") or [])
    for artifact in frontend_artifacts:
        path = str(artifact.get("path") or "")
        if path and path not in generated_files:
            generated_files.append(path)
    manifest["generated_files"] = generated_files
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _update_manifest_generated_outputs(
    *,
    run_root: Path,
    generated_files: list[str],
    patch_targets: list[str],
) -> None:
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current_generated_files = list(manifest.get("generated_files") or [])
    current_patch_targets = list(manifest.get("patch_targets") or [])
    for path in generated_files:
        if path and path not in current_generated_files:
            current_generated_files.append(path)
    for path in patch_targets:
        if path and path not in current_patch_targets:
            current_patch_targets.append(path)
    manifest["generated_files"] = current_generated_files
    manifest["patch_targets"] = current_patch_targets
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
