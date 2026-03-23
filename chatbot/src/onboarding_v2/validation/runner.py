from __future__ import annotations

import json
import py_compile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chatbot.src.onboarding import backend_evaluator as legacy_backend
from chatbot.src.onboarding import frontend_evaluator as legacy_frontend
from chatbot.src.onboarding.smoke_contract import ProbeExpectation, SmokeTestPlan, SmokeTestStep
from chatbot.src.onboarding.smoke_runner import run_smoke_tests
from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.common import ArtifactRef
from chatbot.src.onboarding_v2.models.planning import IntegrationPlan
from chatbot.src.onboarding_v2.models.validation import (
    BackendRuntimePlan,
    BackendRuntimePrepResult,
    BackendRuntimeState,
    ReplayResult,
    SmokeRunResult,
    ValidationBundle,
    ValidationCheck,
)
from chatbot.src.onboarding_v2.validation.backend_runtime import (
    build_backend_runtime_plan,
    launch_backend_runtime,
    prepare_backend_runtime,
    stop_backend_runtime,
)
from chatbot.src.onboarding_v2.validation.signatures import build_failure_signature


@dataclass(slots=True)
class ValidationRunResult:
    bundle: ValidationBundle
    backend_runtime_prep: BackendRuntimePrepResult
    backend_runtime_state: BackendRuntimeState
    smoke_results: SmokeRunResult


def run_validation(
    *,
    run_root: str | Path,
    runtime_workspace: str | Path,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    replay_result: ReplayResult,
    artifact_refs: dict[str, ArtifactRef | None],
    onboarding_credentials: dict[str, str] | None = None,
) -> ValidationBundle:
    return run_validation_cycle(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        snapshot=snapshot,
        plan=plan,
        replay_result=replay_result,
        artifact_refs=artifact_refs,
        onboarding_credentials=onboarding_credentials,
    ).bundle


