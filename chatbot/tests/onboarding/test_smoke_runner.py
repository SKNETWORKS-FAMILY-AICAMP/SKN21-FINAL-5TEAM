import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.smoke_contract import SmokeTestPlan, SmokeTestStep
from chatbot.src.onboarding.smoke_runner import load_smoke_plan, run_smoke_tests


def test_load_smoke_plan_reads_manifest_steps(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {
                    "smoke": [
                        "smoke-tests/login.sh",
                        "smoke-tests/chat_auth_token.sh",
                    ]
                },
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = load_smoke_plan(run_root)

    assert isinstance(plan, SmokeTestPlan)
    assert len(plan.steps) == 2
    assert plan.steps[0].id == "login"
    assert plan.steps[0].script == "smoke-tests/login.sh"
    assert plan.steps[0].category == "general"
    assert plan.steps[1].id == "chat-auth-token"
    assert plan.steps[1].script == "smoke-tests/chat_auth_token.sh"
    assert plan.steps[1].category == "auth"


def test_run_smoke_tests_builds_request_response_summary(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            SmokeTestStep(
                id="login",
                script="smoke-tests/login.sh",
                category="auth",
            ),
        ]
    )
    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=plan,
    )

    assert len(results) == 1
    result = results[0]
    assert result["step_id"] == "login"
    assert result["step"] == "smoke-tests/login.sh"
    assert isinstance(result.get("request"), dict)
    assert isinstance(result.get("response"), dict)
    assert isinstance(result["response"].get("status"), int)
    assert "stdout" in result


def test_run_smoke_tests_rejects_empty_required_json_path(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-auth-empty"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-auth-empty" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "chat-auth-token",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/chat/auth-token",
                "expects": {
                    "status": 200,
                    "json_path_equals": {"authenticated": True},
                    "json_path_not_empty": ["access_token"],
                },
            },
        ]
    )

    probe_responses = iter([_FakeHttpResponse(200, {}, '{"authenticated": true, "access_token": ""}')])

    with patch("chatbot.src.onboarding.smoke_runner.urllib.request.urlopen", side_effect=lambda request, timeout=0: next(probe_responses)):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
        )

    assert results[0]["returncode"] == 1


def test_run_smoke_tests_validates_headers_and_body_substrings(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-widget-bundle"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-widget-bundle" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "widget-bundle",
                "kind": "http",
                "category": "frontend",
                "method": "GET",
                "url": "http://127.0.0.1:8000/widget.js",
                "expects": {
                    "status": 200,
                    "header_contains": {"content-type": "javascript"},
                    "body_contains": ["order-cs-widget"],
                },
            },
        ]
    )

    probe_responses = iter(
        [
            _FakeHttpResponse(
                200,
                {"content-type": "application/javascript; charset=utf-8"},
                "customElements.define('order-cs-widget', Widget);",
            )
        ]
    )

    with patch("chatbot.src.onboarding.smoke_runner.urllib.request.urlopen", side_effect=lambda request, timeout=0: next(probe_responses)):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
        )

    assert results[0]["returncode"] == 0


