import os
import sys
import types
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_bundle
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.export import export_and_replay
from chatbot.src.onboarding_v2.models.validation import BackendRuntimePlan, BackendRuntimePrepResult, BackendRuntimeState
from chatbot.src.onboarding_v2.models.planning import (
    ChatbotBridgePlan,
    HostBackendPlan,
    HostFrontendPlan,
    IntegrationPlan,
    ResolvedAuthContract,
    ResolvedOrderActionContract,
    ResolvedRequestFieldContract,
    ResolvedResponseContract,
)
from chatbot.src.onboarding_v2.planning import build_planning_bundle
from chatbot.src.onboarding_v2.storage import ArtifactStore
from chatbot.src.adapters.schema import User
from chatbot.src.onboarding_v2.validation.runner import (
    ConversationScenarioResult,
    ConversationValidationResult,
    _collect_widget_order_flow_report,
    _build_runtime_fixture_manifest,
    _evaluate_conversation_deterministic_failures,
    _finalize_conversation_scenario_result,
    _evaluate_widget_order_flow_report,
    _enforce_required_rechecks,
    _load_generated_adapter,
    _load_runtime_chat_modules,
    _resolve_bridge_auth_material,
    _run_conversation_llm_judge,
    _runtime_base_url,
    run_validation,
    validate_chatbot_adapter_auth,
    validate_host_auth_bootstrap,
    validate_chatbot_runtime_boot,
    validate_conversation_runtime,
)
from chatbot.src.onboarding_v2.validation.signatures import build_failure_signature


@pytest.fixture(autouse=True)
def _disable_onboarding_v2_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ONBOARDING_V2_ENABLE_LLM", "0")


def _build_food_runtime_artifacts(tmp_path: Path):
    generated_root = tmp_path / "generated" / "food" / "food-run-v2"
    runtime_root = tmp_path / "runtime"
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    snapshot = analysis_bundle.snapshot
    planning_bundle = build_planning_bundle(
        snapshot=snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    plan = planning_bundle.integration_plan
    program = compile_plan(
        analysis_bundle=analysis_bundle,
        planning_bundle=planning_bundle,
        source_root=ROOT / "food",
    )
    apply_result = apply_edit_program(
        host_source_root=ROOT / "food",
        chatbot_source_root=ROOT / "chatbot",
        runtime_root=runtime_root,
        site="food",
        run_id="food-run-v2",
        edit_program=program,
    )
    artifact_store = ArtifactStore(generated_root)
    analysis_ref = artifact_store.write_json_artifact(stage="analysis", artifact_type="snapshot", payload=snapshot.model_dump(mode="json"), producer="test")
    plan_ref = artifact_store.write_json_artifact(stage="planning", artifact_type="integration-plan", payload=plan.model_dump(mode="json"), producer="test")
    compile_ref = artifact_store.write_json_artifact(stage="compile", artifact_type="host-edit-program", payload=program.host_program.model_dump(mode="json"), producer="test")
    apply_ref = artifact_store.write_json_artifact(stage="apply", artifact_type="apply-result", payload=apply_result.model_dump(mode="json"), producer="test")
    _, replay_result, replay_ref = export_and_replay(
        host_source_root=ROOT / "food",
        chatbot_source_root=ROOT / "chatbot",
        host_baseline_root=apply_result.host_source_snapshot_path,
        chatbot_baseline_root=apply_result.chatbot_source_snapshot_path,
        host_runtime_workspace=apply_result.host_workspace_path,
        chatbot_runtime_workspace=apply_result.chatbot_workspace_path,
        host_allowed_targets=apply_result.host_applied_files,
        chatbot_allowed_targets=apply_result.chatbot_applied_files,
        runtime_root=runtime_root,
        run_root=generated_root,
        site="food",
        run_id="food-run-v2",
        artifact_store=artifact_store,
    )
    return {
        "generated_root": generated_root,
        "snapshot": snapshot,
        "plan": plan,
        "apply_result": apply_result,
        "replay_result": replay_result,
        "artifact_refs": {
            "analysis": analysis_ref,
            "planning": plan_ref,
            "compile": compile_ref,
            "apply": apply_ref,
            "replay": replay_ref,
        },
    }


def _build_food_plan():
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    return planning_bundle.integration_plan


def test_validation_runner_normalizes_checks(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan, **kwargs: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "host auth bootstrap passed",
            "bootstrap_payload": {
                "authenticated": True,
                "site_id": "food",
                "access_token": "session-token",
                "user": {"id": "7"},
            },
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_adapter_auth",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot adapter auth passed",
            "validated_user": {"id": "7", "siteId": "food"},
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_order_e2e",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget order e2e passed",
            "covered_flows": ["list_orders", "get_order_status", "cancel", "refund", "exchange"],
            "flow_reports": {},
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_conversation_runtime",
        lambda **kwargs: ConversationValidationResult(
            passed=True,
            fixture_manifest={},
            scenarios=[],
            transcript_contents={},
            trace_contents={},
            related_files=[],
        ),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner._evaluate_replay_workspaces",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": None,
            "related_files": [],
        },
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert [check.name for check in bundle.checks] == [
        "backend_runtime_prep",
        "backend_runtime_boot",
        "chatbot_runtime_boot",
        "widget_bundle_fetch",
        "host_auth_bootstrap",
        "chatbot_adapter_auth",
        "widget_order_e2e",
        "conversation_validation",
        "replay_apply",
        "replay_validation",
    ]
    check_map = {check.name: check for check in bundle.checks}
    assert check_map["conversation_validation"].blocking is False


def test_validation_runner_does_not_allow_static_fallback_success(monkeypatch, tmp_path: Path):
    runtime_context = _build_food_runtime_artifacts(tmp_path)
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(
            framework="django",
            passed=False,
            failure_summary="dependency install failed: missing corsheaders",
        ),
    )

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert bundle.checks[0].name == "backend_runtime_prep"
    assert bundle.checks[0].passed is False
    assert bundle.failure_signature.startswith("backend_runtime_prep")


def test_validation_runner_requires_requested_rechecks():
    with pytest.raises(ValueError, match="required validation rechecks missing: host_auth_bootstrap"):
        _enforce_required_rechecks(
            required_rechecks=["host_auth_bootstrap"],
            checks=[
                {"name": "backend_runtime_prep", "passed": True},
                {"name": "widget_order_e2e", "passed": True},
            ],
        )


