from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")
sys.modules.setdefault("langchain_ollama", types.SimpleNamespace(ChatOllama=object))

from chatbot.src.onboarding.patch_planner import (
    build_patch_proposal,
    write_llm_first_patch_proposal,
    write_llm_patch_draft,
    write_unified_diff_draft,
)


def test_build_patch_proposal_includes_strategy_summary_and_route_targets():
    proposal = build_patch_proposal(
        analysis={
            "auth": {"auth_style": "session_cookie"},
            "framework": {"backend": "django", "frontend": "react"},
        },
        codebase_map={
            "candidate_edit_targets": [
                {"path": "backend/shop/views.py", "reason": "auth handler"},
                {"path": "backend/shop/urls.py", "reason": "route target"},
                {"path": "frontend/src/App.js", "reason": "mount target"},
            ],
            "backend_strategy": "django",
            "frontend_strategy": "react",
            "backend_route_targets": [{"path": "backend/shop/urls.py", "reason": "project urlconf"}],
            "frontend_mount_targets": [{"path": "frontend/src/App.js", "reason": "app shell"}],
            "tool_registry_targets": [{"path": "backend/shop/views.py", "reason": "auth handler"}],
        },
        recommended_outputs=["chat_auth", "frontend_patch", "order_adapter"],
    )

    assert proposal["analysis_summary"]["backend_strategy"] == "django"
    assert proposal["analysis_summary"]["frontend_strategy"] == "react"
    assert proposal["analysis_summary"]["backend_route_targets"] == ["backend/shop/urls.py"]
    assert proposal["analysis_summary"]["frontend_mount_targets"] == ["frontend/src/App.js"]
    assert proposal["analysis_summary"]["tool_registry_targets"] == ["backend/shop/views.py"]


def test_strategy_patch_proposal_for_food_avoids_orders_auth_targets():
    contract = {
        "site": "food",
        "backend": {
            "framework": "django",
            "auth_style": "session_cookie",
            "route_registration_points": ["backend/users/urls.py"],
            "auth_source_paths": ["backend/users/views.py"],
            "user_resolver_paths": ["backend/users/views.py"],
        },
        "frontend": {
            "framework": "react",
            "app_shell_path": "frontend/src/App.js",
            "widget_mount_points": ["frontend/src/App.js"],
        },
    }
    proposal = build_patch_proposal(
        analysis={"integration_contract": contract},
        codebase_map={
            "integration_contract": contract,
            "candidate_edit_targets": [
                {"path": "backend/users/views.py", "reason": "users auth handler"},
                {"path": "backend/users/urls.py", "reason": "users route target"},
                {"path": "backend/orders/views.py", "reason": "orders auth handler"},
                {"path": "frontend/src/App.js", "reason": "react app shell"},
            ],
            "backend_strategy": "django",
            "frontend_strategy": "react",
            "backend_route_targets": [{"path": "backend/users/urls.py", "reason": "users urlconf"}],
            "frontend_mount_targets": [{"path": "frontend/src/App.js", "reason": "app shell"}],
            "tool_registry_targets": [{"path": "backend/users/views.py", "reason": "users auth handler"}],
        },
        recommended_outputs=["chat_auth", "frontend_patch"],
    )

    paths = {item["path"] for item in proposal["target_files"]}
    assert "backend/orders/views.py" not in paths
    assert "backend/users/urls.py" in paths
    assert "frontend/src/App.js" in paths