def test_run_smoke_tests_builds_chat_stream_probe_with_bootstrap_context(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-chat-stream"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-chat-stream" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "credentials": {},
            }
        ),
        encoding="utf-8",
    )
    plan = SmokeTestPlan(
        steps=[
            {
                "id": "chat-auth-token",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/chat/auth-token",
                "expects": {
                    "status": 200,
                    "json_keys": ["access_token", "site_id"],
                },
                "exports": {
                    "chat_auth.access_token": "json.access_token",
                    "chat_auth.site_id": "json.site_id",
                },
            },
            {
                "id": "chat-stream",
                "kind": "http",
                "category": "chat",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/v1/chat/stream",
                "body": {
                    "message": "주문 상태를 확인해줘",
                    "access_token": "{{chat_auth.access_token}}",
                    "site_id": "{{chat_auth.site_id}}",
                },
                "expects": {
                    "status": 200,
                    "header_contains": {"content-type": "text/event-stream"},
                    "body_contains": ["data:"],
                },
                "uses": ["chat_auth.access_token", "chat_auth.site_id"],
            },
        ]
    )

    captured_requests: list[object] = []

    def _fake_urlopen(request, timeout=0):
        captured_requests.append(request)
        if request.full_url.endswith("/api/chat/auth-token"):
            return _FakeHttpResponse(
                200,
                {"content-type": "application/json; charset=utf-8"},
                '{"access_token": "token-123", "site_id": "site-c"}',
            )
        return _StreamingOnlyHttpResponse(
            200,
            {"content-type": "text/event-stream; charset=utf-8"},
            'data: {"type":"metadata"}\n\n',
        )

    with patch("chatbot.src.onboarding.smoke_runner.urllib.request.urlopen", side_effect=_fake_urlopen):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
        )

    assert results[0]["returncode"] == 0
    assert results[1]["returncode"] == 0
    assert json.loads(results[1]["request"]["body"]) == {
        "message": "주문 상태를 확인해줘",
        "access_token": "token-123",
        "site_id": "site-c",
    }
    request_body = captured_requests[1].data.decode("utf-8")
    assert '"access_token": "token-123"' in request_body
    assert '"site_id": "site-c"' in request_body


def test_run_smoke_tests_parses_json_expectations_from_http_error(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-unauth"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-unauth" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "chat-auth-token-unauthenticated",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/chat/auth-token",
                "expects": {
                    "status": 401,
                    "json_path_equals": {"authenticated": False},
                },
            },
        ]
    )

    http_error = urllib.error.HTTPError(
        url="http://127.0.0.1:8000/api/chat/auth-token",
        code=401,
        msg="Unauthorized",
        hdrs={"content-type": "application/json"},
        fp=io.BytesIO(b'{"authenticated": false}'),
    )

    with patch("chatbot.src.onboarding.smoke_runner.urllib.request.urlopen", side_effect=http_error):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
        )

    assert results[0]["returncode"] == 0


def test_run_smoke_tests_ignores_extra_recovery_payload_fields(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-recovery-extra"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-recovery-extra" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "chat-auth-token",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/chat/auth-token",
                "expects": {
                    "status": 200,
                    "json_path_equals": {"authenticated": True},
                    "json_path_not_empty": ["access_token"],
                },
            },
        ]
    )

    probe_responses = iter(
        [_FakeHttpResponse(200, {}, '{"authenticated": true, "access_token": "token"}')]
    )

    with patch(
        "chatbot.src.onboarding.smoke_runner.urllib.request.urlopen",
        side_effect=lambda request, timeout=0: next(probe_responses),
    ):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
            recovery_payload={
                "classification": "backend_server_startup_failure",
                "should_retry": True,
                "repair_scope": "run_only",
                "recommendation_source": "deterministic",
                "guardrail_rejection_reason": None,
            },
        )

    assert results[0]["returncode"] == 0


def test_run_smoke_tests_executes_scripts_and_collects_results(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    smoke_root = run_root / "smoke-tests"

    runtime_workspace.mkdir(parents=True)
    smoke_root.mkdir(parents=True)

    script_path = smoke_root / "login.sh"
    script_path.write_text("#!/bin/sh\necho smoke-ok\n", encoding="utf-8")
    script_path.chmod(0o755)

    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=SmokeTestPlan(steps=["smoke-tests/login.sh"]),
    )

    assert len(results) == 1
    assert results[0]["step"] == "smoke-tests/login.sh"
    assert results[0]["returncode"] == 0
    assert results[0]["stdout"].strip() == "smoke-ok"