def test_validation_runner_records_advisory_conversation_failures(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
        listen_port=8000,
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
        listen_port=8000,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(
            framework="django",
            passed=True,
            fixture_manifest={"available": True},
        ),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan, **kwargs: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "host auth bootstrap passed",
            "bootstrap_payload": {
                "authenticated": True,
                "site_id": "food",
                "access_token": "session-token",
                "user": {"id": "7"},
            },
            "session_cookies": {"sessionid": "cookie-123"},
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_adapter_auth",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot adapter auth passed",
            "validated_user": {"id": "7", "siteId": "food"},
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_order_e2e",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget order e2e passed",
            "covered_flows": ["list_orders", "get_order_status", "cancel", "refund", "exchange"],
            "flow_reports": {},
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_conversation_runtime",
        lambda **kwargs: ConversationValidationResult(
            passed=False,
            failure_summary="conversation validation advisory failure",
            fixture_manifest={"available": True},
            scenarios=[
                ConversationScenarioResult(
                    scenario_id="authenticated_list_orders",
                    mode="read_only",
                    conversation_id="conv-1",
                    deterministic_passed=False,
                    llm_passed=None,
                    final_verdict="fail",
                    transcript_path="/tmp/transcript.json",
                    trace_path="/tmp/trace.jsonl",
                )
            ],
            transcript_contents={"authenticated_list_orders": "{}"},
        ),
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is True
    conversation_check = next(check for check in bundle.checks if check.name == "conversation_validation")
    assert conversation_check.passed is False
    assert conversation_check.blocking is False
    assert "conversation_validation" in bundle.advisory_failures


def test_conversation_validation_skips_llm_judge_after_deterministic_failure(monkeypatch):
    called = {"judge": False}

    def _fake_judge(**kwargs):
        called["judge"] = True
        return {"overall_pass": True}

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner._run_conversation_llm_judge",
        _fake_judge,
    )

    result = _finalize_conversation_scenario_result(
        scenario_id="cancel_order",
        mode="mutating",
        prompt="cancel order",
        final_answer="",
        transcript_path="/tmp/transcript.json",
        trace_path="/tmp/trace.jsonl",
        expected_tool_names=["cancel"],
        observed_tool_names=[],
        deterministic_failures=["missing expected tool"],
        sampled_order_id="ORD-1",
        sampled_option_id=None,
    )

    assert result.deterministic_passed is False
    assert result.llm_passed is None
    assert result.final_verdict == "fail"
    assert called["judge"] is False


def test_conversation_llm_judge_keeps_tool_runtime_disabled(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_invoke_structured_stage(*, response_model, fallback_payload, tool_runtime=None, **kwargs):
        del kwargs
        captured["tool_runtime"] = tool_runtime
        return response_model.model_validate(fallback_payload)

    monkeypatch.setenv("ONBOARDING_V2_ENABLE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.invoke_structured_stage",
        _fake_invoke_structured_stage,
    )

    result = _run_conversation_llm_judge(
        prompt="show my order",
        final_answer="Here is your order.",
        expected_tool_names=["lookup_order"],
        observed_tool_names=["lookup_order"],
        transcript_path="/tmp/transcript.json",
        trace_path="/tmp/trace.jsonl",
    )

    assert captured["tool_runtime"] is None
    assert result["overall_pass"] is True


def test_validate_host_auth_bootstrap_uses_runtime_plan_listen_port(monkeypatch, tmp_path: Path):
    captured_urls: list[str] = []

    class _Response:
        def __init__(self, status_code: int, payload: dict[str, object]):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            del json
            captured_urls.append(url)
            if url.endswith("/api/users/login/"):
                return _Response(200, {})
            return _Response(
                200,
                {
                    "authenticated": True,
                    "site_id": "food",
                    "access_token": "token",
                    "user": {"id": "7"},
                },
            )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.httpx.Client",
        lambda **kwargs: _Client(),
    )
    plan = _build_food_plan()
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8123"],
        readiness_url="http://127.0.0.1:8123/api/chat/auth-token",
        listen_port=8123,
    )

    result = validate_host_auth_bootstrap(
        run_root=tmp_path,
        host_runtime_workspace=tmp_path,
        runtime_plan=runtime_plan,
        snapshot=build_analysis_bundle(site="food", source_root=ROOT / "food").snapshot,
        plan=plan,
    )

    assert result["passed"] is True
    assert result["bootstrap_mode"] == "real_host_session"
    assert captured_urls == [
        f"http://127.0.0.1:8123{plan.host_backend.login_endpoint}",
        "http://127.0.0.1:8123/api/chat/auth-token",
    ]


def test_validate_host_auth_bootstrap_uses_planned_login_endpoint(monkeypatch, tmp_path: Path):
    captured_urls: list[str] = []

    class _Response:
        def __init__(self, status_code: int, payload: dict[str, object]):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            del json
            captured_urls.append(url)
            if url.endswith("/api/auth/login"):
                return _Response(200, {})
            return _Response(
                200,
                {
                    "authenticated": True,
                    "site_id": "bilyeo",
                    "access_token": "token",
                    "user": {"id": "7"},
                },
            )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.httpx.Client",
        lambda **kwargs: _Client(),
    )
    analysis_bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
        strict_coverage=True,
    )
    plan = planning_bundle.integration_plan
    runtime_plan = BackendRuntimePlan(
        framework="flask",
        backend_root=str(tmp_path / "backend"),
        command=["python", "app.py"],
        readiness_url="http://127.0.0.1:8124/api/chat/auth-token",
        listen_port=8124,
    )

    result = validate_host_auth_bootstrap(
        run_root=tmp_path,
        host_runtime_workspace=tmp_path,
        runtime_plan=runtime_plan,
        snapshot=analysis_bundle.snapshot,
        plan=plan,
    )

    assert result["passed"] is True
    assert result["bootstrap_mode"] == "real_host_session"
    assert plan.host_backend.login_endpoint == "/api/auth/login"
    assert captured_urls == [
        "http://127.0.0.1:8124/api/auth/login",
        "http://127.0.0.1:8124/api/chat/auth-token",
    ]


def test_validate_host_auth_bootstrap_uses_validation_bridge_without_planned_login_endpoint(
    monkeypatch, tmp_path: Path
):
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    plan = planning_bundle.integration_plan.model_copy(
        update={
            "host_backend": planning_bundle.integration_plan.host_backend.model_copy(
                update={"login_endpoint": ""}
            )
        }
    )
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8125"],
        readiness_url="http://127.0.0.1:8125/api/chat/auth-token",
        listen_port=8125,
    )

    class _Response:
        def __init__(self, status_code: int, payload: dict[str, object], text: str):
            self.status_code = status_code
            self._payload = payload
            self.text = text

        def json(self):
            return self._payload

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            del json
            assert url == "http://127.0.0.1:8125/api/chat/auth-token"
            return _Response(
                200,
                {
                    "authenticated": True,
                    "site_id": "food",
                    "access_token": "validation-food",
                    "user": {"id": "validation-user"},
                },
                '{"authenticated": true}',
            )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.httpx.Client",
        lambda **kwargs: _Client(),
    )

    result = validate_host_auth_bootstrap(
        run_root=tmp_path,
        host_runtime_workspace=tmp_path,
        runtime_plan=runtime_plan,
        snapshot=analysis_bundle.snapshot,
        plan=plan,
    )

    assert result["passed"] is True
    assert result["bootstrap_mode"] == "validation_bridge"
    assert result["failure_origin"] == "login"


