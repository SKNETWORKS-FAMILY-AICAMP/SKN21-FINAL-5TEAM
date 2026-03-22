from __future__ import annotations

import json
import os
import sys
from types import ModuleType
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

fake_langchain_ollama = ModuleType("langchain_ollama")


class _FakeChatOllama:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


fake_langchain_ollama.ChatOllama = _FakeChatOllama
sys.modules.setdefault("langchain_ollama", fake_langchain_ollama)

from chatbot.src.onboarding.codebase_mapper import build_codebase_map, write_llm_codebase_interpretation
from chatbot.src.onboarding.patch_planner import build_patch_proposal


def test_build_codebase_map_detects_auth_and_urlconf_in_nonstandard_python_files(tmp_path: Path):
    source_root = tmp_path / "source"

    (source_root / "backend" / "account").mkdir(parents=True)
    (source_root / "backend" / "config").mkdir(parents=True)

    (source_root / "backend" / "account" / "handlers.py").write_text(
        "def login(request):\n"
        "    token = request.COOKIES.get('session_token')\n"
        "    return token\n\n"
        "def me(request):\n"
        "    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "config" / "router.py").write_text(
        "from django.urls import include, path\n\n"
        "urlpatterns = [\n"
        '    path("api/account/", include("account.handlers")),\n'
        "]\n",
        encoding="utf-8",
    )

    payload = build_codebase_map(source_root=source_root)

    assert any(item["path"] == "backend/account/handlers.py" for item in payload["auth_candidates"])
    assert any(item["path"] == "backend/config/router.py" for item in payload["urlconf_candidates"])
    assert any(item["path"] == "backend/account/handlers.py" for item in payload["candidate_edit_targets"])
    assert any(item["path"] == "backend/config/router.py" for item in payload["candidate_edit_targets"])


def test_build_patch_proposal_selects_nonstandard_python_targets_from_map(tmp_path: Path):
    source_root = tmp_path / "source"

    (source_root / "backend" / "account").mkdir(parents=True)
    (source_root / "backend" / "config").mkdir(parents=True)

    (source_root / "backend" / "account" / "handlers.py").write_text(
        "def login(request):\n"
        "    return request.COOKIES.get('session_token')\n\n"
        "def me(request):\n"
        "    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "config" / "router.py").write_text(
        "from django.urls import include, path\n\n"
        "urlpatterns = [\n"
        '    path("api/account/", include("account.handlers")),\n'
        "]\n",
        encoding="utf-8",
    )

    codebase_map = build_codebase_map(source_root=source_root)
    proposal = build_patch_proposal(
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
    )

    target_paths = {item["path"] for item in proposal["target_files"]}

    assert "backend/account/handlers.py" in target_paths
    assert "backend/config/router.py" in target_paths


def test_build_codebase_map_ignores_virtualenv_and_dependency_directories(tmp_path: Path):
    source_root = tmp_path / "source"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / ".venv" / "lib").mkdir(parents=True)
    (source_root / "frontend" / "node_modules" / "pkg").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / ".venv" / "lib" / "activate_this.py").write_text(
        "def login(request):\n    return 'bad'\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "node_modules" / "pkg" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    payload = build_codebase_map(source_root=source_root)

    target_paths = {item["path"] for item in payload["candidate_edit_targets"]}
    assert "backend/users/views.py" in target_paths
    assert "backend/.venv/lib/activate_this.py" not in target_paths
    assert "frontend/node_modules/pkg/App.js" not in target_paths


def test_build_codebase_map_emits_strategy_and_integration_targets(tmp_path: Path):
    source_root = tmp_path / "source"

    (source_root / "backend" / "shop").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "shop" / "views.py").write_text(
        "def login(request):\n"
        "    return request.COOKIES.get('session_token')\n\n"
        "def me(request):\n"
        "    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "shop" / "urls.py").write_text(
        "from django.urls import path\n\n"
        "urlpatterns = [\n"
        '    path("api/login", login),\n'
        '    path("api/orders/", me),\n'
        "]\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() {\n"
        "  return <main>Storefront Chatbot Shell</main>;\n"
        "}\n",
        encoding="utf-8",
    )

    payload = build_codebase_map(source_root=source_root)

    assert payload["backend_strategy"] == "django"
    assert payload["frontend_strategy"] == "react"
    assert any(item["path"] == "backend/shop/urls.py" for item in payload["backend_route_targets"])
    assert any(item["path"] == "frontend/src/App.js" for item in payload["frontend_mount_targets"])
    assert any(item["path"] == "backend/shop/views.py" for item in payload["tool_registry_targets"])
    assert any(item["path"] == "backend/shop/urls.py" for item in payload["order_bridge_targets"])