def test_run_smoke_tests_executes_relative_run_root_from_different_cwd(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    run_root = project_root / "generated" / "food" / "food-run-001"
    runtime_workspace = project_root / "runtime" / "food" / "food-run-001" / "workspace"
    smoke_root = run_root / "smoke-tests"

    runtime_workspace.mkdir(parents=True)
    smoke_root.mkdir(parents=True)

    script_path = smoke_root / "login.sh"
    script_path.write_text("#!/bin/sh\necho smoke-ok\n", encoding="utf-8")
    script_path.chmod(0o755)

    monkeypatch.chdir(project_root)

    results = run_smoke_tests(
        run_root=Path("generated") / "food" / "food-run-001",
        runtime_workspace=Path("runtime") / "food" / "food-run-001" / "workspace",
        plan=SmokeTestPlan(steps=["smoke-tests/login.sh"]),
    )

    assert len(results) == 1
    assert results[0]["returncode"] == 0
    assert results[0]["stdout"].strip() == "smoke-ok"


def test_run_smoke_tests_reports_missing_script(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"

    runtime_workspace.mkdir(parents=True)
    run_root.mkdir(parents=True)

    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=SmokeTestPlan(steps=["smoke-tests/missing.sh"]),
    )

    assert results[0]["returncode"] == 127
    assert "missing.sh" in results[0]["stderr"]


def test_load_smoke_plan_reads_step_metadata(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {
                    "smoke": [
                        {
                            "id": "chat-auth",
                            "script": "smoke-tests/chat_auth_token.sh",
                            "env": {"EXPECTED_STATUS": "200"},
                            "timeout_seconds": 5,
                            "required": True,
                            "category": "auth",
                        }
                    ]
                },
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = load_smoke_plan(run_root)

    assert plan == SmokeTestPlan(
        steps=[
            SmokeTestStep(
                id="chat-auth",
                script="smoke-tests/chat_auth_token.sh",
                env={"EXPECTED_STATUS": "200"},
                timeout_seconds=5,
                required=True,
                category="auth",
            )
        ]
    )


def test_run_smoke_tests_includes_timeout_and_env(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    smoke_root = run_root / "smoke-tests"

    runtime_workspace.mkdir(parents=True)
    smoke_root.mkdir(parents=True)

    script_path = smoke_root / "login.sh"
    script_path.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$EXPECTED_VALUE\"\n",
        encoding="utf-8",
    )
    script_path.chmod(0o755)

    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=SmokeTestPlan(
            steps=[
                SmokeTestStep(
                    id="login",
                    script="smoke-tests/login.sh",
                    env={"EXPECTED_VALUE": "ok"},
                    timeout_seconds=1,
                    required=True,
                    category="auth",
                )
            ]
        ),
    )

    assert results[0]["step"] == "smoke-tests/login.sh"
    assert results[0]["step_id"] == "login"
    assert results[0]["required"] is True
    assert results[0]["category"] == "auth"
    assert results[0]["timed_out"] is False
    assert results[0]["stdout"].strip() == "ok"


class _FakeHttpResponse:
    def __init__(self, status: int, headers: dict[str, str], body: str):
        self._status = status
        self._headers = headers
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def getcode(self) -> int:
        return self._status

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def getheaders(self):
        return list(self._headers.items())


class _StreamingOnlyHttpResponse(_FakeHttpResponse):
    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            raise TimeoutError("streaming probe must not read until EOF")
        return super().read(size)


def test_run_smoke_tests_executes_http_probes_and_exports_context(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-18T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "credentials": {"username": "demo", "password": "secret"},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "login",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/login",
                "body": {"username": "{{probe.credentials.username}}", "password": "{{probe.credentials.password}}"},
                "expects": {"status": 200},
                "exports": {"login.cookies": "headers['Set-Cookie']"},
            },
            {
                "id": "chat-auth-token",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/chat/auth-token",
                "headers": {"Cookie": "{{login.cookies}}"},
                "expects": {"status": 200, "json_keys": ["access_token"]},
                "exports": {"chat_auth.access_token": "json.access_token"},
            },
        ]
    )

    probe_responses = iter(
        [
            _FakeHttpResponse(200, {"Set-Cookie": "session=abc"}, '{"ok": true}'),
            _FakeHttpResponse(200, {}, '{"access_token": "token-123"}'),
        ]
    )

    with patch("chatbot.src.onboarding.smoke_runner.urllib.request.urlopen", side_effect=lambda request, timeout=0: next(probe_responses)):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
        )

    assert len(results) == 2
    assert results[0]["request"]["method"] == "POST"
    assert results[0]["response"]["status"] == 200
    assert results[0]["exports"]["login.cookies"] == "session=abc"
    assert results[1]["request"]["headers"]["Cookie"] == "session=abc"
    assert results[1]["exports"]["chat_auth.access_token"] == "token-123"

    smoke_context = json.loads((run_root / "reports" / "smoke-context.json").read_text(encoding="utf-8"))
    assert smoke_context["login.cookies"] == "session=abc"
    assert smoke_context["chat_auth.access_token"] == "token-123"