def test_validate_conversation_runtime_emits_scenario_events(monkeypatch, tmp_path: Path):
    observed_events: list[dict[str, object]] = []
    fixture_manifest = {
        "available": True,
        "site_id": "food",
        "access_token": "token",
        "capability_profile": "order_cs_only",
        "session_cookies": {"sessionid": "cookie-1"},
        "bootstrap_payload": {"user": {"id": "7"}},
        "orders": {},
    }

    async def _fake_unauthenticated(**kwargs):
        scenario = kwargs["scenario"]
        result = ConversationScenarioResult(
            scenario_id=scenario["scenario_id"],
            mode=scenario["mode"],
            conversation_id="conv-unauth",
            deterministic_passed=True,
            llm_passed=True,
            final_verdict="pass",
            transcript_path=str(tmp_path / "unauth.json"),
            trace_path=None,
        )
        return result, "{}"

    async def _fake_authenticated(**kwargs):
        scenario = kwargs["scenario"]
        result = ConversationScenarioResult(
            scenario_id=scenario["scenario_id"],
            mode=scenario["mode"],
            conversation_id="conv-auth",
            deterministic_passed=True,
            llm_passed=True,
            final_verdict="pass",
            transcript_path=str(tmp_path / f"{scenario['scenario_id']}.json"),
            trace_path=str(tmp_path / f"{scenario['scenario_id']}.jsonl"),
        )
        return result, "{}", "{}", {"conversation_id": "conv-auth"}

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner._build_runtime_fixture_manifest",
        lambda **kwargs: fixture_manifest,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner._load_runtime_chat_modules",
        lambda **kwargs: (object(), object()),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner._build_conversation_scenarios",
        lambda **kwargs: [
            {"scenario_id": "unauthenticated_chat_request", "mode": "auth", "prompt": "hi"},
            {"scenario_id": "authenticated_list_orders", "mode": "read_only", "prompt": "orders"},
        ],
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner._run_unauthenticated_conversation_scenario",
        _fake_unauthenticated,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner._run_authenticated_conversation_scenario",
        _fake_authenticated,
    )

    result = validate_conversation_runtime(
        run_root=tmp_path,
        chatbot_runtime_workspace=tmp_path,
        runtime_plan=BackendRuntimePlan(
            framework="django",
            backend_root=str(tmp_path),
            command=["python"],
            readiness_url="http://127.0.0.1:8123/api/chat/auth-token",
            listen_port=8123,
        ),
        snapshot=build_analysis_bundle(site="food", source_root=ROOT / "food").snapshot,
        plan=_build_food_plan(),
        prep_result=BackendRuntimePrepResult(
            framework="django",
            passed=True,
            fixture_manifest=fixture_manifest,
        ),
        bootstrap_result={"passed": True},
        adapter_auth_result={"passed": True},
        event_callback=lambda payload: observed_events.append(payload),
    )

    assert result.passed is True
    phases = [str(event["phase"]) for event in observed_events]
    assert phases == [
        "conversation_scenario_start",
        "conversation_scenario_finish",
        "conversation_scenario_start",
        "conversation_scenario_finish",
    ]


def test_validate_chatbot_adapter_auth_uses_real_session_cookie_for_food(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}
    real_import_module = validate_chatbot_adapter_auth.__globals__["importlib"].import_module
    plan = _build_food_plan()

    class _FakeClient:
        def __init__(self, base_url: str):
            captured["base_url"] = base_url

    class _FakeAdapter:
        def __init__(self, client):
            self.client = client

        async def validate_auth(self, ctx):
            captured["ctx"] = ctx
            return User(id="7", siteId="food")

    def _fake_import_module(name: str):
        if name == "src.adapters.generated.food.adapter":
            return types.SimpleNamespace(GeneratedFoodAdapter=_FakeAdapter)
        if name == "src.adapters.generated.food.client":
            return types.SimpleNamespace(GeneratedFoodClient=_FakeClient)
        return real_import_module(name)

    monkeypatch.setattr(
        validate_chatbot_adapter_auth.__globals__["importlib"],
        "import_module",
        _fake_import_module,
    )

    result = validate_chatbot_adapter_auth(
        chatbot_runtime_workspace=tmp_path,
        runtime_plan=BackendRuntimePlan(
            framework="django",
            backend_root=str(tmp_path / "backend"),
            command=["python", "manage.py", "runserver"],
            readiness_url="http://127.0.0.1:8123/api/chat/auth-token",
            listen_port=8123,
        ),
        bootstrap_result={
            "passed": True,
            "bootstrap_payload": {
                "access_token": "validation-food",
                "user": {"id": "7"},
            },
            "session_cookies": {"session_token": "real-session-token"},
        },
        plan=plan,
    )

    assert result["passed"] is True
    ctx = captured["ctx"]
    assert getattr(ctx, "accessToken", None) in (None, "")
    assert getattr(ctx, "cookies", None) == {"session_token": "real-session-token"}


def test_validate_chatbot_adapter_auth_repairs_generated_src_namespace(tmp_path: Path, monkeypatch):
    chatbot_workspace = tmp_path / "chatbot"
    generated_root = chatbot_workspace / "src" / "adapters" / "generated" / "food"
    generated_root.mkdir(parents=True, exist_ok=True)
    for package_path in [
        chatbot_workspace / "src" / "__init__.py",
        chatbot_workspace / "src" / "adapters" / "__init__.py",
        generated_root / "__init__.py",
    ]:
        package_path.parent.mkdir(parents=True, exist_ok=True)
        package_path.write_text("", encoding="utf-8")
    (generated_root / "client.py").write_text(
        "class GeneratedFoodClient:\n"
        "    def __init__(self, base_url):\n"
        "        self.base_url = base_url\n",
        encoding="utf-8",
    )
    (generated_root / "adapter.py").write_text(
        "class _ValidatedUser:\n"
        "    def __init__(self):\n"
        "        self.id = '7'\n"
        "        self.siteId = 'food'\n"
        "    def model_dump(self, mode='json'):\n"
        "        return {'id': self.id, 'siteId': self.siteId}\n"
        "\n"
        "class GeneratedFoodAdapter:\n"
        "    def __init__(self, client):\n"
        "        self.client = client\n"
        "    async def validate_auth(self, ctx):\n"
        "        return _ValidatedUser()\n",
        encoding="utf-8",
    )

    stale_src = types.ModuleType("src")
    stale_src.__path__ = [str(tmp_path / "stale-src")]
    stale_adapters = types.ModuleType("src.adapters")
    stale_adapters.__path__ = [str(tmp_path / "stale-src" / "adapters")]
    stale_chatbot_src = types.ModuleType("chatbot.src")
    stale_chatbot_src.__path__ = list(stale_src.__path__)
    stale_chatbot_adapters = types.ModuleType("chatbot.src.adapters")
    stale_chatbot_adapters.__path__ = list(stale_adapters.__path__)

    monkeypatch.setitem(sys.modules, "src", stale_src)
    monkeypatch.setitem(sys.modules, "src.adapters", stale_adapters)
    monkeypatch.setitem(sys.modules, "chatbot.src", stale_chatbot_src)
    monkeypatch.setitem(sys.modules, "chatbot.src.adapters", stale_chatbot_adapters)

    result = validate_chatbot_adapter_auth(
        chatbot_runtime_workspace=chatbot_workspace,
        runtime_plan=BackendRuntimePlan(
            framework="django",
            backend_root=str(tmp_path / "backend"),
            command=["python", "manage.py", "runserver"],
            readiness_url="http://127.0.0.1:8128/api/chat/auth-token",
            listen_port=8128,
        ),
        bootstrap_result={
            "passed": True,
            "bootstrap_payload": {
                "access_token": "validation-food",
                "user": {"id": "7"},
            },
            "session_cookies": {"session_token": "real-session-token"},
        },
        plan=_build_food_plan(),
    )

    assert result["passed"] is True
    assert result["validated_user"]["id"] == "7"


