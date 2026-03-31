from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

import onmo.app as app_module
import onmo.github_imports as github_imports


def _clear_runtime_state() -> None:
    app_module._RUN_REGISTRY.clear()
    app_module._SERVICE_REGISTRY.clear()
    app_module._GITHUB_IMPORT_REGISTRY.clear()
    app_module._GITHUB_OAUTH_STATE_REGISTRY.clear()


def setup_function() -> None:
    _clear_runtime_state()


def teardown_function() -> None:
    _clear_runtime_state()


def test_github_import_endpoint_starts_public_repo(monkeypatch):
    client = TestClient(app_module.app)

    monkeypatch.setattr(app_module, "_timestamp_slug", lambda: "20260327-120000")
    monkeypatch.setattr(
        app_module,
        "_probe_github_repository",
        lambda repo_url, access_token=None: app_module.GitHubRepoProbe(
            repo_url=repo_url,
            owner="acme",
            repo="shop-ui",
            default_branch="main",
            private=False,
            requires_auth=False,
            source_subdir="",
        ),
    )
    started: list[tuple[app_module.GitHubImportRun, str | None]] = []
    monkeypatch.setattr(
        app_module,
        "_start_github_import_background",
        lambda intent, access_token=None: started.append((intent, access_token)),
    )

    response = client.post(
        "/api/onboarding/github/imports",
        json={"repo_url": "https://github.com/acme/shop-ui"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "importing",
        "run_id": "shop-ui-github-20260327-120000",
        "site": "shop-ui",
    }
    assert started
    assert started[0][1] is None
    assert started[0][0].default_branch == "main"
    assert started[0][0].demo_enabled is False


def test_github_import_endpoint_returns_auth_required(monkeypatch):
    client = TestClient(app_module.app)

    monkeypatch.setattr(app_module, "_timestamp_slug", lambda: "20260327-120000")
    monkeypatch.setattr(
        app_module,
        "_probe_github_repository",
        lambda repo_url, access_token=None: app_module.GitHubRepoProbe(
            repo_url=repo_url,
            owner="acme",
            repo="private-shop",
            default_branch="main",
            private=True,
            requires_auth=True,
            source_subdir="",
        ),
    )

    response = client.post(
        "/api/onboarding/github/imports",
        json={"repo_url": "https://github.com/acme/private-shop"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "auth_required",
        "run_id": "private-shop-github-20260327-120000",
        "site": "private-shop",
        "authorize_url": "http://testserver/auth/github/start?run_id=private-shop-github-20260327-120000",
    }
    record = app_module._GITHUB_IMPORT_REGISTRY["private-shop-github-20260327-120000"]
    assert record.status == "pending_auth"


def test_github_oauth_start_redirects_to_github(monkeypatch):
    client = TestClient(app_module.app)
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-123")
    monkeypatch.setenv("ONMO_PUBLIC_BASE_URL", "http://localhost:8899")
    app_module._GITHUB_IMPORT_REGISTRY["private-shop-github-20260327-120000"] = app_module.GitHubImportRun(
        run_id="private-shop-github-20260327-120000",
        site="private-shop",
        repo_url="https://github.com/acme/private-shop",
        owner="acme",
        repo="private-shop",
        default_branch="main",
        generated_root="generated-v2",
        runtime_root="runtime-v2",
        created_at="2026-03-27T12:00:00+00:00",
        updated_at="2026-03-27T12:00:00+00:00",
        status="pending_auth",
        source_subdir="",
    )

    response = client.get(
        "/auth/github/start",
        params={"run_id": "private-shop-github-20260327-120000"},
        follow_redirects=False,
    )

    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-123" in location
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8899%2Fauth%2Fgithub%2Fcallback" in location
    assert app_module._GITHUB_OAUTH_STATE_REGISTRY


def test_github_oauth_callback_rejects_unknown_state():
    client = TestClient(app_module.app)

    response = client.get("/auth/github/callback?state=missing-state&code=oauth-code")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired GitHub OAuth state"


def test_dashboard_returns_synthetic_import_stage(monkeypatch, tmp_path: Path):
    client = TestClient(app_module.app)
    generated_root = tmp_path / "generated-v2"
    generated_root.mkdir(parents=True, exist_ok=True)

    run_id = "shop-ui-github-20260327-120000"
    app_module._GITHUB_IMPORT_REGISTRY[run_id] = app_module.GitHubImportRun(
        run_id=run_id,
        site="shop-ui",
        repo_url="https://github.com/acme/shop-ui",
        owner="acme",
        repo="shop-ui",
        default_branch="main",
        generated_root=str(generated_root),
        runtime_root=str(tmp_path / "runtime-v2"),
        created_at="2026-03-27T12:00:00+00:00",
        updated_at="2026-03-27T12:00:10+00:00",
        status="importing",
        summary="GitHub 저장소 소스를 내려받는 중입니다.",
        demo_enabled=False,
        source_subdir="",
    )
    monkeypatch.setattr(app_module, "_ensure_demo_services", lambda **kwargs: [])

    response = client.get(
        f"/api/onboarding/runs/{run_id}",
        params={"site": "shop-ui", "generated_root": str(generated_root)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stages"][0]["stage"] == "import"
    assert payload["stages"][0]["status"] == "running"
    assert payload["details"]["import"]["summary"] == "GitHub 저장소 소스를 내려받는 중입니다."
    assert payload["demo"]["status"] == "disabled"
    assert payload["story"]["steps"][0]["stage"] == "import"
    assert payload["story"]["current_stage"]["stage"] == "import"
    assert payload["story"]["focus_stage"]["stage"] == "import"
    assert payload["repair_story"]["active"] is False


def test_index_renders_cache_busted_static_assets(client=None):
    del client
    client = TestClient(app_module.app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert '/static/styles.css?v=' in html
    assert '/static/app.js?v=' in html
    assert "20260327l" not in html


def test_shutdown_terminates_registered_child_processes(tmp_path: Path):
    class _FakeProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.pid = 1234
            self.terminated = False
            self.wait_calls: list[int] = []

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            return self.returncode

        def kill(self):
            self.returncode = -9

    run_log = (tmp_path / "run.log").open("w", encoding="utf-8")
    service_log = (tmp_path / "service.log").open("w", encoding="utf-8")
    run_process = _FakeProcess()
    service_process = _FakeProcess()

    app_module._RUN_REGISTRY["bilyeo:demo-run"] = app_module.RunProcessRecord(
        site="bilyeo",
        run_id="demo-run",
        generated_root="generated-v2",
        runtime_root="runtime-v2",
        source_root="bilyeo",
        preview_url=None,
        demo_enabled=True,
        command=["python", "-m", "demo"],
        process=run_process,
        log_path=tmp_path / "run.log",
        log_handle=run_log,
        started_at="2026-03-30T00:00:00+00:00",
    )
    app_module._SERVICE_REGISTRY["bilyeo:frontend"] = app_module.ServiceProcessRecord(
        site="bilyeo",
        run_id="demo-run",
        service_name="frontend",
        label="Bilyeo frontend",
        working_directory=str(tmp_path),
        command=["npm", "run", "dev"],
        process=service_process,
        log_path=tmp_path / "service.log",
        log_handle=service_log,
        started_at="2026-03-30T00:00:00+00:00",
        url="http://127.0.0.1:3000/bilyeo/",
    )

    with TestClient(app_module.app):
        pass

    assert run_process.terminated is True
    assert service_process.terminated is True
    assert app_module._RUN_REGISTRY == {}
    assert app_module._SERVICE_REGISTRY == {}
    assert run_log.closed is True
    assert service_log.closed is True


def test_launch_onboarding_process_starts_demo_autostart_watcher(monkeypatch, tmp_path: Path):
    source_root = tmp_path / "food"
    source_root.mkdir(parents=True, exist_ok=True)

    class _FakeProcess:
        pid = 4321
        returncode = None

        def poll(self):
            return None

    monkeypatch.setattr(app_module.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess())
    watched: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(
        app_module,
        "_start_demo_autostart_watcher",
        lambda record: watched.append((record.site, record.run_id, record.demo_enabled)),
    )

    payload = app_module._launch_onboarding_process(
        site="food",
        source_root_arg=str(source_root),
        generated_root_arg=str(tmp_path / "generated-v2"),
        runtime_root_arg=str(tmp_path / "runtime-v2"),
        run_id="food-demo-20260328",
        preview_url="http://127.0.0.1:3000/food/",
        demo_enabled=True,
    )

    assert payload["status"] == "running"
    assert watched == [("food", "food-demo-20260328", True)]
    record = app_module._RUN_REGISTRY["food:food-demo-20260328"]
    record.log_handle.close()


def test_maybe_autostart_demo_services_starts_services_for_exported_demo_run(
    monkeypatch,
    tmp_path: Path,
):
    generated_root = tmp_path / "generated-v2"
    run_root = generated_root / "food" / "food-demo-exported"
    (run_root / "views").mkdir(parents=True, exist_ok=True)
    (run_root / "views" / "run-summary.json").write_text(
        json.dumps({"status": "exported"}, ensure_ascii=False),
        encoding="utf-8",
    )
    source_root = tmp_path / "food"
    source_root.mkdir(parents=True, exist_ok=True)

    class _FinishedProcess:
        pid = 9876
        returncode = 0

        def poll(self):
            return 0

    load_calls: list[Path] = []
    ensure_calls: list[dict[str, object]] = []

    def _fake_load_run_dashboard(*, run_root: Path, process=None):
        del process
        load_calls.append(Path(run_root))
        return {
            "run": {"source_root": str(source_root)},
            "process": {"preview_url": None},
            "details": {"validation": {"passed": True}},
        }

    def _fake_ensure_demo_services(**kwargs):
        ensure_calls.append(kwargs)
        return [{"service_name": "backend", "status": "ready"}]

    monkeypatch.setattr(app_module, "load_run_dashboard", _fake_load_run_dashboard)
    monkeypatch.setattr(app_module, "_ensure_demo_services", _fake_ensure_demo_services)

    log_path = tmp_path / "onmo.log"
    record = app_module.RunProcessRecord(
        site="food",
        run_id="food-demo-exported",
        generated_root=str(generated_root),
        runtime_root=str(tmp_path / "runtime-v2"),
        source_root=str(source_root),
        preview_url="http://127.0.0.1:3000/food/",
        demo_enabled=True,
        command=["python", "-m", "chatbot.scripts.run_onboarding_generation"],
        process=_FinishedProcess(),
        log_path=log_path,
        log_handle=log_path.open("w", encoding="utf-8"),
        started_at="2026-03-28T00:30:00+00:00",
    )

    services = app_module._maybe_autostart_demo_services(record)

    assert load_calls == [run_root]
    assert services == [{"service_name": "backend", "status": "ready"}]
    assert ensure_calls and ensure_calls[0]["site"] == "food"
    assert ensure_calls[0]["run_id"] == "food-demo-exported"
    assert ensure_calls[0]["preview_url"] == "http://127.0.0.1:3000/food/"


def test_maybe_autostart_demo_services_skips_disabled_or_non_exported_runs(
    monkeypatch,
    tmp_path: Path,
):
    generated_root = tmp_path / "generated-v2"
    run_root = generated_root / "food" / "food-demo-review"
    (run_root / "views").mkdir(parents=True, exist_ok=True)
    (run_root / "views" / "run-summary.json").write_text(
        json.dumps({"status": "failed_human_review"}, ensure_ascii=False),
        encoding="utf-8",
    )

    class _FinishedProcess:
        pid = 6543
        returncode = 0

        def poll(self):
            return 0

    ensure_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        app_module,
        "_ensure_demo_services",
        lambda **kwargs: ensure_calls.append(kwargs) or [],
    )

    first_log = tmp_path / "review.log"
    review_record = app_module.RunProcessRecord(
        site="food",
        run_id="food-demo-review",
        generated_root=str(generated_root),
        runtime_root=str(tmp_path / "runtime-v2"),
        source_root=str(tmp_path / "food"),
        preview_url="http://127.0.0.1:3000/food/",
        demo_enabled=True,
        command=["python"],
        process=_FinishedProcess(),
        log_path=first_log,
        log_handle=first_log.open("w", encoding="utf-8"),
        started_at="2026-03-28T00:31:00+00:00",
    )
    exported_run_root = generated_root / "food" / "food-demo-disabled"
    (exported_run_root / "views").mkdir(parents=True, exist_ok=True)
    (exported_run_root / "views" / "run-summary.json").write_text(
        json.dumps({"status": "exported"}, ensure_ascii=False),
        encoding="utf-8",
    )
    second_log = tmp_path / "disabled.log"
    disabled_record = app_module.RunProcessRecord(
        site="food",
        run_id="food-demo-disabled",
        generated_root=str(generated_root),
        runtime_root=str(tmp_path / "runtime-v2"),
        source_root=str(tmp_path / "food"),
        preview_url="http://127.0.0.1:3000/food/",
        demo_enabled=False,
        command=["python"],
        process=_FinishedProcess(),
        log_path=second_log,
        log_handle=second_log.open("w", encoding="utf-8"),
        started_at="2026-03-28T00:32:00+00:00",
    )

    assert app_module._maybe_autostart_demo_services(review_record) == []
    assert app_module._maybe_autostart_demo_services(disabled_record) == []
    assert ensure_calls == []
    disabled_record.log_handle.close()


def test_food_service_specs_adds_frontend_install_and_cra_safe_env(tmp_path: Path):
    source_root = tmp_path / "food"
    backend_root = source_root / "backend"
    frontend_root = source_root / "frontend"
    backend_root.mkdir(parents=True, exist_ok=True)
    frontend_root.mkdir(parents=True, exist_ok=True)
    (backend_root / "manage.py").write_text("print('ok')\n", encoding="utf-8")
    (frontend_root / "package.json").write_text('{"name":"food-frontend"}\n', encoding="utf-8")

    specs, blocked = app_module._food_service_specs(
        profile=app_module.KNOWN_LAUNCH_PROFILES["food"],
        source_root=source_root,
    )

    assert blocked == []
    frontend = next(spec for spec in specs if spec.service_name == "frontend")
    assert frontend.prepare_command == ["npm", "install"]
    assert frontend.prepare_sentinel == "node_modules"
    assert "HOST" not in frontend.env_overrides
    assert frontend.env_overrides["DANGEROUSLY_DISABLE_HOST_CHECK"] == "true"


def test_ensure_service_process_runs_prepare_command_before_launch(monkeypatch, tmp_path: Path):
    frontend_root = tmp_path / "frontend"
    frontend_root.mkdir(parents=True, exist_ok=True)
    (frontend_root / "package.json").write_text('{"name":"food-frontend"}\n', encoding="utf-8")

    events: list[tuple[str, object]] = []

    def _fake_run(command, **kwargs):
        events.append(("run", list(command)))
        return app_module.subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    class _FakeProcess:
        pid = 3210
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            del timeout
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    def _fake_popen(command, **kwargs):
        events.append(("popen", list(command)))
        return _FakeProcess()

    monkeypatch.setattr(app_module.subprocess, "run", _fake_run)
    monkeypatch.setattr(app_module.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(app_module, "_probe_tcp_port", lambda *args, **kwargs: False)

    snapshot = app_module._ensure_service_process(
        site="food",
        run_id="food-demo-install",
        spec=app_module.ServiceLaunchSpec(
            service_name="frontend",
            label="Food frontend",
            working_directory=frontend_root,
            command=["npm", "run", "dev"],
            url="http://127.0.0.1:3000/",
            healthcheck_port=3000,
            env_overrides={"PORT": "3000"},
            prepare_command=["npm", "install"],
            prepare_sentinel="node_modules",
        ),
    )

    assert events == [
        ("run", ["npm", "install"]),
        ("popen", ["npm", "run", "dev"]),
    ]
    assert snapshot["status"] == "starting"
    record = app_module._SERVICE_REGISTRY["food:frontend"]
    record.log_handle.close()


def test_build_demo_payload_exposes_primary_open_action_for_exported_preview():
    payload = app_module._build_demo_payload(
        run_payload={
            "run": {"status": "exported"},
            "details": {"validation": {"passed": True}},
        },
        service_snapshots=[
            {
                "name": "frontend",
                "label": "Bilyeo frontend",
                "status": "ready",
                "status_label": "Ready",
                "ready": True,
                "running": True,
                "url": "http://127.0.0.1:3000/bilyeo/",
            }
        ],
        preview_url="http://127.0.0.1:3000/bilyeo/",
    )

    assert payload["primary_action"] == {
        "label": "사이트 열기",
        "url": "http://127.0.0.1:3000/bilyeo/",
    }
    assert payload["launch_status"] == "ready"
    assert payload["open_url"] == "http://127.0.0.1:3000/bilyeo/"


def test_build_demo_payload_marks_blocked_launch_state_for_failed_bootstrap():
    payload = app_module._build_demo_payload(
        run_payload={
            "run": {"status": "exported"},
            "details": {"validation": {"passed": True}},
        },
        service_snapshots=[
            {
                "name": "backend",
                "label": "Food backend",
                "status": "blocked",
                "status_label": "Blocked",
                "ready": False,
                "running": False,
                "reason": "docker compose를 찾을 수 없습니다.",
                "url": "http://127.0.0.1:8000",
            }
        ],
        preview_url="http://127.0.0.1:3000/",
        launch_profile=app_module.KNOWN_LAUNCH_PROFILES["food"],
    )

    assert payload["status"] == "blocked"
    assert payload["launch_status"] == "blocked"
    assert payload["blocked_reason"] == "docker compose를 찾을 수 없습니다."
    assert payload["primary_action"] is None


def test_build_demo_payload_exposes_degraded_preview_signals_and_demo_credentials():
    payload = app_module._build_demo_payload(
        run_payload={
            "run": {
                "status": "exported",
                "retrieval_status": {
                    "faq": {"status": "completed"},
                    "policy": {"status": "completed"},
                    "discovery_image": {"status": "failed"},
                },
                "enabled_retrieval_corpora": ["faq", "policy"],
            },
            "details": {
                "validation": {
                    "passed": True,
                    "real_login_available": False,
                    "bridge_fallback_used": True,
                    "validation_warning_summary": "실제 사이트 로그인 불가",
                    "demo_auth": {"email": "test@example.com", "password": "password123"},
                }
            },
        },
        service_snapshots=[],
        preview_url="http://127.0.0.1:3000/bilyeo/",
    )

    assert payload["real_login_available"] is False
    assert payload["bridge_fallback_used"] is True
    assert payload["missing_retrieval_corpora"] == ["discovery_image"]
    assert payload["validation_warning_summary"] == "실제 사이트 로그인 불가"
    assert payload["demo_auth"]["email"] == "test@example.com"


def test_run_github_import_job_enables_demo_for_known_family(monkeypatch, tmp_path: Path):
    run_id = "food-github-20260330-101010"
    runtime_root = tmp_path / "runtime-v2"
    record = app_module.GitHubImportRun(
        run_id=run_id,
        site="food",
        repo_url="https://github.com/acme/food/tree/main/food",
        owner="acme",
        repo="food",
        default_branch="main",
        generated_root="generated-v2",
        runtime_root=str(runtime_root),
        created_at="2026-03-30T10:10:10+00:00",
        updated_at="2026-03-30T10:10:10+00:00",
        status="importing",
        summary="GitHub 저장소 정보를 확인하는 중입니다.",
        source_subdir="food",
        demo_enabled=False,
    )
    app_module._GITHUB_IMPORT_REGISTRY[run_id] = record

    extracted_root = tmp_path / "archive" / "repo"
    selected_root = extracted_root / "food"
    selected_root.mkdir(parents=True, exist_ok=True)
    launch_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        app_module,
        "_probe_github_repository",
        lambda repo_url, access_token=None: app_module.GitHubRepoProbe(
            repo_url=repo_url,
            owner="acme",
            repo="food",
            default_branch="main",
            private=False,
            requires_auth=False,
            source_subdir="food",
        ),
    )
    monkeypatch.setattr(app_module, "download_github_archive", lambda **kwargs: extracted_root)
    monkeypatch.setattr(app_module, "resolve_github_source_root", lambda root, subdir: selected_root)
    monkeypatch.setattr(
        app_module,
        "_launch_onboarding_process",
        lambda **kwargs: launch_calls.append(kwargs) or {"status": "running"},
    )

    app_module._run_github_import_job(run_id=run_id)

    updated = app_module._GITHUB_IMPORT_REGISTRY[run_id]
    assert updated.demo_enabled is True
    assert launch_calls and launch_calls[0]["demo_enabled"] is True
    assert launch_calls[0]["preview_url"] == "http://127.0.0.1:3000/"


def test_probe_github_repository_accepts_tree_subdir_url(monkeypatch):
    monkeypatch.setattr(
        github_imports,
        "_read_json_response",
        lambda request: {
            "default_branch": "main",
            "private": False,
        },
    )

    probe = github_imports.probe_github_repository(
        "https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN21-FINAL-5TEAM/tree/new_feature/food"
    )

    assert probe.owner == "SKNETWORKS-FAMILY-AICAMP"
    assert probe.repo == "SKN21-FINAL-5TEAM"
    assert probe.default_branch == "new_feature"
    assert probe.source_subdir == "food"


def test_github_import_endpoint_uses_tree_subdir_as_site(monkeypatch):
    client = TestClient(app_module.app)

    monkeypatch.setattr(app_module, "_timestamp_slug", lambda: "20260327-120000")
    monkeypatch.setattr(
        app_module,
        "_probe_github_repository",
        lambda repo_url, access_token=None: app_module.GitHubRepoProbe(
            repo_url=repo_url,
            owner="SKNETWORKS-FAMILY-AICAMP",
            repo="SKN21-FINAL-5TEAM",
            default_branch="new_feature",
            private=False,
            requires_auth=False,
            source_subdir="food",
        ),
    )
    monkeypatch.setattr(
        app_module,
        "_start_github_import_background",
        lambda intent, access_token=None: None,
    )

    response = client.post(
        "/api/onboarding/github/imports",
        json={
            "repo_url": "https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN21-FINAL-5TEAM/tree/new_feature/food"
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "importing",
        "run_id": "food-github-20260327-120000",
        "site": "food",
    }


def test_github_import_endpoint_accepts_env_attachment(monkeypatch, tmp_path: Path):
    client = TestClient(app_module.app)
    monkeypatch.setattr(app_module, "_timestamp_slug", lambda: "20260330-120000")
    monkeypatch.setattr(app_module, "DEFAULT_RUNTIME_ROOT_ARG", str(tmp_path / "runtime-v2"))
    monkeypatch.setattr(
        app_module,
        "_probe_github_repository",
        lambda repo_url, access_token=None: app_module.GitHubRepoProbe(
            repo_url=repo_url,
            owner="acme",
            repo="bilyeo",
            default_branch="main",
            private=False,
            requires_auth=False,
            source_subdir="",
        ),
    )
    started: list[tuple[app_module.GitHubImportRun, str | None]] = []
    monkeypatch.setattr(
        app_module,
        "_start_github_import_background",
        lambda intent, access_token=None: started.append((intent, access_token)),
    )

    response = client.post(
        "/api/onboarding/github/imports",
        data={
            "repo_url": "https://github.com/acme/bilyeo",
            "env_target_path": ".env",
        },
        files={
            "env_file": ("bilyeo.env", b"ORACLE_HOST=oracle.example.com\n", "text/plain"),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "importing",
        "run_id": "bilyeo-github-20260330-120000",
        "site": "bilyeo",
    }
    record = app_module._GITHUB_IMPORT_REGISTRY["bilyeo-github-20260330-120000"]
    assert record.env_target_path == ".env"
    assert record.env_attachment_name == "bilyeo.env"
    assert record.env_attachment_path
    attachment_path = Path(record.env_attachment_path)
    assert attachment_path.exists()
    assert attachment_path.read_text(encoding="utf-8") == "ORACLE_HOST=oracle.example.com\n"
    assert started and started[0][0].env_target_path == ".env"


def test_run_github_import_job_injects_env_attachment_before_launch(monkeypatch, tmp_path: Path):
    run_id = "bilyeo-github-20260330-121500"
    runtime_root = tmp_path / "runtime-v2"
    workdir_root = runtime_root / "_github_imports" / "bilyeo" / run_id
    attachment_root = app_module._github_import_attachment_root(
        runtime_root=runtime_root,
        site="bilyeo",
        run_id=run_id,
    )
    attachment_root.mkdir(parents=True, exist_ok=True)
    attachment_path = attachment_root / "prod.env"
    attachment_path.write_text("ORACLE_HOST=prod-db\n", encoding="utf-8")

    record = app_module.GitHubImportRun(
        run_id=run_id,
        site="bilyeo",
        repo_url="https://github.com/acme/bilyeo",
        owner="acme",
        repo="bilyeo",
        default_branch="main",
        generated_root="generated-v2",
        runtime_root=str(runtime_root),
        created_at="2026-03-30T12:15:00+00:00",
        updated_at="2026-03-30T12:15:00+00:00",
        status="importing",
        summary="GitHub 저장소 정보를 확인하는 중입니다.",
        source_subdir="",
        demo_enabled=False,
        env_target_path="backend/.env",
        env_attachment_name="prod.env",
        env_attachment_path=str(attachment_path),
    )
    app_module._GITHUB_IMPORT_REGISTRY[run_id] = record

    extracted_root = tmp_path / "archive" / "repo"
    selected_root = extracted_root / "backend-app"
    backend_root = selected_root / "backend"
    backend_root.mkdir(parents=True, exist_ok=True)
    (selected_root / "README.md").write_text("hello\n", encoding="utf-8")
    launch_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        app_module,
        "_probe_github_repository",
        lambda repo_url, access_token=None: app_module.GitHubRepoProbe(
            repo_url=repo_url,
            owner="acme",
            repo="bilyeo",
            default_branch="main",
            private=False,
            requires_auth=False,
            source_subdir="",
        ),
    )
    monkeypatch.setattr(app_module, "download_github_archive", lambda **kwargs: extracted_root)
    monkeypatch.setattr(app_module, "resolve_github_source_root", lambda root, subdir: selected_root)
    monkeypatch.setattr(
        app_module,
        "_launch_onboarding_process",
        lambda **kwargs: launch_calls.append(kwargs) or {"status": "running"},
    )

    app_module._run_github_import_job(run_id=run_id)

    source_root = workdir_root / "source"
    injected_env = source_root / "backend" / ".env"
    assert injected_env.exists()
    assert injected_env.read_text(encoding="utf-8") == "ORACLE_HOST=prod-db\n"
    assert launch_calls and launch_calls[0]["source_root_arg"] == str(source_root.resolve())


def test_resolve_preview_workspace_selection_prefers_export_replay(tmp_path: Path):
    run_root = tmp_path / "generated-v2" / "bilyeo" / "bilyeo-demo-preview"
    export_host = tmp_path / "runtime-v2" / "bilyeo" / "export-replay-workspace" / "host"
    export_chatbot = tmp_path / "runtime-v2" / "bilyeo" / "export-replay-workspace" / "chatbot"
    apply_host = tmp_path / "runtime-v2" / "bilyeo" / "workspace" / "host"
    apply_chatbot = tmp_path / "runtime-v2" / "bilyeo" / "workspace" / "chatbot"
    source_root = tmp_path / "source"
    export_host.mkdir(parents=True, exist_ok=True)
    export_chatbot.mkdir(parents=True, exist_ok=True)
    apply_host.mkdir(parents=True, exist_ok=True)
    apply_chatbot.mkdir(parents=True, exist_ok=True)
    source_root.mkdir(parents=True, exist_ok=True)
    artifact_dir = run_root / "artifacts" / "06-export" / "replay-result"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "v0001.json").write_text(
        json.dumps(
            {
                "payload": {
                    "host_replay_workspace_path": str(export_host),
                    "chatbot_replay_workspace_path": str(export_chatbot),
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    apply_dir = run_root / "artifacts" / "04-apply" / "apply-result"
    apply_dir.mkdir(parents=True, exist_ok=True)
    (apply_dir / "v0001.json").write_text(
        json.dumps(
            {
                "payload": {
                    "host_workspace_path": str(apply_host),
                    "chatbot_workspace_path": str(apply_chatbot),
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    selection = app_module._resolve_preview_workspace_selection(
        run_root=run_root,
        run_payload={"run": {"source_root": str(source_root)}},
    )

    assert selection.source_kind == "export_replay_workspace"
    assert selection.host_root == export_host.resolve()
    assert selection.chatbot_root == export_chatbot.resolve()


def test_resolve_preview_workspace_selection_falls_back_to_apply_then_source(tmp_path: Path):
    run_root = tmp_path / "generated-v2" / "food" / "food-demo-preview"
    apply_host = tmp_path / "runtime-v2" / "food" / "workspace" / "host"
    apply_chatbot = tmp_path / "runtime-v2" / "food" / "workspace" / "chatbot"
    source_root = tmp_path / "source"
    fallback_chatbot = (app_module.ROOT / "chatbot").resolve()
    apply_host.mkdir(parents=True, exist_ok=True)
    apply_chatbot.mkdir(parents=True, exist_ok=True)
    source_root.mkdir(parents=True, exist_ok=True)
    apply_dir = run_root / "artifacts" / "04-apply" / "apply-result"
    apply_dir.mkdir(parents=True, exist_ok=True)
    (apply_dir / "v0001.json").write_text(
        json.dumps(
            {
                "payload": {
                    "host_workspace_path": str(apply_host),
                    "chatbot_workspace_path": str(apply_chatbot),
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    apply_selection = app_module._resolve_preview_workspace_selection(
        run_root=run_root,
        run_payload={"run": {"source_root": str(source_root)}},
    )
    source_selection = app_module._resolve_preview_workspace_selection(
        run_root=run_root / "missing",
        run_payload={"run": {"source_root": str(source_root)}},
    )

    assert apply_selection.source_kind == "apply_workspace"
    assert apply_selection.host_root == apply_host.resolve()
    assert apply_selection.chatbot_root == apply_chatbot.resolve()
    assert source_selection.source_kind == "source_root"
    assert source_selection.host_root == source_root.resolve()
    assert source_selection.chatbot_root == fallback_chatbot


def test_bootstrap_launch_profile_waits_for_tcp_readiness(monkeypatch, tmp_path: Path):
    compose_path = tmp_path / "docker" / "AWS" / "docker-compose.yml"
    compose_path.parent.mkdir(parents=True, exist_ok=True)
    compose_path.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(app_module, "ROOT", tmp_path)
    probe_results = iter([False, False, True])
    monkeypatch.setattr(
        app_module.subprocess,
        "run",
        lambda *args, **kwargs: app_module.subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(app_module, "_probe_tcp_port", lambda port, host="127.0.0.1", timeout=0.4: next(probe_results))
    monkeypatch.setattr(app_module.time, "sleep", lambda seconds: None)
    monotonic_values = iter([0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr(app_module.time, "monotonic", lambda: next(monotonic_values))

    result = app_module._bootstrap_launch_profile(app_module.KNOWN_LAUNCH_PROFILES["bilyeo"])

    assert result["status"] == "ready"
    assert result["ready"] is True
    assert result["wait_target"] == "127.0.0.1:1521"


def test_bootstrap_launch_profile_times_out_when_readiness_never_arrives(monkeypatch, tmp_path: Path):
    compose_path = tmp_path / "docker" / "AWS" / "docker-compose.yml"
    compose_path.parent.mkdir(parents=True, exist_ok=True)
    compose_path.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(app_module, "ROOT", tmp_path)
    monkeypatch.setattr(
        app_module.subprocess,
        "run",
        lambda *args, **kwargs: app_module.subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(app_module, "_probe_tcp_port", lambda port, host="127.0.0.1", timeout=0.4: False)
    monkeypatch.setattr(app_module.time, "sleep", lambda seconds: None)
    monotonic_values = iter([0.0, 0.2, 0.4, 0.6, 0.8, 1.2])
    monkeypatch.setattr(app_module.time, "monotonic", lambda: next(monotonic_values))

    result = app_module._bootstrap_launch_profile(
        app_module.KnownLaunchProfile(
            site="demo",
            label="Demo",
            preview_url="http://127.0.0.1:3000/",
            backend_url="http://127.0.0.1:8000",
            frontend_url="http://127.0.0.1:3000/",
            bootstrap=app_module.BootstrapLaunchProfile(
                compose_service="demo-db",
                wait_strategy="tcp_port",
                wait_target="127.0.0.1:15432",
                timeout_seconds=1,
            ),
        )
    )

    assert result["status"] == "failed"
    assert result["ready"] is False
    assert "timed out" in result["reason"]


def test_build_demo_service_specs_uses_profile_env_overrides_without_site_branching(tmp_path: Path):
    host_root = tmp_path / "workspace" / "host"
    chatbot_root = tmp_path / "workspace" / "chatbot"
    (host_root / "backend").mkdir(parents=True, exist_ok=True)
    (host_root / "frontend").mkdir(parents=True, exist_ok=True)
    chatbot_root.mkdir(parents=True, exist_ok=True)
    (host_root / "backend" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (host_root / "frontend" / "package.json").write_text('{"name":"bilyeo-frontend"}\n', encoding="utf-8")
    (chatbot_root / "server_fastapi.py").write_text("app = object()\n", encoding="utf-8")

    specs, blocked = app_module._build_demo_service_specs(
        site="bilyeo",
        run_id="bilyeo-demo-runtime",
        host_root=host_root,
        chatbot_root=chatbot_root,
        preview_url="http://127.0.0.1:3000/bilyeo/",
        launch_profile=app_module.KNOWN_LAUNCH_PROFILES["bilyeo"],
        diagnostics={
            "preview_source_kind": "export_replay_workspace",
            "preview_host_root": str(host_root),
            "preview_chatbot_root": str(chatbot_root),
            "bootstrap_status": "ready",
            "bootstrap_wait_target": "127.0.0.1:1521",
        },
        capability_profile="order_cs_plus_retrieval",
        enabled_retrieval_corpora=["discovery_image", "faq"],
    )

    assert blocked == []
    frontend = next(spec for spec in specs if spec.service_name == "frontend")
    chatbot = next(spec for spec in specs if spec.service_name == "chatbot")
    assert frontend.env_overrides["VITE_API_BASE"] == "/api"
    assert frontend.env_overrides["VITE_CHATBOT_SERVER_BASE_URL"] == "http://127.0.0.1:8100"
    assert frontend.env_overrides["VITE_CAPABILITY_PROFILE"] == "order_cs_plus_retrieval"
    assert frontend.env_overrides["VITE_ENABLED_RETRIEVAL_CORPORA"] == "discovery_image,faq"
    assert chatbot.env_overrides["BACKEND_API_URL"] == "http://127.0.0.1:5000"
    assert chatbot.env_overrides["BILYEO_API_URL"] == "http://127.0.0.1:5000"


def test_build_launch_render_context_resolves_frontend_api_base_template(tmp_path: Path):
    context = app_module._build_launch_render_context(
        profile=app_module.KnownLaunchProfile(
            site="demo",
            label="Demo",
            preview_url="http://127.0.0.1:3000/",
            backend_url="http://127.0.0.1:8000",
            frontend_url="http://127.0.0.1:3000/",
            frontend_api_base_template="{backend_url}/api",
        ),
        service_root=tmp_path / "workspace" / "host" / "frontend",
        chatbot_root=tmp_path / "workspace" / "chatbot",
    )

    assert context["backend_url"] == "http://127.0.0.1:8000"
    assert context["frontend_api_base"] == "http://127.0.0.1:8000/api"


def test_build_launch_render_context_defaults_frontend_api_base_to_backend_url(tmp_path: Path):
    context = app_module._build_launch_render_context(
        profile=app_module.KnownLaunchProfile(
            site="demo",
            label="Demo",
            preview_url="http://127.0.0.1:3000/",
            backend_url="http://127.0.0.1:8000",
            frontend_url="http://127.0.0.1:3000/",
        ),
        service_root=tmp_path / "workspace" / "host" / "frontend",
        chatbot_root=tmp_path / "workspace" / "chatbot",
    )

    assert context["frontend_api_base"] == "http://127.0.0.1:8000"


def test_build_launch_render_context_includes_retrieval_contract_values(tmp_path: Path):
    context = app_module._build_launch_render_context(
        profile=app_module.KnownLaunchProfile(
            site="demo",
            label="Demo",
            preview_url="http://127.0.0.1:3000/",
            backend_url="http://127.0.0.1:8000",
            frontend_url="http://127.0.0.1:3000/",
        ),
        service_root=tmp_path / "workspace" / "host" / "frontend",
        chatbot_root=tmp_path / "workspace" / "chatbot",
        capability_profile="order_cs_plus_retrieval",
        enabled_retrieval_corpora=["discovery_image", "faq"],
    )

    assert context["capability_profile"] == "order_cs_plus_retrieval"
    assert context["enabled_retrieval_corpora_csv"] == "discovery_image,faq"


def test_release_bound_port_kills_foreign_processes(monkeypatch):
    calls: list[list[str]] = []

    def _fake_run(command, **kwargs):
        calls.append(list(command))
        if command[:2] == ["lsof", "-ti"]:
            return app_module.subprocess.CompletedProcess(command, 0, stdout="1234\n5678\n", stderr="")
        return app_module.subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    probe_values = iter([True, False])
    monkeypatch.setattr(app_module.subprocess, "run", _fake_run)
    monkeypatch.setattr(app_module, "_probe_tcp_port", lambda *args, **kwargs: next(probe_values))
    monkeypatch.setattr(app_module.time, "sleep", lambda seconds: None)

    failure = app_module._release_bound_port(
        port=5000,
        label="Bilyeo backend",
        protected_pids={9999},
    )

    assert failure is None
    assert calls == [
        ["lsof", "-ti", "tcp:5000"],
        ["kill", "-TERM", "1234", "5678"],
    ]


def test_release_bound_port_reports_failure_when_port_stays_busy(monkeypatch):
    def _fake_run(command, **kwargs):
        if command[:2] == ["lsof", "-ti"]:
            return app_module.subprocess.CompletedProcess(command, 0, stdout="1234\n", stderr="")
        return app_module.subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(app_module.subprocess, "run", _fake_run)
    monkeypatch.setattr(app_module, "_probe_tcp_port", lambda *args, **kwargs: True)
    monkeypatch.setattr(app_module.time, "sleep", lambda seconds: None)

    failure = app_module._release_bound_port(
        port=8100,
        label="Chatbot server",
        protected_pids=set(),
    )

    assert "port 8100 is already in use" in str(failure)