def test_run_smoke_tests_fails_auth_probe_when_credentials_are_missing(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-credentials"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-credentials" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "login",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/users/login/",
                "body": {"username": "{{probe.credentials.username}}", "password": "{{probe.credentials.password}}"},
                "expects": {"status": 200},
                "exports": {"login.cookies": "headers['Set-Cookie']"},
                "uses": ["probe.credentials.username", "probe.credentials.password"],
            },
        ]
    )

    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        plan=plan,
    )

    assert results[0]["returncode"] == 1
    assert results[0]["stderr"].startswith("Missing onboarding credentials for auth probe")
    assert results[0]["request"]["body"] is None


def test_run_smoke_tests_reports_missing_required_email_credentials(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-email"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-email" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "login",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/users/login/",
                "body": {"email": "{{probe.credentials.email}}", "password": "{{probe.credentials.password}}"},
                "expects": {"status": 200},
            }
        ]
    )

    results = run_smoke_tests(run_root=run_root, runtime_workspace=runtime_workspace, plan=plan)

    assert results[0]["returncode"] == 1
    assert "probe.credentials.email" in results[0]["stderr"]
    assert "probe.credentials.password" in results[0]["stderr"]


def test_run_smoke_tests_validates_json_path_equals_and_root_array_exports(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-shape"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-shape" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-shape",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-18T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "credentials": {"email": "test1@example.com", "password": "password123"},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "login",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/users/login/",
                "body": {"email": "{{probe.credentials.email}}", "password": "{{probe.credentials.password}}"},
                "expects": {"status": 200},
                "exports": {"login.cookies": "headers['Set-Cookie']"},
            },
            {
                "id": "session-me",
                "kind": "http",
                "category": "auth",
                "method": "GET",
                "url": "http://127.0.0.1:8000/api/users/me/",
                "headers": {"Cookie": "{{login.cookies}}"},
                "expects": {"status": 200, "json_path_equals": {"authenticated": True}},
                "exports": {"login.user_id": "json.user.id"},
            },
            {
                "id": "product-api",
                "kind": "http",
                "category": "catalog",
                "method": "GET",
                "url": "http://127.0.0.1:8000/api/products/",
                "headers": {"Cookie": "{{login.cookies}}"},
                "expects": {"status": 200, "json_type": "list", "json_array_min_length": 1},
                "exports": {"product.first_item": "json[0]"},
            },
        ]
    )

    probe_responses = iter(
        [
            _FakeHttpResponse(200, {"Set-Cookie": "session=abc"}, '{"ok": true, "user": {"id": 1}}'),
            _FakeHttpResponse(200, {}, '{"authenticated": true, "user": {"id": 1}}'),
            _FakeHttpResponse(200, {}, '[{"id": 1, "name": "apple"}]'),
        ]
    )

    with patch("chatbot.src.onboarding.smoke_runner.urllib.request.urlopen", side_effect=lambda request, timeout=0: next(probe_responses)):
        results = run_smoke_tests(run_root=run_root, runtime_workspace=runtime_workspace, plan=plan)

    assert [item["returncode"] for item in results] == [0, 0, 0]
    assert results[2]["exports"]["product.first_item"] == "{'id': 1, 'name': 'apple'}"