def test_validate_chatbot_adapter_auth_returns_failure_on_generated_import_error(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setitem(
        validate_chatbot_adapter_auth.__globals__,
        "_load_generated_adapter",
        lambda **kwargs: (_ for _ in ()).throw(
            ModuleNotFoundError("No module named 'src.adapters.generated'")
        ),
    )

    result = validate_chatbot_adapter_auth(
        chatbot_runtime_workspace=tmp_path,
        runtime_plan=BackendRuntimePlan(
            framework="django",
            backend_root=str(tmp_path / "backend"),
            command=["python", "manage.py", "runserver"],
            readiness_url="http://127.0.0.1:8129/api/chat/auth-token",
            listen_port=8129,
        ),
        bootstrap_result={
            "passed": True,
            "bootstrap_payload": {
                "access_token": "validation-food",
                "user": {"id": "7"},
            },
            "session_cookies": {"session_token": "real-session-token"},
        },
        plan=_build_food_plan(),
    )

    assert result["passed"] is False
    assert "src.adapters.generated" in result["failure_summary"]


def test_runtime_fixture_manifest_reuses_transport_aware_food_auth_context(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    class _FakeClient:
        async def list_orders(self, headers):
            captured["headers"] = headers
            return [{"order_id": "10", "option_id": "opt-1"}]

    class _FakeAdapter:
        def __init__(self):
            self.client = _FakeClient()

    monkeypatch.setitem(
        _build_runtime_fixture_manifest.__globals__,
        "_load_generated_adapter",
        lambda **kwargs: _FakeAdapter(),
    )

    def _fake_build_generated_auth_headers(*, adapter, auth_context):
        del adapter
        captured["auth_context"] = auth_context
        return {"Cookie": "session_token=real-session-token"}

    monkeypatch.setitem(
        _build_runtime_fixture_manifest.__globals__,
        "_build_generated_auth_headers",
        _fake_build_generated_auth_headers,
    )

    manifest = _build_runtime_fixture_manifest(
        chatbot_runtime_workspace=tmp_path,
        runtime_plan=BackendRuntimePlan(
            framework="django",
            backend_root=str(tmp_path / "backend"),
            command=["python", "manage.py", "runserver"],
            readiness_url="http://127.0.0.1:8124/api/chat/auth-token",
            listen_port=8124,
        ),
        plan=_build_food_plan(),
        prep_result=BackendRuntimePrepResult(
            framework="django",
            passed=True,
            fixture_manifest={"seed_source": {}, "auth": {}},
        ),
        bootstrap_result={
            "passed": True,
            "bootstrap_payload": {
                "access_token": "validation-food",
                "user": {"id": "7"},
            },
            "session_cookies": {"session_token": "real-session-token"},
        },
        adapter_auth_result={"passed": True, "validated_user": {"id": "7"}},
        onboarding_credentials=None,
    )

    assert manifest["available"] is True
    assert manifest["access_token"] == ""
    assert manifest["session_cookies"] == {"session_token": "real-session-token"}
    assert manifest["validation_capability_contract"]["supports_authenticated_chat"] is True
    assert manifest["validation_capability_contract"]["supports_mutations"] is True
    auth_context = captured["auth_context"]
    assert getattr(auth_context, "accessToken", None) in (None, "")
    assert getattr(auth_context, "cookies", None) == {"session_token": "real-session-token"}


def test_runtime_fixture_manifest_uses_nested_response_contract_for_visible_order_ids(
    monkeypatch, tmp_path: Path
):
    captured: dict[str, object] = {}

    class _FakeClient:
        async def list_orders(self, headers):
            captured["headers"] = headers
            return [{"id": 99, "order_number": "ORD-9001"}]

    class _FakeAdapter:
        def __init__(self):
            self.client = _FakeClient()
            self.response_contract = ResolvedResponseContract(
                order_profile="user_scoped_order_service",
                order_identifier_mode="order_number_with_internal_resolution",
            )
            self.order_action_contract = ResolvedOrderActionContract(
                submission_mode="per_action_query_endpoint",
                supported_actions=["list_orders", "get_order_status", "cancel", "refund"],
                request_fields=ResolvedRequestFieldContract(),
            )

    monkeypatch.setitem(
        _build_runtime_fixture_manifest.__globals__,
        "_load_generated_adapter",
        lambda **kwargs: _FakeAdapter(),
    )
    monkeypatch.setitem(
        _build_runtime_fixture_manifest.__globals__,
        "_build_generated_auth_headers",
        lambda **kwargs: {"Authorization": "Bearer bridge-token"},
    )

    plan = IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="django_project_urlconf_import_view",
            route_target="backend/project/urls.py",
            import_target="backend/project/urls.py",
            login_endpoint="/api/login",
            auth_handler_source="backend/users/views.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="site-c",
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api/api.js",
            chatbot_server_base_url="http://localhost:8100",
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="site-c",
            adapter_package="src/adapters/generated/site_c",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="GENERATED_SITE_C_API_URL",
            auth_validation_endpoint="/api/auth/me",
            current_user_endpoint="/api/auth/me",
            product_search_endpoint="/api/products",
            order_list_endpoint="/api/users/{user_id}/orders",
            order_detail_endpoint="/api/users/{user_id}/orders/{order_id}",
            order_action_endpoint="/api/users/{user_id}/orders/{order_id}/actions",
            auth_contract=ResolvedAuthContract(
                transport="bearer_token",
            ),
            response_contract=ResolvedResponseContract(
                order_profile="user_scoped_order_service",
                order_identifier_mode="order_number_with_internal_resolution",
            ),
            order_action_contract=ResolvedOrderActionContract(
                submission_mode="per_action_query_endpoint",
                supported_actions=["list_orders", "get_order_status", "cancel", "refund"],
                request_fields=ResolvedRequestFieldContract(),
            ),
        ),
    )

    manifest = _build_runtime_fixture_manifest(
        chatbot_runtime_workspace=tmp_path,
        runtime_plan=BackendRuntimePlan(
            framework="fastapi",
            backend_root=str(tmp_path / "backend"),
            command=["uvicorn", "app:app"],
            readiness_url="http://127.0.0.1:8125/api/chat/auth-token",
            listen_port=8125,
        ),
        plan=plan,
        prep_result=BackendRuntimePrepResult(
            framework="fastapi",
            passed=True,
            fixture_manifest={"seed_source": {}, "auth": {}},
        ),
        bootstrap_result={
            "passed": True,
            "bootstrap_payload": {
                "access_token": "bridge-token",
                "user": {"id": "7"},
            },
            "session_cookies": {},
        },
        adapter_auth_result={"passed": True, "validated_user": {"id": "7"}},
        onboarding_credentials=None,
    )

    assert manifest["available"] is True
    assert manifest["orders"]["lookup_order_id"] == "ORD-9001"
    assert manifest["orders"]["status_order_id"] == "ORD-9001"


