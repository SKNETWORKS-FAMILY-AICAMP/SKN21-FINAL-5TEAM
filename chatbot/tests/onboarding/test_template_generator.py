import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.template_generator import (
    generate_backend_tool_registry,
    generate_backend_route_patch,
    generate_chat_auth_template,
    generate_frontend_widget_artifact,
)
from chatbot.src.onboarding.shared_chatbot_assets import resolve_shared_chatbot_assets


def test_generate_chat_auth_template_for_food_site_creates_python_file(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    reports_root = run_root / "reports"
    files_root = run_root / "files"
    reports_root.mkdir(parents=True)
    files_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "auth": {
                        "login_entrypoints": ["backend/users/views.py:login"],
                        "me_entrypoints": ["backend/users/views.py:me"],
                    }
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_chat_auth_template(run_root)

    assert output_path == run_root / "files" / "backend" / "chat_auth.py"
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "chat_auth_token" in content
    assert "site-a" in content
    assert "issue_chat_token" in content
    assert 'request.COOKIES.get("session_token")' in content
    assert "SessionToken.objects.select_related" in content
    assert '"authenticated": False' in content
    assert "from django.views.decorators.csrf import csrf_exempt" in content
    assert "@csrf_exempt" in content


def test_generate_chat_auth_template_for_food_uses_repo_local_primitives(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-local"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-local",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-19T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "backend_strategy": "django",
                    "integration_contract": {
                        "backend": {
                            "framework": "django",
                            "auth_style": "session_cookie",
                            "auth_source_paths": ["backend/users/views.py"],
                            "route_registration_points": ["backend/users/urls.py"],
                        }
                    },
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    content = generate_chat_auth_template(run_root).read_text(encoding="utf-8")

    assert "chatbot.src.auth.chat_token" not in content
    assert "SessionToken" in content
    assert "def issue_chat_token" in content or "def issue_bridge_token" in content


def test_generate_chat_auth_template_for_bilyeo_site_uses_site_b(tmp_path: Path):
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "bilyeo-run-001",
                "site": "bilyeo",
                "source_root": "/workspace/bilyeo",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {"auth": {"login_entrypoints": ["backend/routes/auth.py:login"], "me_entrypoints": []}},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_chat_auth_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert "site-b" in content
    assert 'session.get("user_id")' in content
    assert 'session.get("email")' in content
    assert "issue_chat_token" in content


def test_generate_chat_auth_template_for_ecommerce_site_uses_access_token_cookie(tmp_path: Path):
    run_root = tmp_path / "generated" / "ecommerce" / "ecommerce-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "ecommerce-run-001",
                "site": "ecommerce",
                "source_root": "/workspace/ecommerce",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "auth": {
                        "login_entrypoints": ["backend/app/router/users/router.py:login"],
                        "me_entrypoints": ["backend/app/router/users/router.py:me"],
                    }
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_chat_auth_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert "site-c" in content
    assert 'request.cookies.get("access_token")' in content
    assert "crud.get_user_by_email" not in content
    assert "get_current_user" not in content


def test_generate_frontend_widget_artifact_writes_widget_file(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "frontend-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "frontend-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "frontend_widget_proposal": {
                        "widget_path": "frontend/src/chatbot/SharedChatbotWidget.jsx",
                        "imports": ["import React from 'react';"],
                        "component": "export default function SharedChatbotWidget() { return <div>Chat</div>; }",
                    }
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifact = generate_frontend_widget_artifact(
        run_root,
        proposal={
            "widget_path": "frontend/src/chatbot/SharedChatbotWidget.jsx",
            "content": "import React from 'react';\n\nexport default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        },
    )

    widget_file = run_root / "files" / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx"
    assert artifact["type"] == "widget"
    assert artifact["path"] == str(widget_file)
    assert widget_file.exists()
    assert "SharedChatbotWidget" in widget_file.read_text(encoding="utf-8")


def test_generate_frontend_widget_artifact_default_content_bootstraps_auth_without_external_widget_dependency(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "frontend-run-003"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "frontend-run-003",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "frontend_strategy": "react",
                    "frontend_widget_path": "frontend/src/chatbot/SharedChatbotWidget.jsx",
                },
                "generated_files": [],
                "patch_targets": [],
                "frontend_artifacts": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifact = generate_frontend_widget_artifact(run_root)
    content = Path(artifact["path"]).read_text(encoding="utf-8")

    assert "authBootstrapPath" in content
    assert "SharedChatbotWidget" in content
    assert "chatbotApiBase" in content
    assert '@shared-chatbot/ChatbotWidget' not in content
    assert "HostedChatbotWidget" not in content
    assert "useEffect" in content
    assert "useState" in content
    assert "fetch(sharedWidgetHost.authBootstrapPath" in content
    assert 'data-chatbot-status="authenticated"' in content
    assert 'http://localhost:8100' in content
    assert '/api/v1/chat/stream' in content
    assert 'placeholder="메시지를 입력하세요"' in content
    assert "'전송'" in content or '"전송"' in content


def test_resolve_shared_chatbot_assets_uses_code_owned_site_contract_for_food() -> None:
    config = resolve_shared_chatbot_assets("food")

    assert config.site_name == "food"
    assert config.site_id == "site-a"
    assert config.auth_bootstrap_path == "/api/chat/auth-token"
    assert config.stream_path == "/api/v1/chat/stream"
    assert config.chatbot_api_base_default == "http://localhost:8100"
    assert config.source_label == "shared_widget_runtime"




def test_generate_backend_route_patch_for_django_uses_strategy_target(tmp_path: Path):
    source_root = tmp_path / "workspace" / "food"
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)
    (source_root / "backend" / "foodshop").mkdir(parents=True)
    (source_root / "backend" / "foodshop" / "urls.py").write_text(
        "from django.urls import include, path\n\n"
        "urlpatterns = [\n"
        '    path("api/orders/", include("orders.urls")),\n'
        "]\n",
        encoding="utf-8",
    )

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": str(source_root),
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "backend_strategy": "django",
                    "backend_route_targets": ["backend/foodshop/urls.py"],
                },
                "generated_files": [],
                "patch_targets": [],
                "frontend_artifacts": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_backend_route_patch(run_root)

    assert output_path == run_root / "patches" / "backend_chat_auth_route.patch"
    content = output_path.read_text(encoding="utf-8")
    assert 'from chat_auth import chat_auth_token' in content
    assert 'path("api/chat/auth-token", chat_auth_token)' in content


def test_generate_backend_route_patch_for_fastapi_uses_include_router(tmp_path: Path):
    source_root = tmp_path / "workspace" / "ecommerce"
    run_root = tmp_path / "generated" / "ecommerce" / "ecommerce-run-001"
    run_root.mkdir(parents=True)
    (source_root / "backend" / "app").mkdir(parents=True)
    (source_root / "backend" / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        encoding="utf-8",
    )

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "ecommerce-run-001",
                "site": "ecommerce",
                "source_root": str(source_root),
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "backend_strategy": "fastapi",
                    "backend_route_targets": ["backend/app/main.py"],
                },
                "generated_files": [],
                "patch_targets": [],
                "frontend_artifacts": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_backend_route_patch(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert "from backend.chat_auth import router as onboarding_chat_router" in content
    assert "app.include_router(onboarding_chat_router)" in content


def test_generate_backend_tool_registry_includes_enabled_tools_and_targets(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-002"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-002",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "tool_registry_targets": ["backend/users/views.py"],
                    "product_api": ["/api/products/"],
                    "order_api": ["/api/orders/"],
                },
                "generated_files": [],
                "patch_targets": [],
                "frontend_artifacts": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_backend_tool_registry(run_root)
    content = output_path.read_text(encoding="utf-8")

    assert output_path == run_root / "files" / "backend" / "tool_registry.py"
    assert "GeneratedProductAdapterClient" in content
    assert "GeneratedOrderAdapterClient" in content
    assert '"product_list"' in content
    assert '"orders_list"' in content


def test_template_generator_import_does_not_require_qdrant_env(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[3]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(repo_root),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib; importlib.import_module('chatbot.src.onboarding.template_generator')",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