def test_strategy_patch_proposal_for_food_allows_frontend_api_client_targets():
    contract = {
        "site": "food",
        "backend": {
            "framework": "django",
            "auth_style": "session_cookie",
            "route_registration_points": ["backend/foodshop/urls.py"],
            "auth_source_paths": ["backend/users/views.py"],
            "user_resolver_paths": ["backend/users/views.py"],
        },
        "frontend": {
            "framework": "react",
            "app_shell_path": "frontend/src/App.js",
            "router_boundary_path": "frontend/src/App.js",
            "api_client_paths": ["frontend/src/api/api.js"],
            "widget_mount_points": ["frontend/src/App.js"],
        },
    }
    proposal = build_patch_proposal(
        analysis={"integration_contract": contract},
        codebase_map={
            "integration_contract": contract,
            "candidate_edit_targets": [
                {"path": "backend/users/views.py", "reason": "users auth handler"},
                {"path": "backend/foodshop/urls.py", "reason": "project route target"},
                {"path": "frontend/src/App.js", "reason": "react app shell"},
                {"path": "frontend/src/api/api.js", "reason": "api client target"},
            ],
            "backend_strategy": "django",
            "frontend_strategy": "react",
            "backend_route_targets": [{"path": "backend/foodshop/urls.py", "reason": "project urlconf"}],
            "frontend_mount_targets": [{"path": "frontend/src/App.js", "reason": "app shell"}],
            "tool_registry_targets": [{"path": "backend/users/views.py", "reason": "users auth handler"}],
        },
        recommended_outputs=["chat_auth", "frontend_patch"],
        llm_codebase_interpretation={
            "ranked_candidates": [
                {"path": "frontend/src/api/api.js", "reason": "api bootstrap integration point"},
                {"path": "frontend/src/App.js", "reason": "widget mount"},
            ]
        },
    )

    paths = {item["path"] for item in proposal["target_files"]}
    assert "frontend/src/api/api.js" in paths
    assert proposal["analysis_summary"]["strategy_allowlist"] == sorted(
        [
            "backend/foodshop/urls.py",
            "backend/users/views.py",
            "frontend/src/App.js",
            "frontend/src/api/api.js",
        ]
    )


def test_build_patch_proposal_filters_ranked_candidates_outside_strategy_allowlist():
    contract = {
        "site": "food",
        "backend": {
            "framework": "django",
            "auth_style": "session_cookie",
            "route_registration_points": ["backend/foodshop/urls.py"],
            "auth_source_paths": ["backend/users/views.py"],
            "user_resolver_paths": ["backend/users/views.py"],
        },
        "frontend": {
            "framework": "react",
            "app_shell_path": "frontend/src/App.js",
            "router_boundary_path": "frontend/src/App.js",
            "widget_mount_points": ["frontend/src/App.js"],
        },
    }
    proposal = build_patch_proposal(
        analysis={"integration_contract": contract},
        codebase_map={
            "integration_contract": contract,
            "candidate_edit_targets": [
                {"path": "backend/users/views.py", "reason": "users auth handler"},
                {"path": "backend/foodshop/urls.py", "reason": "project route target"},
                {"path": "frontend/src/App.js", "reason": "react app shell"},
                {"path": "frontend/src/views/Orders.js", "reason": "orders screen"},
            ],
            "backend_route_targets": [{"path": "backend/foodshop/urls.py", "reason": "project urlconf"}],
            "frontend_mount_targets": [{"path": "frontend/src/App.js", "reason": "app shell"}],
            "tool_registry_targets": [{"path": "backend/users/views.py", "reason": "users auth handler"}],
        },
        recommended_outputs=["chat_auth", "frontend_patch"],
        llm_codebase_interpretation={
            "ranked_candidates": [
                {"path": "frontend/src/views/Orders.js", "reason": "incorrect frontend target"},
            ]
        },
    )

    paths = {item["path"] for item in proposal["target_files"]}
    assert "frontend/src/views/Orders.js" not in paths
    assert "frontend/src/App.js" in paths


def test_build_patch_proposal_rejects_build_artifact_mount_target():
    contract = {
        "site": "food",
        "frontend": {
            "framework": "react",
            "app_shell_path": "frontend/build/static/js/main.abc.js",
            "widget_mount_points": ["frontend/build/static/js/main.abc.js"],
        },
    }
    proposal = build_patch_proposal(
        analysis={"integration_contract": contract},
        codebase_map={
            "integration_contract": contract,
            "candidate_edit_targets": [
                {"path": "frontend/build/static/js/main.abc.js", "reason": "bundled mount target"},
                {"path": "frontend/src/App.js", "reason": "source app shell"},
            ],
            "frontend_mount_targets": [
                {"path": "frontend/build/static/js/main.abc.js", "reason": "bundled mount target"},
                {"path": "frontend/src/App.js", "reason": "source app shell"},
            ],
        },
        recommended_outputs=["frontend_patch"],
    )

    paths = {item["path"] for item in proposal["target_files"]}
    assert "frontend/build/static/js/main.abc.js" not in paths
    assert proposal["analysis_summary"]["target_rejections"] == [
        {
            "path": "frontend/build/static/js/main.abc.js",
            "reason": "build_artifact_target",
        }
    ]