def test_collect_widget_order_flow_report_patches_runtime_auth_without_chat_endpoint_adapter_setup(
    monkeypatch,
):
    import chatbot.src.runtime_auth as runtime_auth

    observed: dict[str, object] = {}
    real_import_module = _collect_widget_order_flow_report.__globals__["importlib"].import_module
    plan = _build_food_plan()

    class _FakeStatus:
        value = "paid"

    class _FakeOrder:
        status = _FakeStatus()

    class _FakeOrderStatus:
        order = _FakeOrder()

    class _FakeAdapter:
        site_id = "food"

        async def get_order_status(self, auth_context, status_input):
            observed["status_auth_context"] = auth_context
            observed["status_input"] = status_input
            return _FakeOrderStatus()

    fake_adapter = _FakeAdapter()
    fake_server_fastapi = types.SimpleNamespace(app=object())
    fake_client = types.SimpleNamespace()
    fake_chat_endpoint = types.SimpleNamespace(
        resolve_runtime_auth=runtime_auth.resolve_runtime_auth,
    )

    monkeypatch.setitem(
        _collect_widget_order_flow_report.__globals__,
        "TestClient",
        lambda app: fake_client,
    )

    def _fake_exercise_widget_order_flow(**kwargs):
        resolved = runtime_auth._resolve_adapter("food")
        observed.setdefault("resolved_adapters", []).append(resolved)
        return {"passed": True, "steps": []}

    monkeypatch.setitem(
        _collect_widget_order_flow_report.__globals__,
        "_exercise_widget_order_flow",
        _fake_exercise_widget_order_flow,
    )
    monkeypatch.setattr(
        _collect_widget_order_flow_report.__globals__["importlib"],
        "import_module",
        lambda name: types.SimpleNamespace(
            GetOrderStatusInput=lambda **kwargs: types.SimpleNamespace(**kwargs)
        )
        if name == "src.adapters.schema"
        else real_import_module(name),
    )

    reports = _collect_widget_order_flow_report(
        adapter=fake_adapter,
        auth_context=types.SimpleNamespace(
            accessToken="",
            cookies={"session_token": "real-session-token"},
        ),
        plan=plan,
        sample_context={
            "sampled_order_id": "ORD-1",
            "sampled_order_ui_item": {"order_id": "ORD-1"},
            "sampled_option_id": "OPT-1",
        },
        server_fastapi=fake_server_fastapi,
        chat_endpoint=fake_chat_endpoint,
    )

    assert reports["get_order_status"]["passed"] is True
    assert reports["list_orders"]["passed"] is True
    assert all(item is fake_adapter for item in observed["resolved_adapters"])


def test_resolve_bridge_auth_material_prefers_nested_auth_contract_over_legacy_fields():
    plan = IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="django_project_urlconf_import_view",
            route_target="backend/foodshop/urls.py",
            import_target="backend/foodshop/urls.py",
            login_endpoint="/api/users/login/",
            auth_handler_source="backend/users/views.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="food",
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api/api.js",
            chatbot_server_base_url="http://localhost:8100",
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="food",
            adapter_package="src/adapters/generated/food",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="GENERATED_FOOD_API_URL",
            auth_validation_endpoint="/api/users/me/",
            current_user_endpoint="/api/users/me/",
            product_search_endpoint="/api/products/",
            order_list_endpoint="/api/orders/",
            order_detail_endpoint="/api/orders/{order_id}/",
            order_action_endpoint="/api/orders/{order_id}/actions/",
            auth_contract=ResolvedAuthContract(
                transport="session_cookie",
                session_cookie_name="real_session",
            ),
            auth_transport="bearer_token",
            session_cookie_name="legacy_session",
        ),
    )

    auth_material, failure_summary = _resolve_bridge_auth_material(
        bootstrap_result={
            "bootstrap_payload": {"access_token": "synthetic-access-token"},
            "session_cookies": {
                "real_session": "real-session-token",
                "legacy_session": "stale-legacy-token",
            },
        },
        plan=plan,
    )

    assert failure_summary is None
    assert auth_material is not None
    assert auth_material["auth_transport"] == "session_cookie"
    assert auth_material["access_token"] == ""
    assert auth_material["cookies"]["real_session"] == "real-session-token"


def test_validate_host_auth_bootstrap_falls_back_to_validation_bridge_when_login_fails(
    monkeypatch, tmp_path: Path
):
    captured_urls: list[str] = []

    class _Response:
        def __init__(self, status_code: int, payload: dict[str, object], text: str):
            self.status_code = status_code
            self._payload = payload
            self.text = text

        def json(self):
            return self._payload

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            del json
            captured_urls.append(url)
            if url.endswith("/api/auth/login"):
                return _Response(500, {}, "oracle unavailable")
            return _Response(
                200,
                {
                    "authenticated": True,
                    "site_id": "bilyeo",
                    "access_token": "validation-bilyeo",
                    "user": {"id": "validation-user", "email": "test1@example.com"},
                },
                '{"authenticated": true}',
            )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.httpx.Client",
        lambda **kwargs: _Client(),
    )
    analysis_bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
        strict_coverage=True,
    )
    runtime_plan = BackendRuntimePlan(
        framework="flask",
        backend_root=str(tmp_path / "backend"),
        command=["python", "app.py"],
        readiness_url="http://127.0.0.1:8126/api/chat/auth-token",
        listen_port=8126,
    )

    result = validate_host_auth_bootstrap(
        run_root=tmp_path,
        host_runtime_workspace=tmp_path,
        runtime_plan=runtime_plan,
        snapshot=analysis_bundle.snapshot,
        plan=planning_bundle.integration_plan,
    )

    assert result["passed"] is True
    assert result["bootstrap_mode"] == "validation_bridge"
    assert result["failure_origin"] == "login"