def run_validation_cycle(
    *,
    run_root: str | Path,
    runtime_workspace: str | Path,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    replay_result: ReplayResult,
    artifact_refs: dict[str, ArtifactRef | None],
    onboarding_credentials: dict[str, str] | None = None,
) -> ValidationRunResult:
    run_root = Path(run_root)
    runtime_workspace = Path(runtime_workspace)
    _write_smoke_manifest(
        run_root=run_root,
        credentials=onboarding_credentials or {
            "email": "test1@example.com",
            "password": "password123",
        },
    )

    prep_result = prepare_backend_runtime(workspace=runtime_workspace, snapshot=snapshot)
    runtime_state: BackendRuntimeState
    smoke_results: SmokeRunResult
    if prep_result.passed:
        runtime_plan = build_backend_runtime_plan(
            workspace=runtime_workspace,
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

    frontend_payload = _evaluate_frontend(runtime_workspace)
    if prep_result.passed and runtime_state.passed and runtime_plan is not None:
        try:
            smoke_payload = run_runtime_smoke(
                run_root=run_root,
                runtime_workspace=runtime_workspace,
                runtime_plan=runtime_plan,
            )
            smoke_results = (
                smoke_payload
                if isinstance(smoke_payload, SmokeRunResult)
                else SmokeRunResult.model_validate(smoke_payload)
            )
        finally:
            stop_backend_runtime(runtime_state)
    else:
        smoke_results = _skipped_smoke_result(
            "backend runtime boot failed"
            if prep_result.passed
            else "backend runtime prep failed"
        )

    replay_validation_payload = _evaluate_replay_workspace(Path(replay_result.replay_workspace_path))

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
            name="frontend_evaluation",
            passed=bool(frontend_payload["passed"]),
            summary="frontend evaluation passed" if frontend_payload["passed"] else frontend_payload["failure_summary"],
            details=frontend_payload,
        ),
        ValidationCheck(
            name="smoke",
            passed=smoke_results.passed,
            summary=smoke_results.failure_summary or "smoke passed",
            details=smoke_results.model_dump(mode="json"),
        ),
        ValidationCheck(
            name="replay_apply",
            passed=bool(replay_result.passed),
            summary="replay apply passed" if replay_result.passed else "replay apply failed",
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

    first_failure = next((check for check in checks if not check.passed), None)
    related_artifacts = [ref for ref in artifact_refs.values() if ref is not None]
    input_artifact_versions = {name: ref.version for name, ref in artifact_refs.items() if ref is not None}
    related_files = sorted(
        {
            *prep_result.related_files,
            *runtime_state.related_files,
            *frontend_payload.get("related_files", []),
            *smoke_results.related_files,
            *replay_validation_payload.get("related_files", []),
        }
    )
    bundle = ValidationBundle(
        passed=first_failure is None,
        checks=checks,
        failure_signature=(
            None
            if first_failure is None
            else build_failure_signature(check_name=first_failure.name, summary=first_failure.summary)
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
        smoke_results=smoke_results,
    )


def run_runtime_smoke(
    *,
    run_root: Path,
    runtime_workspace: Path,
    runtime_plan: BackendRuntimePlan,
) -> SmokeRunResult:
    del runtime_plan
    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=_build_food_smoke_plan(),
    )
    first_failure = next((item for item in results if int(item.get("returncode") or 0) != 0), None)
    return SmokeRunResult(
        passed=first_failure is None,
        results=results,
        failure_summary=(
            "smoke passed"
            if first_failure is None
            else str(first_failure.get("stderr") or first_failure.get("stdout") or first_failure.get("step_id"))
        ),
        related_files=["backend/manage.py", "backend/chat_auth.py"],
    )


def _evaluate_backend(workspace: Path) -> dict[str, Any]:
    ignore_matcher = legacy_backend.OnboardingIgnoreMatcher(workspace)
    checked_files: list[str] = []
    failed_files: list[dict[str, str]] = []
    for path in legacy_backend._iter_python_files(workspace, ignore_matcher):
        relative = path.relative_to(workspace).as_posix()
        checked_files.append(relative)
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failed_files.append({"path": relative, "error": str(exc)})
    framework = legacy_backend._detect_backend_framework(workspace)
    route_wiring = legacy_backend._evaluate_route_wiring(workspace, framework=framework)
    passed = not failed_files and not route_wiring["validation_errors"]
    failure_summary = ""
    if failed_files:
        failure_summary = f"python compile failed for {failed_files[0]['path']}"
    elif route_wiring["validation_errors"]:
        failure_summary = str(route_wiring["validation_errors"][0])
    return {
        "passed": passed,
        "framework": framework,
        "checked_files": checked_files,
        "failed_files": failed_files,
        "route_wiring": route_wiring,
        "failure_summary": failure_summary or "backend evaluation passed",
        "related_files": sorted(set(checked_files) | set(route_wiring.get("files") or [])),
    }


def _evaluate_frontend(workspace: Path) -> dict[str, Any]:
    framework = legacy_frontend._detect_frontend_framework(workspace)
    mount_candidates = legacy_frontend._find_mount_candidates(workspace)
    mount_path = legacy_frontend._resolve_mount_path(workspace, mount_candidates)
    validation_errors = legacy_frontend._collect_validation_errors(
        workspace=workspace,
        mount=mount_path,
        framework=framework,
    )
    passed = not validation_errors
    return {
        "passed": passed,
        "framework": framework,
        "mount_candidates": mount_candidates,
        "mount_path": str(mount_path) if mount_path else None,
        "validation_errors": validation_errors,
        "failure_summary": validation_errors[0] if validation_errors else "frontend evaluation passed",
        "related_files": mount_candidates,
    }


def _build_food_smoke_plan() -> SmokeTestPlan:
    return SmokeTestPlan(
        steps=[
            SmokeTestStep(
                id="login",
                method="POST",
                url="http://127.0.0.1:8000/api/users/login/",
                headers={"Content-Type": "application/json"},
                body={
                    "email": "{{ probe.credentials.email }}",
                    "password": "{{ probe.credentials.password }}",
                },
                category="auth",
                expects=ProbeExpectation(status=200, json_path_equals={"ok": True}),
                exports={"login.session_token": "cookies.session_token"},
            ),
            SmokeTestStep(
                id="session-me",
                method="GET",
                url="http://127.0.0.1:8000/api/users/me/",
                headers={"Cookie": "session_token={{ login.session_token }}"},
                category="auth",
                uses=["login.session_token"],
                expects=ProbeExpectation(status=200, json_path_equals={"authenticated": True}),
            ),
            SmokeTestStep(
                id="chat-auth-token",
                method="GET",
                url="http://127.0.0.1:8000/api/chat/auth-token",
                headers={"Cookie": "session_token={{ login.session_token }}"},
                category="auth",
                uses=["login.session_token"],
                expects=ProbeExpectation(
                    status=200,
                    json_path_equals={"authenticated": True},
                    json_path_not_empty=["access_token"],
                ),
            ),
            SmokeTestStep(
                id="product-api",
                method="GET",
                url="http://127.0.0.1:8000/api/products/",
                category="catalog",
                expects=ProbeExpectation(status=200, json_type="list", json_array_min_length=1),
            ),
            SmokeTestStep(
                id="order-api",
                method="GET",
                url="http://127.0.0.1:8000/api/orders/",
                headers={"Cookie": "session_token={{ login.session_token }}"},
                category="orders",
                uses=["login.session_token"],
                expects=ProbeExpectation(status=200, json_type="list", json_array_min_length=1),
            ),
        ]
    )


def _evaluate_replay_workspace(workspace: Path) -> dict[str, Any]:
    backend = _evaluate_backend(workspace)
    frontend = _evaluate_frontend(workspace)
    passed = backend["passed"] and frontend["passed"]
    failure_summary = (
        "replay validation passed"
        if passed
        else backend["failure_summary"] if not backend["passed"] else frontend["failure_summary"]
    )
    return {
        "passed": passed,
        "failure_summary": failure_summary,
        "backend": backend,
        "frontend": frontend,
        "related_files": sorted(set(backend["related_files"]) | set(frontend["related_files"])),
    }


def _write_smoke_manifest(*, run_root: Path, credentials: dict[str, str]) -> None:
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        payload = {}
    payload["credentials"] = {key: value for key, value in credentials.items() if value}
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _skipped_runtime_state(*, framework: str, reason: str) -> BackendRuntimeState:
    return BackendRuntimeState(
        framework=framework,
        passed=False,
        failure_summary=reason,
        related_files=["backend/manage.py", "backend/chat_auth.py"] if framework == "django" else ["chat_auth.py"],
    )


def _skipped_smoke_result(reason: str) -> SmokeRunResult:
    return SmokeRunResult(
        passed=False,
        results=[],
        failure_summary=f"smoke skipped because {reason}",
        related_files=["backend/manage.py", "backend/chat_auth.py"],
    )
