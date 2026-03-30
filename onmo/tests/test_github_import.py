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