def test_load_runtime_chat_modules_clears_chatbot_src_cache(tmp_path: Path):
    chatbot_workspace = tmp_path / "chatbot"
    chat_module_path = chatbot_workspace / "src" / "api" / "v1" / "endpoints" / "chat.py"
    chat_module_path.parent.mkdir(parents=True, exist_ok=True)
    for package_path in [
        chatbot_workspace / "src" / "__init__.py",
        chatbot_workspace / "src" / "api" / "__init__.py",
        chatbot_workspace / "src" / "api" / "v1" / "__init__.py",
        chatbot_workspace / "src" / "api" / "v1" / "endpoints" / "__init__.py",
    ]:
        package_path.write_text("", encoding="utf-8")
    chat_module_path.write_text(
        "MARKER = 'workspace-chat'\n"
        "def _build_stream_config(*args, **kwargs):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    (chatbot_workspace / "server_fastapi.py").write_text(
        "from __future__ import annotations\n\n"
        "import importlib\n"
        "import os\n"
        "import sys\n"
        "import types\n\n"
        "def _bootstrap_legacy_import_alias():\n"
        "    workspace_root = os.path.dirname(os.path.abspath(__file__))\n"
        "    if workspace_root not in sys.path:\n"
        "        sys.path.insert(0, workspace_root)\n"
        "    chatbot_src = importlib.import_module('src')\n"
        "    chatbot_ns = sys.modules.get('chatbot')\n"
        "    if chatbot_ns is None:\n"
        "        chatbot_ns = types.ModuleType('chatbot')\n"
        "        chatbot_ns.__path__ = [workspace_root]\n"
        "        sys.modules['chatbot'] = chatbot_ns\n"
        "    setattr(chatbot_ns, 'src', chatbot_src)\n"
        "    sys.modules['chatbot.src'] = chatbot_src\n\n"
        "_bootstrap_legacy_import_alias()\n"
        "from chatbot.src.api.v1.endpoints import chat as chat_endpoint\n"
        "app = object()\n",
        encoding="utf-8",
    )

    import types

    repo_chat = types.ModuleType("chatbot.src.api.v1.endpoints.chat")
    repo_chat.MARKER = "repo-chat"
    sys.modules["chatbot.src.api.v1.endpoints.chat"] = repo_chat

    runtime_server_fastapi, runtime_chat_endpoint = _load_runtime_chat_modules(
        chatbot_runtime_workspace=chatbot_workspace
    )

    assert getattr(runtime_server_fastapi, "app", None) is not None
    assert runtime_chat_endpoint.MARKER == "workspace-chat"
    assert sys.modules["chatbot.src.api.v1.endpoints.chat"].MARKER == "workspace-chat"


def test_load_generated_adapter_clears_stale_src_adapters_cache(tmp_path: Path, monkeypatch):
    chatbot_workspace = tmp_path / "chatbot"
    generated_root = chatbot_workspace / "src" / "adapters" / "generated" / "food"
    generated_root.mkdir(parents=True, exist_ok=True)
    for package_path in [
        chatbot_workspace / "src" / "__init__.py",
        chatbot_workspace / "src" / "adapters" / "__init__.py",
        generated_root / "__init__.py",
    ]:
        package_path.parent.mkdir(parents=True, exist_ok=True)
        package_path.write_text("", encoding="utf-8")
    (generated_root / "client.py").write_text(
        "class GeneratedFoodClient:\n"
        "    def __init__(self, base_url):\n"
        "        self.base_url = base_url\n",
        encoding="utf-8",
    )
    (generated_root / "adapter.py").write_text(
        "class GeneratedFoodAdapter:\n"
        "    def __init__(self, client):\n"
        "        self.client = client\n",
        encoding="utf-8",
    )

    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "backend"),
        command=["python"],
        readiness_url="http://127.0.0.1:8127/api/chat/auth-token",
        listen_port=8127,
    )
    plan = IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="django_project_urlconf_import_view",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/users/login/",
            auth_handler_source="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="food",
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="react_app_shell_outside_routes",
            mount_target="frontend/src/App.js",
            api_strategy="react_api_client_augment_existing",
            api_client_target="frontend/src/api.js",
            chatbot_server_base_url="http://localhost:8100",
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="food",
            adapter_package="src/adapters/generated/food",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="FOOD_SERVICE_URL",
            auth_validation_endpoint="/api/chat/auth-token",
            current_user_endpoint="/api/chat/auth-token",
            product_search_endpoint="/api/products/",
            order_list_endpoint="/api/orders/",
            order_detail_endpoint="/api/orders/{order_id}/",
            order_action_endpoint="/api/orders/{order_id}/actions/",
        ),
    )

    stale_src = types.ModuleType("src")
    stale_src.__path__ = [str(tmp_path / "stale-src")]
    stale_adapters = types.ModuleType("src.adapters")
    stale_adapters.__path__ = [str(tmp_path / "stale-src" / "adapters")]
    stale_chatbot_src = types.ModuleType("chatbot.src")
    stale_chatbot_src.__path__ = list(stale_src.__path__)
    stale_chatbot_adapters = types.ModuleType("chatbot.src.adapters")
    stale_chatbot_adapters.__path__ = list(stale_adapters.__path__)

    monkeypatch.setitem(sys.modules, "src", stale_src)
    monkeypatch.setitem(sys.modules, "src.adapters", stale_adapters)
    monkeypatch.setitem(sys.modules, "chatbot.src", stale_chatbot_src)
    monkeypatch.setitem(sys.modules, "chatbot.src.adapters", stale_chatbot_adapters)

    adapter = _load_generated_adapter(
        chatbot_runtime_workspace=chatbot_workspace,
        runtime_plan=runtime_plan,
        plan=plan,
    )

    assert adapter.__class__.__module__.startswith("src.adapters.generated.food")


def test_validate_chatbot_runtime_boot_injects_generated_host_base_url_env(
    monkeypatch, tmp_path: Path
):
    captured: dict[str, object] = {}

    def _fake_run(command, cwd, env, capture_output, text):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["env"] = dict(env)
        captured["capture_output"] = capture_output
        captured["text"] = text
        return types.SimpleNamespace(
            returncode=0,
            stdout="chatbot runtime boot passed\n",
            stderr="",
        )

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.subprocess.run",
        _fake_run,
    )
    runtime_plan = BackendRuntimePlan(
        framework="flask",
        backend_root=str(tmp_path / "backend"),
        command=["python", "app.py"],
        readiness_url="http://127.0.0.1:8128/api/chat/auth-token",
        listen_port=8128,
    )
    plan = IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="bilyeo",
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="vue_app_shell_outside_routes",
            mount_target="frontend/src/App.vue",
            api_strategy="vue_api_client_augment_existing",
            api_client_target="frontend/src/api.js",
            chatbot_server_base_url="http://localhost:8100",
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="bilyeo",
            adapter_package="src/adapters/generated/bilyeo",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="GENERATED_BILYEO_API_URL",
            auth_validation_endpoint="/api/chat/auth-token",
            current_user_endpoint="/api/chat/auth-token",
            product_search_endpoint="/api/products",
            order_list_endpoint="/api/orders/all",
            order_detail_endpoint="/api/orders/{order_id}",
            order_action_endpoint="/api/orders/{order_id}/exchange",
        ),
    )

    result = validate_chatbot_runtime_boot(
        chatbot_runtime_workspace=tmp_path,
        runtime_plan=runtime_plan,
        plan=plan,
    )

    assert result["passed"] is True
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["GENERATED_BILYEO_API_URL"] == "http://127.0.0.1:8128"