def test_strategy_patch_proposal_for_bilyeo_targets_flask_auth_and_vue_shell():
    contract = {
        "site": "bilyeo",
        "backend": {
            "framework": "flask",
            "auth_style": "session",
            "route_registration_points": ["backend/app.py"],
            "auth_source_paths": ["backend/routes/auth.py"],
            "user_resolver_paths": ["backend/routes/auth.py"],
        },
        "frontend": {
            "framework": "vue",
            "app_shell_path": "frontend/src/App.vue",
            "widget_mount_points": ["frontend/src/App.vue"],
        },
    }
    proposal = build_patch_proposal(
        analysis={"integration_contract": contract},
        codebase_map={
            "integration_contract": contract,
            "candidate_edit_targets": [
                {"path": "backend/app.py", "reason": "flask entrypoint"},
                {"path": "backend/routes/auth.py", "reason": "auth blueprint"},
                {"path": "frontend/src/App.vue", "reason": "vue shell"},
                {"path": "frontend/src/views/Orders.vue", "reason": "orders screen"},
            ],
            "backend_strategy": "flask",
            "frontend_strategy": "vue",
            "backend_route_targets": [{"path": "backend/app.py", "reason": "flask entrypoint"}],
            "frontend_mount_targets": [{"path": "frontend/src/App.vue", "reason": "vue shell"}],
            "tool_registry_targets": [{"path": "backend/routes/auth.py", "reason": "auth blueprint"}],
        },
        recommended_outputs=["chat_auth", "frontend_patch"],
    )

    paths = {item["path"] for item in proposal["target_files"]}
    assert "backend/app.py" in paths
    assert "backend/routes/auth.py" in paths
    assert "frontend/src/App.vue" in paths
    assert "frontend/src/views/Orders.vue" not in paths


def test_write_unified_diff_draft_inserts_auth_stub_after_existing_auth_view(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    source_file = source_root / "backend" / "users" / "views.py"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    output_path = run_root / "patches" / "proposed.patch"

    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "def login(request):\n"
        "    return None\n\n"
        "def me(request):\n"
        "    return None\n\n"
        "def healthcheck(request):\n"
        "    return None\n",
        encoding="utf-8",
    )
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "backend/users/views.py",
                        "reason": "auth handler",
                        "intent": "add onboarding auth stub",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=proposal_path,
        output_path=output_path,
    )

    content = output_path.read_text(encoding="utf-8")

    assert "+def onboarding_chat_auth_token(request):\n" in content
    assert " def me(request):\n     return None\n \n+\n+def onboarding_chat_auth_token(request):\n" in content
    assert '+    """Generated onboarding stub for runtime-only integration."""\n' in content
    assert "+    return None\n def healthcheck(request):\n" in content


def test_write_unified_diff_draft_inserts_django_route_inside_urlpatterns(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    source_file = source_root / "backend" / "foodshop" / "urls.py"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    output_path = run_root / "patches" / "proposed.patch"

    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "from django.urls import include, path\n\n"
        "urlpatterns = [\n"
        '    path("api/orders/", include("orders.urls")),\n'
        "]\n",
        encoding="utf-8",
    )
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "backend/foodshop/urls.py",
                        "reason": "project urlconf",
                        "intent": "register onboarding auth route",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=proposal_path,
        output_path=output_path,
    )

    content = output_path.read_text(encoding="utf-8")

    assert '+from users.views import onboarding_chat_auth_token\n' in content
    assert '+    path("api/chat/auth-token", onboarding_chat_auth_token),\n' in content
    assert ' urlpatterns = [\n' in content
    assert ' ]\n' in content
    assert '-]\n+# onboarding draft route registration\n' not in content


