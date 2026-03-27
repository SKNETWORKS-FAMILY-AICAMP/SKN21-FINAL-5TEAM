from __future__ import annotations

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