def test_run_smoke_tests_validates_named_array_wrapper_exports(tmp_path: Path):
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-shape"
    runtime_workspace = tmp_path / "runtime" / "bilyeo" / "bilyeo-run-shape" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "bilyeo-run-shape",
                "site": "bilyeo",
                "source_root": "/workspace/bilyeo",
                "created_at": "2026-03-18T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "credentials": {"email": "test@example.com", "password": "password123"},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "login",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/auth/login/",
                "body": {"email": "{{probe.credentials.email}}", "password": "{{probe.credentials.password}}"},
                "expects": {"status": 200, "json_keys": ["user"]},
                "exports": {"login.cookies": "headers['Set-Cookie']"},
            },
            {
                "id": "product-api",
                "kind": "http",
                "category": "catalog",
                "method": "GET",
                "url": "http://127.0.0.1:8000/api/products/",
                "headers": {"Cookie": "{{login.cookies}}"},
                "expects": {"status": 200, "json_keys": ["products"], "json_array_key": "products", "json_array_min_length": 1},
                "exports": {"product.first_item": "json.products[0]"},
            },
        ]
    )

    probe_responses = iter(
        [
            _FakeHttpResponse(200, {"Set-Cookie": "session=abc"}, '{"user": {"user_id": 1}}'),
            _FakeHttpResponse(200, {}, '{"products": [{"id": 1, "name": "chair"}]}'),
        ]
    )

    with patch("chatbot.src.onboarding.smoke_runner.urllib.request.urlopen", side_effect=lambda request, timeout=0: next(probe_responses)):
        results = run_smoke_tests(run_root=run_root, runtime_workspace=runtime_workspace, plan=plan)

    assert [item["returncode"] for item in results] == [0, 0]
    assert results[1]["exports"]["product.first_item"] == "{'id': 1, 'name': 'chair'}"


def test_run_smoke_tests_uses_explicit_probe_credentials_and_session_cookie(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-session"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-session" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-session",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-18T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "credentials": {"username": "demo", "password": "secret"},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "login",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/users/login/",
                "body": {"username": "{{probe.credentials.username}}", "password": "{{probe.credentials.password}}"},
                "expects": {"status": 200},
                "exports": {"login.cookies": "headers['Set-Cookie']"},
            },
            {
                "id": "session-me",
                "kind": "http",
                "category": "auth",
                "method": "GET",
                "url": "http://127.0.0.1:8000/api/users/me/",
                "headers": {"Cookie": "{{login.cookies}}"},
                "expects": {"status": 200, "json_keys": ["user"]},
                "exports": {"login.user_id": "json.user.id"},
                "uses": ["login.cookies"],
            },
        ]
    )

    probe_responses = iter(
        [
            _FakeHttpResponse(200, {"Set-Cookie": "sessionid=abc"}, '{"ok": true}'),
            _FakeHttpResponse(200, {}, '{"user": {"id": 7}}'),
        ]
    )

    with patch("chatbot.src.onboarding.smoke_runner.urllib.request.urlopen", side_effect=lambda request, timeout=0: next(probe_responses)):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
        )

    assert json.loads(results[0]["request"]["body"]) == {"username": "demo", "password": "secret"}
    assert results[1]["request"]["headers"]["Cookie"] == "sessionid=abc"
    smoke_context = json.loads((run_root / "reports" / "smoke-context.json").read_text(encoding="utf-8"))
    assert smoke_context["login.cookies"] == "sessionid=abc"
    assert smoke_context["login.user_id"] == "7"