def test_write_unified_diff_draft_inserts_react_widget_inside_component_markup(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    source_file = source_root / "frontend" / "src" / "App.js"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    output_path = run_root / "patches" / "proposed.patch"

    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        'import { BrowserRouter } from "react-router-dom";\n\n'
        "export default function App() {\n"
        "  return (\n"
        "    <BrowserRouter>\n"
        "      <main>Home</main>\n"
        "    </BrowserRouter>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "frontend/src/App.js",
                        "reason": "frontend app shell",
                        "intent": "mount chatbot widget",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=proposal_path,
        output_path=output_path,
    )

    content = output_path.read_text(encoding="utf-8")

    assert '+const ORDER_CS_WIDGET_HOST_CONTRACT = {\n' in content
    assert '+  widgetBundlePath: "/widget.js",\n' in content
    assert '+      <order-cs-widget />\n' in content
    assert 'SharedChatbotWidget' not in content


def test_write_unified_diff_draft_inserts_fastapi_router_near_app_setup(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    source_file = source_root / "backend" / "app" / "main.py"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    output_path = run_root / "patches" / "proposed.patch"

    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n"
        'app.include_router(existing_router, prefix="/api")\n',
        encoding="utf-8",
    )
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "backend/app/main.py",
                        "reason": "fastapi entrypoint",
                        "intent": "register onboarding router",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=proposal_path,
        output_path=output_path,
    )

    content = output_path.read_text(encoding="utf-8")

    assert "+from backend.chat_auth import router as onboarding_chat_router\n" in content
    assert '+app.include_router(onboarding_chat_router)\n' in content
    assert '+app.include_router(onboarding_chat_router)\n app.include_router(existing_router, prefix="/api")\n' in content


def test_write_unified_diff_draft_inserts_flask_blueprint_near_app_setup(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    source_file = source_root / "backend" / "app.py"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    output_path = run_root / "patches" / "proposed.patch"

    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "from flask import Flask\n\n"
        "app = Flask(__name__)\n"
        "app.register_blueprint(existing_bp)\n",
        encoding="utf-8",
    )
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "backend/app.py",
                        "reason": "flask entrypoint",
                        "intent": "register onboarding blueprint",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=proposal_path,
        output_path=output_path,
    )

    content = output_path.read_text(encoding="utf-8")

    assert "+from backend.chat_auth import chat_auth_bp\n" in content
    assert "+app.register_blueprint(chat_auth_bp)\n" in content
    assert "+app.register_blueprint(chat_auth_bp)\n app.register_blueprint(existing_bp)\n" in content


def test_write_unified_diff_draft_respects_views_insertion_hint(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    source_file = source_root / "backend" / "users" / "views.py"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    output_path = run_root / "patches" / "proposed.patch"

    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "def login(request):\n"
        "    return None\n\n"
        "def me(request):\n"
        "    return None\n\n"
        "def healthcheck(request):\n"
        "    return None\n",
        encoding="utf-8",
    )
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "backend/users/views.py",
                        "reason": "auth handler",
                        "intent": "add onboarding auth stub",
                        "insertion_hint": {
                            "anchor_text": "def login(request):",
                            "position": "after",
                            "notes": "insert after login",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=proposal_path,
        output_path=output_path,
    )

    content = output_path.read_text(encoding="utf-8")
    assert "+def onboarding_chat_auth_token(request):\n" in content
    assert content.index("+def onboarding_chat_auth_token(request):\n") < content.index(" def me(request):\n")