def test_build_codebase_map_emits_order_bridge_targets(tmp_path: Path):
    source_root = tmp_path / "source-order-bridge"

    (source_root / "backend" / "shop").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "shop" / "views.py").write_text(
        "def list_orders(request):\n"
        "    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "shop" / "urls.py").write_text(
        "from django.urls import path\n\n"
        "urlpatterns = [\n"
        '    path("api/orders/", list_orders),\n'
        "]\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() {\n"
        "  return <main>Storefront Chatbot Shell</main>;\n"
        "}\n",
        encoding="utf-8",
    )

    payload = build_codebase_map(source_root=source_root)

    assert any(item["path"] == "backend/shop/urls.py" for item in payload["order_bridge_targets"])


def test_codebase_mapper_extracts_bilyeo_route_and_mount_contract(tmp_path: Path):
    source_root = tmp_path / "bilyeo"

    (source_root / "backend" / "routes").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "app.py").write_text(
        """
from flask import Flask
from routes.auth import auth_bp

app = Flask(__name__)
app.register_blueprint(auth_bp, url_prefix="/api/auth")
""",
        encoding="utf-8",
    )
    (source_root / "backend" / "routes" / "auth.py").write_text(
        """
from flask import Blueprint, session

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["POST"])
def login():
    session["user_id"] = 1
    return {"ok": True}
""",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.vue").write_text(
        """
<template>
  <router-view />
</template>
""",
        encoding="utf-8",
    )

    payload = build_codebase_map(source_root=source_root)
    contract = payload["integration_contract"]

    assert contract["site"] == "bilyeo"
    assert contract["backend"]["framework"] == "flask"
    assert contract["backend"]["route_registration_points"] == ["backend/app.py"]
    assert contract["frontend"]["framework"] == "vue"
    assert contract["frontend"]["app_shell_path"] == "frontend/src/App.vue"
    assert contract["frontend"]["widget_mount_points"] == ["frontend/src/App.vue"]
    assert any(item["path"] == "backend/routes/auth.py" for item in payload["auth_session_resolver_candidates"])
    assert any(item["path"] == "frontend/src/App.vue" for item in payload["frontend_app_shell_candidates"])


def test_build_codebase_map_respects_onboardingignore_patterns(tmp_path: Path):
    source_root = tmp_path / "source"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "secret").mkdir(parents=True)
    (source_root / ".onboardingignore").write_text(
        "backend/secret\n",
        encoding="utf-8",
    )

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "secret" / "views.py").write_text(
        "def login(request):\n    return 'secret'\n",
        encoding="utf-8",
    )

    payload = build_codebase_map(source_root=source_root)

    target_paths = {item["path"] for item in payload["candidate_edit_targets"]}
    assert "backend/users/views.py" in target_paths
    assert "backend/secret/views.py" not in target_paths


def test_build_codebase_map_includes_frontend_api_clients_in_candidate_edit_targets(tmp_path: Path):
    source_root = tmp_path / "source"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "frontend" / "src" / "api").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True, exist_ok=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() {\n"
        "  return <main>Food storefront</main>;\n"
        "}\n",
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "api" / "api.js").write_text(
        "export async function fetchProducts() {\n"
        "  const response = await fetch('/api/products/');\n"
        "  return response.json();\n"
        "}\n",
        encoding="utf-8",
    )

    payload = build_codebase_map(source_root=source_root)

    target_paths = {item["path"] for item in payload["candidate_edit_targets"]}
    assert "frontend/src/api/api.js" in target_paths
    assert any(item["path"] == "frontend/src/api/api.js" for item in payload["api_client_candidates"])