def test_run_smoke_tests_preserves_strategy_metadata_in_results(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "login",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/login",
                "expects": {"status": 200},
                "exports": {"login.cookies": "headers['Set-Cookie']"},
                "uses": [],
                "strategy": "django",
            },
        ]
    )

    with patch(
        "chatbot.src.onboarding.smoke_runner.urllib.request.urlopen",
        return_value=_FakeHttpResponse(200, {"Set-Cookie": "session=abc"}, '{"ok": true}'),
    ):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
        )

    assert results[0]["uses"] == []
    assert results[0]["strategy"] == "django"


def test_run_smoke_tests_applies_recovery_probe_updates(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "chat-auth-token",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/chat/auth-token",
                "headers": {"Cookie": "{{login.cookies}}"},
                "body": {"scope": "default"},
                "expects": {"status": 200, "json_keys": ["access_token"]},
                "exports": {"chat_auth.access_token": "json.access_token"},
            },
        ]
    )
    recovery_payload = {
        "classification": "response_schema_mismatch",
        "should_retry": True,
        "proposed_probe_updates": [
            {
                "step_id": "chat-auth-token",
                "merge": {
                    "url": "http://127.0.0.1:8000/api/chat/recovered-auth-token",
                    "headers": {"X-Recovery-Attempt": "1"},
                    "body": {"scope": "recovered"},
                },
            }
        ],
        "proposed_schema_overrides": [],
    }

    with patch(
        "chatbot.src.onboarding.smoke_runner.urllib.request.urlopen",
        return_value=_FakeHttpResponse(200, {}, '{"access_token": "token-123"}'),
    ):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
            recovery_payload=recovery_payload,
        )

    assert results[0]["request"]["url"].endswith("/api/chat/recovered-auth-token")
    assert results[0]["request"]["headers"]["X-Recovery-Attempt"] == "1"
    assert json.loads(results[0]["request"]["body"]) == {"scope": "recovered"}


def test_run_smoke_tests_applies_recovery_schema_overrides(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "chat-auth-token",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/chat/auth-token",
                "expects": {"status": 200, "json_keys": ["access_token"]},
                "exports": {"chat_auth.access_token": "json.access_token"},
            },
        ]
    )
    recovery_payload = {
        "classification": "response_schema_mismatch",
        "should_retry": True,
        "proposed_probe_updates": [],
        "proposed_schema_overrides": [
            {
                "step_id": "chat-auth-token",
                "expects": {"json_keys": ["token"]},
                "exports": {"chat_auth.access_token": "json.token"},
            }
        ],
    }

    with patch(
        "chatbot.src.onboarding.smoke_runner.urllib.request.urlopen",
        return_value=_FakeHttpResponse(200, {}, '{"token": "token-123"}'),
    ):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
            recovery_payload=recovery_payload,
        )

    assert results[0]["returncode"] == 0
    assert results[0]["exports"]["chat_auth.access_token"] == "token-123"


def test_run_smoke_tests_records_recovery_provenance_in_results(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-001" / "workspace"
    run_root.mkdir(parents=True)
    runtime_workspace.mkdir(parents=True)

    plan = SmokeTestPlan(
        steps=[
            {
                "id": "chat-auth-token",
                "kind": "http",
                "category": "auth",
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/chat/auth-token",
                "expects": {"status": 200},
            },
        ]
    )
    recovery_payload = {
        "classification": "response_schema_mismatch",
        "should_retry": True,
        "proposed_probe_updates": [{"step_id": "chat-auth-token", "merge": {"headers": {"X-Recovery": "true"}}}],
        "proposed_schema_overrides": [],
    }

    with patch(
        "chatbot.src.onboarding.smoke_runner.urllib.request.urlopen",
        return_value=_FakeHttpResponse(200, {}, '{"ok": true}'),
    ):
        results = run_smoke_tests(
            run_root=run_root,
            runtime_workspace=runtime_workspace,
            plan=plan,
            recovery_payload=recovery_payload,
        )

    assert results[0]["recovery"]["classification"] == "response_schema_mismatch"
    assert results[0]["recovery"]["applied"] is True
    assert results[0]["recovery"]["probe_update_step_ids"] == ["chat-auth-token"]