def test_write_unified_diff_draft_respects_urls_insertion_hint(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    source_file = source_root / "backend" / "foodshop" / "urls.py"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    output_path = run_root / "patches" / "proposed.patch"

    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "from django.urls import include, path\n\n"
        "urlpatterns = [\n"
        '    path("api/orders/", include("orders.urls")),\n'
        "]\n",
        encoding="utf-8",
    )
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "backend/foodshop/urls.py",
                        "reason": "project urlconf",
                        "intent": "register onboarding auth route",
                        "insertion_hint": {
                            "anchor_text": '    path("api/orders/", include("orders.urls")),',
                            "position": "after",
                            "notes": "insert after orders route",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=proposal_path,
        output_path=output_path,
    )

    content = output_path.read_text(encoding="utf-8")
    assert '     path("api/orders/", include("orders.urls")),\n+    path("api/chat/auth-token", onboarding_chat_auth_token),\n' in content


def test_write_unified_diff_draft_falls_back_when_insertion_hint_missing(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    source_file = source_root / "frontend" / "src" / "App.js"
    proposal_path = run_root / "reports" / "patch-proposal.json"
    output_path = run_root / "patches" / "proposed.patch"

    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        'import { BrowserRouter } from "react-router-dom";\n\n'
        "export default function App() {\n"
        "  return (\n"
        "    <BrowserRouter>\n"
        "      <main>Home</main>\n"
        "    </BrowserRouter>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "frontend/src/App.js",
                        "reason": "frontend app shell",
                        "intent": "mount chatbot widget",
                        "insertion_hint": {
                            "anchor_text": "<NonExistingAnchor />",
                            "position": "after",
                            "notes": "invalid anchor should fallback",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    write_unified_diff_draft(
        source_root=source_root,
        generated_run_root=run_root,
        proposal_path=proposal_path,
        output_path=output_path,
    )

    content = output_path.read_text(encoding="utf-8")
    assert '+      <order-cs-widget />\n' in content


def test_write_llm_first_patch_proposal_prefers_llm_output_when_valid(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "patch-proposal.json"
    execution_path = tmp_path / "reports" / "llm-patch-proposal-execution.json"
    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
            {"path": "backend/config/urls.py", "reason": "urlconf"},
        ]
    }

    class FakeLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "target_files": [
                                {
                                    "path": "backend/users/views.py",
                                    "reason": "session auth entrypoint",
                                    "intent": "add onboarding auth stub",
                                }
                            ],
                            "supporting_generated_files": ["files/backend/chat_auth.py"],
                            "recommended_outputs": ["chat_auth"],
                            "analysis_summary": {
                                "auth_style": "session_cookie",
                                "frontend_mount_points": [],
                                "route_prefixes": ["/api"],
                            },
                        }
                    )
                },
            )()

    write_llm_first_patch_proposal(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        output_path=output_path,
        execution_output_path=execution_path,
        llm_factory=lambda: FakeLLM(),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))

    assert payload["target_files"][0]["path"] == "backend/users/views.py"
    assert payload["recommended_outputs"] == ["chat_auth"]
    assert execution["source"] == "llm"
    assert execution["fallback_reason"] is None


def test_write_llm_first_patch_proposal_recovery_normalizes_single_target_shape(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "patch-proposal.json"
    execution_path = tmp_path / "reports" / "llm-patch-proposal-execution.json"
    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
        ]
    }

    class RecoverableLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "target_files": {
                                "path": "backend/users/views.py",
                                "reason": "session auth entrypoint",
                                "intent": "add onboarding auth stub",
                            },
                            "supporting_generated_files": "files/backend/chat_auth.py",
                            "recommended_outputs": "chat_auth",
                            "analysis_summary": {
                                "auth_style": "session_cookie",
                                "frontend_mount_points": [],
                                "route_prefixes": [],
                            },
                        }
                    )
                },
            )()

    write_llm_first_patch_proposal(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        output_path=output_path,
        execution_output_path=execution_path,
        llm_factory=lambda: RecoverableLLM(),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))

    assert payload["target_files"][0]["path"] == "backend/users/views.py"
    assert execution["source"] == "recovered_llm"
    assert execution["recovery_reason"] == "patch_proposal_shape_normalized"
    assert execution["hard_fallback_reason"] is None