def test_validate_conversation_runtime_injects_generated_host_base_url_env(
    monkeypatch, tmp_path: Path
):
    runtime_plan = BackendRuntimePlan(
        framework="flask",
        backend_root=str(tmp_path / "backend"),
        command=["python", "app.py"],
        readiness_url="http://127.0.0.1:8129/api/chat/auth-token",
        listen_port=8129,
    )
    plan = IntegrationPlan(
        host_backend=HostBackendPlan(
            strategy="flask_app_register_blueprint",
            route_target="backend/app.py",
            import_target="backend/app.py",
            login_endpoint="/api/auth/login",
            auth_handler_source="backend/chat_auth.py",
            chat_auth_contract_path="/api/chat/auth-token",
            site_id="bilyeo",
        ),
        host_frontend=HostFrontendPlan(
            mount_strategy="vue_app_shell_outside_routes",
            mount_target="frontend/src/App.vue",
            api_strategy="vue_api_client_augment_existing",
            api_client_target="frontend/src/api.js",
            chatbot_server_base_url="http://localhost:8100",
        ),
        chatbot_bridge=ChatbotBridgePlan(
            site_key="bilyeo",
            adapter_package="src/adapters/generated/bilyeo",
            setup_target="src/adapters/setup.py",
            host_base_url_env_var="GENERATED_BILYEO_API_URL",
            auth_validation_endpoint="/api/chat/auth-token",
            current_user_endpoint="/api/chat/auth-token",
            product_search_endpoint="/api/products",
            order_list_endpoint="/api/orders/all",
            order_detail_endpoint="/api/orders/{order_id}",
            order_action_endpoint="/api/orders/{order_id}/exchange",
        ),
    )
    prep_fixture_manifest = {"seed_source": {}, "auth": {}}

    class _FakeClient:
        async def list_orders(self, headers):
            assert headers["Authorization"] == "Bearer 1"
            return [
                {"order_id": "7", "option_id": "synthetic-option-1"},
                {"order_id": "6"},
                {"order_id": "5"},
                {"order_id": "4"},
                {"order_id": "3"},
            ]

    class _FakeAdapter:
        def __init__(self):
            self.client = _FakeClient()

    monkeypatch.setitem(
        validate_conversation_runtime.__globals__,
        "_load_generated_adapter",
        lambda **kwargs: _FakeAdapter(),
    )
    monkeypatch.setitem(
        validate_conversation_runtime.__globals__,
        "_build_generated_auth_headers",
        lambda **kwargs: {"Authorization": "Bearer 1"},
    )

    def _fake_load_runtime_chat_modules(**kwargs):
        assert os.environ.get("GENERATED_BILYEO_API_URL") == "http://127.0.0.1:8129"
        return object(), object()

    async def _fake_unauthenticated(**kwargs):
        result = ConversationScenarioResult(
            scenario_id="unauthenticated_chat_request",
            mode="auth",
            conversation_id="conv-unauth",
            deterministic_passed=True,
            llm_passed=True,
            final_verdict="pass",
            transcript_path=str(tmp_path / "unauth.json"),
            trace_path=None,
        )
        return result, "{}"

    async def _fake_authenticated(**kwargs):
        assert os.environ.get("GENERATED_BILYEO_API_URL") == "http://127.0.0.1:8129"
        scenario = kwargs["scenario"]
        result = ConversationScenarioResult(
            scenario_id=scenario["scenario_id"],
            mode=scenario["mode"],
            conversation_id="conv-auth",
            deterministic_passed=True,
            llm_passed=True,
            final_verdict="pass",
            transcript_path=str(tmp_path / f"{scenario['scenario_id']}.json"),
            trace_path=str(tmp_path / f"{scenario['scenario_id']}.jsonl"),
        )
        return result, "{}", "{}", {"conversation_id": "conv-auth"}

    monkeypatch.setitem(
        validate_conversation_runtime.__globals__,
        "_load_runtime_chat_modules",
        _fake_load_runtime_chat_modules,
    )
    monkeypatch.setitem(
        validate_conversation_runtime.__globals__,
        "_build_conversation_scenarios",
        lambda **kwargs: [
            {"scenario_id": "unauthenticated_chat_request", "mode": "auth", "prompt": "hi"},
            {"scenario_id": "authenticated_list_orders", "mode": "read_only", "prompt": "orders"},
        ],
    )
    monkeypatch.setitem(
        validate_conversation_runtime.__globals__,
        "_run_unauthenticated_conversation_scenario",
        _fake_unauthenticated,
    )
    monkeypatch.setitem(
        validate_conversation_runtime.__globals__,
        "_run_authenticated_conversation_scenario",
        _fake_authenticated,
    )

    result = validate_conversation_runtime(
        run_root=tmp_path,
        chatbot_runtime_workspace=tmp_path,
        runtime_plan=runtime_plan,
        snapshot=build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo").snapshot,
        plan=plan,
        prep_result=BackendRuntimePrepResult(
            framework="flask",
            passed=True,
            fixture_manifest=prep_fixture_manifest,
        ),
        bootstrap_result={
            "passed": True,
            "bootstrap_payload": {"user": {"id": "1"}, "access_token": "1"},
            "session_cookies": {},
        },
        adapter_auth_result={"passed": True, "validated_user": {"id": "1"}},
    )

    assert result.passed is True


def test_observed_tool_names_fall_back_to_metadata_last_tool():
    response = {
        "metadata_state": {
            "order_context": {
                "last_tool": "get_user_orders",
            }
        }
    }

    observed = validate_conversation_runtime.__globals__["_augment_observed_tool_names"](
        response=response,
        observed_tool_names=[],
    )

    assert observed == ["list_orders"]


def test_authenticated_conversation_401_is_classified_as_auth_gate_failure():
    failures = _evaluate_conversation_deterministic_failures(
        scenario={"scenario_id": "authenticated_list_orders", "mode": "read_only", "expected_tool_names": []},
        response={
            "status_code": 401,
            "error_events": [],
            "metadata_state": {},
            "final_answer": "",
            "ui_interrupts": [],
        },
        observed_tool_names=[],
    )

    assert "auth_gate_failed" in failures


def test_finalize_conversation_scenario_result_records_failure_category():
    result = _finalize_conversation_scenario_result(
        scenario_id="authenticated_list_orders",
        mode="read_only",
        prompt="orders",
        final_answer="",
        transcript_path="/tmp/transcript.json",
        trace_path="/tmp/trace.jsonl",
        expected_tool_names=[],
        observed_tool_names=[],
        deterministic_failures=["auth_gate_failed", "unexpected status 401"],
        sampled_order_id=None,
        sampled_option_id=None,
        conversation_id="conv-auth",
    )

    assert result.deterministic_passed is False
    assert result.final_verdict == "fail"
    assert result.failure_category == "auth_gate_failed"


def test_runtime_base_url_uses_custom_chat_auth_contract_path():
    runtime_plan = BackendRuntimePlan(
        framework="flask",
        backend_root="/tmp/backend",
        command=["python", "app.py"],
        readiness_url="http://127.0.0.1:9000/custom/auth/bootstrap",
    )

    assert (
        _runtime_base_url(
            runtime_plan,
            chat_auth_contract_path="/custom/auth/bootstrap",
        )
        == "http://127.0.0.1:9000"
    )