def test_write_llm_codebase_interpretation_prefers_llm_ranked_candidates(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "llm-codebase-interpretation.json"

    (source_root / "backend" / "account").mkdir(parents=True)
    (source_root / "backend" / "config").mkdir(parents=True)
    (source_root / "backend" / "account" / "handlers.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/account/handlers.py", "reason": "auth handler"},
            {"path": "backend/config/router.py", "reason": "urlconf"},
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
                            "structure_summary": "django session auth with router entrypoint",
                            "framework_assessment": {"backend": "django", "frontend": "unknown"},
                            "ranked_candidates": [
                                {
                                    "path": "backend/account/handlers.py",
                                    "reason": "primary auth entrypoint",
                                }
                            ],
                        }
                    )
                },
            )()

    path = write_llm_codebase_interpretation(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        output_path=output_path,
        llm_factory=lambda: FakeLLM(),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["source"] == "llm"
    assert payload["ranked_candidates"][0]["path"] == "backend/account/handlers.py"
    assert payload["fallback_reason"] is None


def test_write_llm_codebase_interpretation_recovery_normalizes_string_framework_assessment(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "llm-codebase-interpretation.json"

    (source_root / "backend" / "account").mkdir(parents=True)
    (source_root / "backend" / "account" / "handlers.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/account/handlers.py", "reason": "auth handler"},
        ]
    }

    class FlexibleFrameworkLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "structure_summary": "django session auth",
                            "framework_assessment": "Backend framework: Django. Frontend framework: React.",
                            "ranked_candidates": [
                                {
                                    "path": "backend/account/handlers.py",
                                    "reason": "primary auth entrypoint",
                                }
                            ],
                        }
                    )
                },
            )()

    path = write_llm_codebase_interpretation(
        source_root=source_root,
        analysis={"framework": {"backend": "django", "frontend": "react"}},
        codebase_map=codebase_map,
        output_path=output_path,
        llm_factory=lambda: FlexibleFrameworkLLM(),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    debug_payload = json.loads((tmp_path / "reports" / "llm-debug" / "codebase-interpretation.json").read_text(encoding="utf-8"))
    recovery_events = json.loads((tmp_path / "reports" / "recovery-events.json").read_text(encoding="utf-8"))

    assert payload["source"] == "recovered_llm"
    assert payload["recovery_applied"] is True
    assert payload["recovery_reason"] == "framework_assessment_string_to_dict"
    assert payload["hard_fallback_reason"] is None
    assert payload["framework_assessment"] == {
        "summary": "Backend framework: Django. Frontend framework: React."
    }
    assert debug_payload["status"] == "recovered_llm"
    assert debug_payload["recovery_reason"] == "framework_assessment_string_to_dict"
    assert recovery_events == [
        {
            "component": "llm_codebase_interpretation",
            "source": "recovered_llm",
            "recovery_reason": "framework_assessment_string_to_dict",
            "hard_fallback_reason": None,
        }
    ]


def test_write_llm_codebase_interpretation_recovery_normalizes_object_structure_summary(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "llm-codebase-interpretation.json"

    (source_root / "backend" / "account").mkdir(parents=True)
    (source_root / "backend" / "account" / "handlers.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/account/handlers.py", "reason": "auth handler"},
        ]
    }

    class ObjectStructureSummaryLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "structure_summary": {
                                "backend": {"framework": "django"},
                                "frontend": {"framework": "react"},
                            },
                            "framework_assessment": {
                                "backend": "django",
                                "frontend": "react",
                            },
                            "ranked_candidates": [
                                {
                                    "path": "backend/account/handlers.py",
                                    "reason": "primary auth entrypoint",
                                }
                            ],
                        }
                    )
                },
            )()

    path = write_llm_codebase_interpretation(
        source_root=source_root,
        analysis={"framework": {"backend": "django", "frontend": "react"}},
        codebase_map=codebase_map,
        output_path=output_path,
        llm_factory=lambda: ObjectStructureSummaryLLM(),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    debug_payload = json.loads((tmp_path / "reports" / "llm-debug" / "codebase-interpretation.json").read_text(encoding="utf-8"))
    recovery_events = json.loads((tmp_path / "reports" / "recovery-events.json").read_text(encoding="utf-8"))

    assert payload["source"] == "recovered_llm"
    assert payload["recovery_applied"] is True
    assert payload["recovery_reason"] == "structure_summary_object_to_string"
    assert payload["hard_fallback_reason"] is None
    assert '"backend"' in payload["structure_summary"]
    assert debug_payload["status"] == "recovered_llm"
    assert debug_payload["recovery_reason"] == "structure_summary_object_to_string"
    assert recovery_events == [
        {
            "component": "llm_codebase_interpretation",
            "source": "recovered_llm",
            "recovery_reason": "structure_summary_object_to_string",
            "hard_fallback_reason": None,
        }
    ]


def test_write_llm_codebase_interpretation_recovery_uses_hard_fallback_on_invalid_candidate(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "llm-codebase-interpretation.json"
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/account/handlers.py", "reason": "auth handler"},
        ]
    }

    class InvalidLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "structure_summary": "wrong",
                            "framework_assessment": {"backend": "django", "frontend": "unknown"},
                            "ranked_candidates": [
                                {
                                    "path": "backend/admin/views.py",
                                    "reason": "invalid candidate",
                                }
                            ],
                        }
                    )
                },
            )()

    path = write_llm_codebase_interpretation(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        output_path=output_path,
        llm_factory=lambda: InvalidLLM(),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    debug_payload = json.loads((tmp_path / "reports" / "llm-debug" / "codebase-interpretation.json").read_text(encoding="utf-8"))
    recovery_events = json.loads((tmp_path / "reports" / "recovery-events.json").read_text(encoding="utf-8"))

    assert payload["source"] == "hard_fallback"
    assert payload["recovery_applied"] is False
    assert payload["recovery_reason"] is None
    assert payload["hard_fallback_reason"] == "invalid_ranked_candidates"
    assert payload["ranked_candidates"][0]["path"] == "backend/account/handlers.py"
    assert debug_payload["status"] == "hard_fallback"
    assert debug_payload["hard_fallback_reason"] == "invalid_ranked_candidates"
    assert recovery_events == [
        {
            "component": "llm_codebase_interpretation",
            "source": "hard_fallback",
            "recovery_reason": None,
            "hard_fallback_reason": "invalid_ranked_candidates",
        }
    ]


def test_write_llm_codebase_interpretation_recovery_normalizes_ranked_candidate_paths(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "llm-codebase-interpretation.json"
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/users/views.py", "reason": "auth handler"},
            {"path": "backend/users/urls.py", "reason": "user urlconf"},
        ]
    }

    class PathOnlyRankedCandidatesLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "structure_summary": "django session auth",
                            "framework_assessment": {
                                "backend": "django",
                                "frontend": "react",
                            },
                            "ranked_candidates": [
                                "backend/users/views.py",
                                "backend/users/urls.py",
                            ],
                        }
                    )
                },
            )()

    path = write_llm_codebase_interpretation(
        source_root=source_root,
        analysis={"framework": {"backend": "django", "frontend": "react"}},
        codebase_map=codebase_map,
        output_path=output_path,
        llm_factory=lambda: PathOnlyRankedCandidatesLLM(),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    debug_payload = json.loads((tmp_path / "reports" / "llm-debug" / "codebase-interpretation.json").read_text(encoding="utf-8"))
    recovery_events = json.loads((tmp_path / "reports" / "recovery-events.json").read_text(encoding="utf-8"))

    assert payload["source"] == "recovered_llm"
    assert payload["recovery_reason"] == "ranked_candidate_paths_to_objects"
    assert payload["ranked_candidates"] == [
        {"path": "backend/users/views.py", "reason": "auth handler"},
        {"path": "backend/users/urls.py", "reason": "user urlconf"},
    ]
    assert debug_payload["status"] == "recovered_llm"
    assert debug_payload["recovery_reason"] == "ranked_candidate_paths_to_objects"
    assert recovery_events == [
        {
            "component": "llm_codebase_interpretation",
            "source": "recovered_llm",
            "recovery_reason": "ranked_candidate_paths_to_objects",
            "hard_fallback_reason": None,
        }
    ]


def test_write_llm_codebase_interpretation_writes_debug_artifact_and_generation_log_on_invalid_payload(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "llm-codebase-interpretation.json"
    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/account/handlers.py", "reason": "auth handler"},
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
                            "claim": "wrong shape",
                            "evidence": ["not the expected payload"],
                        }
                    )
                },
            )()

    path = write_llm_codebase_interpretation(
        source_root=source_root,
        analysis={"framework": {"backend": "django", "frontend": "react"}},
        codebase_map=codebase_map,
        output_path=output_path,
        llm_factory=lambda: InvalidPayloadLLM(),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    debug_payload = json.loads((tmp_path / "reports" / "llm-debug" / "codebase-interpretation.json").read_text(encoding="utf-8"))
    generation_log = (tmp_path / "reports" / "generation.log").read_text(encoding="utf-8")

    assert payload["source"] == "hard_fallback"
    assert payload["hard_fallback_reason"] == "invalid_llm_payload"
    assert debug_payload["status"] == "hard_fallback"
    assert debug_payload["hard_fallback_reason"] == "invalid_llm_payload"
    assert "wrong shape" in debug_payload["raw_response"]
    assert "hard_fallback_used" in generation_log
    assert "hard_fallback_reason=invalid_llm_payload" in generation_log

    trace_lines = [
        json.loads(line)
        for line in (tmp_path / "reports" / "execution-trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = {(item["component"], item["event"]) for item in trace_lines}

    assert ("codebase_mapper", "llm_call_started") in events
    assert ("codebase_mapper", "hard_fallback_used") in events
    assert ("codebase_mapper", "artifact_written") in events


def test_write_llm_codebase_interpretation_emits_acceptance_event_for_recovered_payload(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "reports" / "llm-codebase-interpretation.json"

    (source_root / "backend" / "account").mkdir(parents=True)
    (source_root / "backend" / "account" / "handlers.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    codebase_map = {
        "candidate_edit_targets": [
            {"path": "backend/account/handlers.py", "reason": "auth handler"},
        ]
    }

    class FlexibleFrameworkLLM:
        def invoke(self, messages):
            return type(
                "LLMResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "structure_summary": "django session auth",
                            "framework_assessment": "Backend framework: Django. Frontend framework: React.",
                            "ranked_candidates": [
                                {
                                    "path": "backend/account/handlers.py",
                                    "reason": "primary auth entrypoint",
                                }
                            ],
                        }
                    )
                },
            )()

    write_llm_codebase_interpretation(
        source_root=source_root,
        analysis={"framework": {"backend": "django", "frontend": "react"}},
        codebase_map=codebase_map,
        output_path=output_path,
        llm_factory=lambda: FlexibleFrameworkLLM(),
    )

    trace_lines = [
        json.loads(line)
        for line in (tmp_path / "reports" / "execution-trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    accepted = [
        item
        for item in trace_lines
        if item["component"] == "codebase_mapper" and item["event"] == "llm_output_accepted"
    ]
    assert accepted
    assert accepted[-1]["source"] == "recovered_llm"
    assert accepted[-1]["recovery"] == {
        "applied": True,
        "reason": "framework_assessment_string_to_dict",
    }


def test_codebase_interpretation_prompt_requires_structured_framework_assessment_object():
    from chatbot.src.onboarding.codebase_mapper import _llm_codebase_interpretation_system_prompt

    prompt = _llm_codebase_interpretation_system_prompt()

    assert "framework_assessment must be a JSON object" in prompt
    assert "backend" in prompt
    assert "frontend" in prompt
    assert "summary" in prompt
    assert "Do not return framework_assessment as a plain string" in prompt
    assert "ranked_candidates must be an array of objects with path and reason" in prompt
    assert "Do not return ranked_candidates as strings" in prompt


def test_build_patch_proposal_prefers_llm_ranked_candidates_when_present(tmp_path: Path):
    source_root = tmp_path / "source"

    (source_root / "backend" / "account").mkdir(parents=True)
    (source_root / "backend" / "config").mkdir(parents=True)

    (source_root / "backend" / "account" / "handlers.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "config" / "router.py").write_text(
        "urlpatterns = []\n",
        encoding="utf-8",
    )

    codebase_map = build_codebase_map(source_root=source_root)
    proposal = build_patch_proposal(
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map=codebase_map,
        recommended_outputs=["chat_auth"],
        llm_codebase_interpretation={
            "ranked_candidates": [
                {"path": "backend/config/router.py", "reason": "project-level preferred route entrypoint"},
            ]
        },
    )

    assert proposal["target_files"][0]["path"] == "backend/config/router.py"