def test_write_llm_first_patch_proposal_recovery_normalizes_alias_fields_and_string_targets(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "patch-proposal.json"
    execution_path = tmp_path / "reports" / "llm-patch-proposal-execution.json"
    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
        ]
    }

    class RecoverableAliasLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "targetFiles": ["backend/users/views.py"],
                            "supportingGeneratedFiles": "files/backend/chat_auth.py",
                            "recommendedOutputs": "chat_auth",
                        }
                    )
                },
            )()

    write_llm_first_patch_proposal(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        output_path=output_path,
        execution_output_path=execution_path,
        llm_factory=lambda: RecoverableAliasLLM(),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))

    assert payload["target_files"][0]["path"] == "backend/users/views.py"
    assert payload["target_files"][0]["reason"] == "auth handler"
    assert "chat auth" in payload["target_files"][0]["intent"]
    assert payload["analysis_summary"]["auth_style"] == "session_cookie"
    assert execution["source"] == "recovered_llm"
    assert execution["recovery_reason"] == "patch_proposal_shape_normalized"
    assert execution["hard_fallback_reason"] is None


def test_write_llm_first_patch_proposal_falls_back_on_invalid_json(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "patch-proposal.json"
    execution_path = tmp_path / "reports" / "llm-patch-proposal-execution.json"
    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
        ]
    }

    class BrokenLLM:
        def invoke(self, messages):
            return type("LLMResponse", (), {"content": "not-json"})()

    write_llm_first_patch_proposal(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        output_path=output_path,
        execution_output_path=execution_path,
        llm_factory=lambda: BrokenLLM(),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))

    assert payload["target_files"][0]["path"] == "backend/users/views.py"
    assert execution["source"] == "hard_fallback"
    assert execution["fallback_reason"] == "invalid_llm_response"

    trace_lines = [
        json.loads(line)
        for line in (tmp_path / "reports" / "execution-trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = {(item["component"], item["event"]) for item in trace_lines}
    assert ("patch_planner", "llm_call_started") in events
    assert ("patch_planner", "hard_fallback_used") in events
    assert ("patch_planner", "artifact_written") in events


def test_write_llm_first_patch_proposal_writes_debug_artifact_for_invalid_payload(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "patch-proposal.json"
    execution_path = tmp_path / "reports" / "llm-patch-proposal-execution.json"
    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
        ]
    }

    class InvalidPayloadLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "target_files": [123],
                            "supporting_generated_files": ["files/backend/chat_auth.py"],
                            "recommended_outputs": ["chat_auth"],
                            "analysis_summary": [],
                        }
                    )
                },
            )()

    write_llm_first_patch_proposal(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        output_path=output_path,
        execution_output_path=execution_path,
        llm_factory=lambda: InvalidPayloadLLM(),
    )

    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    debug_payload = json.loads((tmp_path / "reports" / "llm-debug" / "patch-proposal.json").read_text(encoding="utf-8"))

    assert execution["source"] == "hard_fallback"
    assert execution["hard_fallback_reason"] == "invalid_llm_payload"
    assert debug_payload["status"] == "hard_fallback"
    assert debug_payload["hard_fallback_reason"] == "invalid_llm_payload"
    assert debug_payload["error_type"] == "invalid_llm_payload"
    assert "target_files" in debug_payload["error_message"]


