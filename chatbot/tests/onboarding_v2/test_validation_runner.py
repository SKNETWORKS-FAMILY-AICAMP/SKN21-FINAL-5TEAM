import os
import sys
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
from chatbot.src.onboarding_v2.planning import build_planning_bundle
from chatbot.src.onboarding_v2.storage import ArtifactStore
from chatbot.src.onboarding_v2.validation.runner import (
    ConversationScenarioResult,
    ConversationValidationResult,
    _finalize_conversation_scenario_result,
    _evaluate_widget_order_flow_report,
    _enforce_required_rechecks,
    _run_conversation_llm_judge,
    _runtime_base_url,
    run_validation,
    validate_host_auth_bootstrap,
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
    assert bundle.checks[6].details["covered_flows"] == [
        "list_orders",
        "get_order_status",
        "cancel",
        "refund",
        "exchange",
    ]


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
    assert observed_events[0]["details"]["scenario_id"] == "unauthenticated_chat_request"
    assert observed_events[-1]["details"]["scenario_id"] == "authenticated_list_orders"


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
    assert result["login_status"] == 500
    assert result["bootstrap_status"] == 200
    assert result["login_response_text"] == "oracle unavailable"
    assert result["bootstrap_response_text"] == '{"authenticated": true}'
    assert captured_urls == [
        "http://127.0.0.1:8126/api/auth/login",
        "http://127.0.0.1:8126/api/chat/auth-token",
    ]


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