def test_validation_runner_fails_when_chatbot_runtime_boot_fails(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan, **kwargs: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": False,
            "failure_summary": "chatbot runtime boot failed: No module named 'ecommerce.backend'",
            "related_files": ["server_fastapi.py", "src/tools/order_tools.py"],
        },
        raising=False,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "host auth bootstrap passed",
            "bootstrap_payload": {
                "authenticated": True,
                "site_id": "food",
                "access_token": "session-token",
                "user": {"id": "7"},
            },
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert [check.name for check in bundle.checks][:3] == [
        "backend_runtime_prep",
        "backend_runtime_boot",
        "chatbot_runtime_boot",
    ]
    assert bundle.checks[2].passed is False
    assert bundle.failure_signature == "chatbot_runtime_boot_chatbot_runtime_boot_failed_no_module_named_ecommerce_backend"


def test_validation_runner_fails_when_widget_bundle_fetch_uses_host_origin(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan, **kwargs: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": False,
            "failure_summary": "widget bundle fetch failed: resolved to host origin",
            "target_url": "http://127.0.0.1:8000/widget.js",
            "related_files": ["frontend/src/App.js"],
        },
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert [check.name for check in bundle.checks][:4] == [
        "backend_runtime_prep",
        "backend_runtime_boot",
        "chatbot_runtime_boot",
        "widget_bundle_fetch",
    ]
    assert bundle.checks[3].passed is False
    assert bundle.failure_signature == "widget_bundle_fetch_widget_bundle_fetch_failed_resolved_to_host_origin"


def test_failure_signature_distinguishes_runtime_validation_phases():
    assert build_failure_signature(check_name="backend_runtime_prep", summary="dependency install failed") == "backend_runtime_prep_dependency_install_failed"
    assert build_failure_signature(check_name="backend_runtime_boot", summary="django app boot failed") == "backend_runtime_boot_django_app_boot_failed"
    assert build_failure_signature(check_name="chatbot_runtime_boot", summary="chatbot runtime boot failed: No module named 'ecommerce.backend'") == "chatbot_runtime_boot_chatbot_runtime_boot_failed_no_module_named_ecommerce_backend"
    assert build_failure_signature(check_name="widget_order_e2e", summary="show_order_list missing") == "widget_order_e2e_show_order_list_missing"


def test_widget_order_e2e_report_tracks_all_required_flows():
    result = _evaluate_widget_order_flow_report(
        plan=_build_food_plan(),
        flow_reports={
            "get_order_status": {"passed": True, "steps": []},
            "list_orders": {"steps": ["show_order_list"], "fragments": ["list-stream"]},
            "cancel": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["cancel-1", "cancel-2"]},
            "refund": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["refund-1", "refund-2"]},
            "exchange": {"steps": ["show_order_list", "show_option_list", "confirm_order_action"], "fragments": ["exchange-1", "exchange-2", "exchange-3"]},
        },
        sample_context={
            "sampled_order_id": "sample-order-1",
            "sampled_option_id": "option-7",
            "scenario_mode": "sampled_order_with_sampled_option",
        },
    )

    assert result.passed is True
    assert result.covered_flows == ["list_orders", "get_order_status", "cancel", "refund", "exchange"]
    assert result.sampled_order_id == "sample-order-1"
    assert result.sampled_option_id == "option-7"
    assert result.scenario_mode == "sampled_order_with_sampled_option"


def test_widget_order_e2e_report_marks_missing_exchange_option_step_as_failure():
    result = _evaluate_widget_order_flow_report(
        plan=_build_food_plan(),
        flow_reports={
            "get_order_status": {"passed": True, "steps": []},
            "list_orders": {"steps": ["show_order_list"], "fragments": ["list-stream"]},
            "cancel": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["cancel-1", "cancel-2"]},
            "refund": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["refund-1", "refund-2"]},
            "exchange": {"steps": ["show_order_list", "confirm_order_action"], "fragments": ["exchange-1", "exchange-2"]},
        },
    )

    assert result.passed is False
    assert result.failure_summary == "show_option_list missing"


def test_validation_runner_uses_explicit_credentials_without_manifest(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan, **kwargs: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    captured = {}

    def _bootstrap(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "passed": True,
            "failure_summary": "host auth bootstrap passed",
            "bootstrap_payload": {
                "authenticated": True,
                "site_id": "food",
                "access_token": "session-token",
                "user": {"id": "7"},
            },
            "related_files": [],
        }

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        _bootstrap,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_adapter_auth",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot adapter auth passed",
            "validated_user": {"id": "7", "siteId": "food"},
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_order_e2e",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget order e2e passed",
            "related_files": [],
        },
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)
    manifest_path = runtime_context["generated_root"] / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
        onboarding_credentials={"email": "test1@example.com", "password": "password123"},
    )

    assert bundle.passed is True
    assert captured["kwargs"]["onboarding_credentials"]["email"] == "test1@example.com"
    assert not manifest_path.exists()


def test_validation_runner_requires_site_id_in_host_bootstrap(monkeypatch, tmp_path: Path):
    runtime_plan = BackendRuntimePlan(
        framework="django",
        backend_root=str(tmp_path / "runtime" / "food" / "food-run-v2" / "workspace" / "backend"),
        command=["python", "manage.py", "runserver", "127.0.0.1:8000"],
        readiness_url="http://127.0.0.1:8000/api/chat/auth-token",
    )
    runtime_state = BackendRuntimeState(
        framework="django",
        passed=True,
        pid=1234,
        command=runtime_plan.command,
        readiness_url=runtime_plan.readiness_url,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.prepare_backend_runtime",
        lambda **kwargs: BackendRuntimePrepResult(framework="django", passed=True),
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.build_backend_runtime_plan",
        lambda **kwargs: runtime_plan,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.launch_backend_runtime",
        lambda plan, **kwargs: runtime_state,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.stop_backend_runtime",
        lambda state: None,
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_runtime_boot",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "chatbot runtime boot passed",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_host_auth_bootstrap",
        lambda **kwargs: {
            "passed": False,
            "failure_summary": "host auth bootstrap missing site_id",
            "related_files": ["backend/chat_auth.py"],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_bundle_fetch",
        lambda **kwargs: {
            "passed": True,
            "failure_summary": "widget bundle fetch passed",
            "target_url": "http://localhost:8100/widget.js",
            "related_files": [],
        },
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_chatbot_adapter_auth",
        lambda **kwargs: {"passed": True, "failure_summary": "chatbot adapter auth passed", "related_files": []},
    )
    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.validation.runner.validate_widget_order_e2e",
        lambda **kwargs: {"passed": True, "failure_summary": "widget order e2e passed", "related_files": []},
    )
    runtime_context = _build_food_runtime_artifacts(tmp_path)

    bundle = run_validation(
        run_root=runtime_context["generated_root"],
        host_runtime_workspace=runtime_context["apply_result"].host_workspace_path,
        chatbot_runtime_workspace=runtime_context["apply_result"].chatbot_workspace_path,
        snapshot=runtime_context["snapshot"],
        plan=runtime_context["plan"],
        replay_result=runtime_context["replay_result"],
        artifact_refs=runtime_context["artifact_refs"],
    )

    assert bundle.passed is False
    assert bundle.checks[4].name == "host_auth_bootstrap"
    assert bundle.failure_signature == "host_auth_bootstrap_host_auth_bootstrap_missing_site_id"