def test_write_llm_first_patch_proposal_emits_acceptance_event_for_recovered_payload(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "patch-proposal.json"
    execution_path = tmp_path / "reports" / "llm-patch-proposal-execution.json"
    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
        ]
    }

    class RecoverableLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "target_files": {
                                "path": "backend/users/views.py",
                                "reason": "session auth entrypoint",
                                "intent": "add onboarding auth stub",
                            },
                            "supporting_generated_files": "files/backend/chat_auth.py",
                            "recommended_outputs": "chat_auth",
                            "analysis_summary": {
                                "auth_style": "session_cookie",
                                "frontend_mount_points": [],
                                "route_prefixes": [],
                            },
                        }
                    )
                },
            )()

    write_llm_first_patch_proposal(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        output_path=output_path,
        execution_output_path=execution_path,
        llm_factory=lambda: RecoverableLLM(),
    )

    trace_lines = [
        json.loads(line)
        for line in (tmp_path / "reports" / "execution-trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    accepted = [
        item
        for item in trace_lines
        if item["component"] == "patch_planner" and item["event"] == "llm_output_accepted"
    ]
    assert accepted
    assert accepted[-1]["source"] == "recovered_llm"
    assert accepted[-1]["recovery"] == {
        "applied": True,
        "reason": "patch_proposal_shape_normalized",
    }


def test_write_llm_patch_draft_emits_canonical_events_for_hard_fallback(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    class BrokenPatchLLM:
        def invoke(self, messages):
            return type("LLMResponse", (), {"content": "--- a/backend/users/views.py\n+++ b/backend/users/views.py\n@@ malformed\n"})()

    write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={"candidate_edit_targets": [{"path": "backend/users/views.py", "reason": "auth handler"}]},
        patch_proposal={
            "target_files": [{"path": "backend/users/views.py", "intent": "add auth stub"}],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: BrokenPatchLLM(),
    )

    trace_lines = [
        json.loads(line)
        for line in (run_root / "reports" / "execution-trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = {(item["component"], item["event"]) for item in trace_lines}

    assert ("patch_planner", "llm_call_started") in events
    assert ("patch_planner", "hard_fallback_used") in events
    assert ("patch_planner", "artifact_written") in events


def test_write_llm_first_patch_proposal_recovery_uses_hard_fallback_on_invalid_target_path(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "patch-proposal.json"
    execution_path = tmp_path / "reports" / "llm-patch-proposal-execution.json"
    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text("def login(request):\n    return None\n", encoding="utf-8")
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
        ]
    }

    class InvalidTargetLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "target_files": [
                                {
                                    "path": "backend/admin/views.py",
                                    "reason": "wrong target",
                                    "intent": "add onboarding auth stub",
                                }
                            ],
                            "supporting_generated_files": ["files/backend/chat_auth.py"],
                            "recommended_outputs": ["chat_auth"],
                            "analysis_summary": {
                                "auth_style": "session_cookie",
                                "frontend_mount_points": [],
                                "route_prefixes": [],
                            },
                        }
                    )
                },
            )()

    write_llm_first_patch_proposal(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        output_path=output_path,
        execution_output_path=execution_path,
        llm_factory=lambda: InvalidTargetLLM(),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))

    assert payload["target_files"][0]["path"] == "backend/users/views.py"
    assert execution["source"] == "hard_fallback"
    assert execution["hard_fallback_reason"] == "invalid_target_selection"


def test_write_llm_first_patch_proposal_includes_file_samples_in_prompt(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "patch-proposal.json"
    execution_path = tmp_path / "reports" / "llm-patch-proposal-execution.json"
    target_file = source_root / "backend" / "users" / "views.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
        ]
    }

    class CapturingLLM:
        def __init__(self):
            self.calls = []

        def invoke(self, messages):
            self.calls.append(messages)
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "target_files": [
                                {
                                    "path": "backend/users/views.py",
                                    "reason": "auth handler",
                                    "intent": "add onboarding auth stub",
                                    "insertion_hint": {
                                        "anchor_text": "def login(request):",
                                        "position": "after",
                                        "notes": "insert after login",
                                    },
                                }
                            ],
                            "supporting_generated_files": ["files/backend/chat_auth.py"],
                            "recommended_outputs": ["chat_auth"],
                            "analysis_summary": {
                                "auth_style": "session_cookie",
                                "frontend_mount_points": [],
                                "route_prefixes": [],
                            },
                        }
                    )
                },
            )()

    llm = CapturingLLM()
    write_llm_first_patch_proposal(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        output_path=output_path,
        execution_output_path=execution_path,
        llm_factory=lambda: llm,
    )

    prompt = str(llm.calls[0][1].content)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert "file_samples" in prompt
    assert "def login(request):" in prompt
    assert payload["target_files"][0]["insertion_hint"]["anchor_text"] == "def login(request):"
