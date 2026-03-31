import json
import os
import io
import subprocess
import sys
from types import ModuleType
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ["PYTHONPATH"] = (
    str(ROOT)
    if not os.environ.get("PYTHONPATH")
    else f"{str(ROOT)}:{os.environ['PYTHONPATH']}"
)

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

fake_langchain_ollama = ModuleType("langchain_ollama")


class _FakeChatOllama:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


fake_langchain_ollama.ChatOllama = _FakeChatOllama
sys.modules.setdefault("langchain_ollama", fake_langchain_ollama)

from chatbot.src.onboarding.approval_store import ApprovalStore
from chatbot.scripts.run_onboarding_generation import build_parser
from chatbot.scripts.run_onboarding_generation import build_slack_bridge_from_env
from chatbot.scripts.run_onboarding_generation import load_generation_env
from chatbot.scripts.run_onboarding_generation import main as run_onboarding_generation_main
from chatbot.scripts.run_slack_socket_gateway import (
    _build_resume_runner,
    build_parser as build_gateway_parser,
    load_gateway_env,
    run_gateway,
)
from chatbot.src.onboarding.slack_bridge import SlackWebBridge


@pytest.fixture(autouse=True)
def _stub_cli_dependencies(monkeypatch):
    monkeypatch.setattr(
        "chatbot.src.onboarding.orchestrator.run_smoke_tests",
        lambda **_: [
            {
                "step": "login",
                "step_id": "login",
                "required": True,
                "category": "auth",
                "timed_out": False,
                "returncode": 0,
                "stdout": '{"ok": true}',
                "stderr": "",
                "request": {"method": "POST", "url": "http://127.0.0.1:8000/api/users/login/", "headers": {}},
                "response": {"status": 200, "headers": {"Set-Cookie": "sessionid=abc"}, "body": '{"ok": true}'},
                "exports": {"login.cookies": "sessionid=abc"},
            },
            {
                "step": "session-me",
                "step_id": "session-me",
                "required": True,
                "category": "auth",
                "timed_out": False,
                "returncode": 0,
                "stdout": '{"user": {"id": 7}}',
                "stderr": "",
                "request": {"method": "GET", "url": "http://127.0.0.1:8000/api/users/me/", "headers": {"Cookie": "sessionid=abc"}},
                "response": {"status": 200, "headers": {}, "body": '{"user": {"id": 7}}'},
                "exports": {"login.user_id": "7"},
            },
            {
                "step": "product-api",
                "step_id": "product-api",
                "required": True,
                "category": "catalog",
                "timed_out": False,
                "returncode": 0,
                "stdout": '{"items": [{"id": 1}]}',
                "stderr": "",
                "request": {"method": "GET", "url": "http://127.0.0.1:8000/api/products/", "headers": {"Cookie": "sessionid=abc"}},
                "response": {"status": 200, "headers": {}, "body": '{"items": [{"id": 1}]}'},
                "exports": {"product.first_item": "{'id': 1}"},
            },
            {
                "step": "order-api",
                "step_id": "order-api",
                "required": True,
                "category": "orders",
                "timed_out": False,
                "returncode": 0,
                "stdout": '{"orders": [{"id": 7}]}',
                "stderr": "",
                "request": {"method": "GET", "url": "http://127.0.0.1:8000/api/orders/", "headers": {"Cookie": "sessionid=abc"}},
                "response": {"status": 200, "headers": {}, "body": '{"orders": [{"id": 7}]}'},
                "exports": {"order.first_order": "{'id': 7}"},
            },
        ],
    )
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.build_onboarding_event_store", lambda redis_url: None)
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.close_onboarding_event_store", lambda store: None)

    original_run = subprocess.run

    def _inline_run(cmd, *args, **kwargs):
        if (
            isinstance(cmd, list)
            and len(cmd) >= 2
            and cmd[0] == sys.executable
            and cmd[1] == "chatbot/scripts/run_onboarding_generation.py"
        ):
            captured_stdout = io.StringIO()
            captured_stderr = io.StringIO()
            old_argv = sys.argv[:]
            old_cwd = os.getcwd()
            cwd = kwargs.get("cwd")
            try:
                if cwd is not None:
                    os.chdir(cwd)
                sys.argv = [cmd[1], *cmd[2:]]
                with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
                    try:
                        exit_code = run_onboarding_generation_main()
                    except SystemExit as exc:
                        exit_code = int(exc.code or 0) if isinstance(exc.code, int) else 1
            finally:
                sys.argv = old_argv
                os.chdir(old_cwd)
            return subprocess.CompletedProcess(cmd, exit_code, captured_stdout.getvalue(), captured_stderr.getvalue())
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _inline_run)


def test_cli_runner_executes_onboarding_flow(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            str(source_root),
            "--generated-root",
            str(generated_root),
            "--runtime-root",
            str(runtime_root),
            "--run-id",
            "food-run-001",
            "--agent-version",
            "test-v1",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["run_root"].endswith("generated/food/food-run-001")
    assert payload["runtime_workspace"].endswith("runtime/food/food-run-001/workspace")
    assert payload["edit_plan_path"].endswith("reports/edit-plan.json")
    assert payload["edit_execution_path"].endswith("reports/edit-execution.json")


def test_cli_runner_accepts_explicit_approval_inputs(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            str(source_root),
            "--generated-root",
            str(generated_root),
            "--runtime-root",
            str(runtime_root),
            "--run-id",
            "food-run-002",
            "--agent-version",
            "test-v1",
            "--approval",
            "analysis=approve",
            "--approval",
            "apply=approve",
            "--approval",
            "export=approve",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["current_state"] not in {
        "awaiting_analysis_approval",
        "awaiting_apply_approval",
        "awaiting_export_approval",
    }
    assert payload["pending_approval"] is None


def test_cli_runner_can_emit_report_paths(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            str(source_root),
            "--generated-root",
            str(generated_root),
            "--runtime-root",
            str(runtime_root),
            "--run-id",
            "food-run-004",
            "--agent-version",
            "test-v1",
            "--approval",
            "analysis=approve",
            "--approval",
            "apply=approve",
            "--approval",
            "export=approve",
            "--print-report-paths",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["smoke_summary_path"].endswith("reports/smoke-summary.json")
    assert payload["diagnostic_report_path"].endswith("reports/diagnostic-report.json")
    assert payload["export_metadata_path"].endswith("reports/export-metadata.json")


def test_cli_runner_emits_edit_plan_and_execution_paths(monkeypatch, capsys):
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.load_generation_env", lambda: None)
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.build_onboarding_event_store", lambda redis_url: None)
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.close_onboarding_event_store", lambda store: None)
    monkeypatch.setattr(
        "chatbot.scripts.run_onboarding_generation.run_onboarding_generation",
        lambda **kwargs: {
            "run_root": "/tmp/generated/food/food-run-edit-paths",
            "runtime_workspace": "/tmp/runtime/food/food-run-edit-paths/workspace",
            "current_state": "completed",
            "edit_plan_path": "/tmp/generated/food/food-run-edit-paths/reports/edit-plan.json",
            "edit_execution_path": "/tmp/generated/food/food-run-edit-paths/reports/edit-execution.json",
            "export_metadata_path": "/tmp/generated/food/food-run-edit-paths/reports/export-metadata.json",
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            "/tmp/source",
            "--generated-root",
            "/tmp/generated",
            "--runtime-root",
            "/tmp/runtime",
            "--run-id",
            "food-run-edit-paths",
            "--agent-version",
            "test-v1",
        ],
    )

    exit_code = run_onboarding_generation_main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["edit_plan_path"].endswith("reports/edit-plan.json")
    assert payload["edit_execution_path"].endswith("reports/edit-execution.json")
    assert payload["export_metadata_path"].endswith("reports/export-metadata.json")
    assert not payload.get("proposed_patch_path")
    assert not payload.get("llm_proposed_patch_path")


def test_cli_runner_preserves_repaired_run_fields(monkeypatch, capsys):
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.load_generation_env", lambda: None)
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.build_onboarding_event_store", lambda redis_url: None)
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.close_onboarding_event_store", lambda store: None)
    monkeypatch.setattr(
        "chatbot.scripts.run_onboarding_generation.run_onboarding_generation",
        lambda **kwargs: {
            "run_root": "/tmp/generated/food/food-run-repair",
            "runtime_workspace": "/tmp/runtime/food/food-run-repair/workspace",
            "current_state": "completed",
            "export_metadata_path": "/tmp/generated/food/food-run-repair/reports/export-metadata.json",
            "recovery_artifact_path": "/tmp/generated/food/food-run-repair/reports/recovery-plan.json",
            "final_recovery_source": "missing_import_target",
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            "/tmp/source",
            "--generated-root",
            "/tmp/generated",
            "--runtime-root",
            "/tmp/runtime",
            "--run-id",
            "food-run-repair",
            "--agent-version",
            "test-v1",
        ],
    )

    exit_code = run_onboarding_generation_main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["current_state"] == "completed"
    assert payload["export_metadata_path"].endswith("reports/export-metadata.json")
    assert payload["recovery_artifact_path"].endswith("reports/recovery-plan.json")
    assert payload["final_recovery_source"] == "missing_import_target"


def test_cli_parser_accepts_llm_role_runner_flags():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--run-id",
            "food-run-003",
            "--use-llm-roles",
            "--llm-provider",
            "openai",
            "--llm-model",
            "gpt-4o-mini",
            "--print-report-paths",
        ]
    )

    assert args.use_llm_roles is True
    assert args.llm_provider == "openai"
    assert args.llm_model == "gpt-4o-mini"
    assert args.print_report_paths is True


def test_cli_parser_accepts_runtime_completion_loop_flag():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--run-id",
            "food-run-runtime-loop",
            "--enable-runtime-completion-loop",
        ]
    )

    assert args.enable_runtime_completion_loop is True


def test_cli_parser_defaults_engine_to_legacy():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--run-id",
            "food-run-engine-default",
        ]
    )

    assert args.engine == "legacy"


def test_cli_parser_accepts_engine_v2():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--run-id",
            "food-run-engine-v2",
            "--engine",
            "v2",
        ]
    )

    assert args.engine == "v2"


def test_cli_parser_accepts_chatbot_server_base_url():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--run-id",
            "food-run-engine-v2",
            "--engine",
            "v2",
            "--chatbot-server-base-url",
            "http://localhost:8100",
        ]
    )

    assert args.chatbot_server_base_url == "http://localhost:8100"


def test_cli_parser_accepts_llm_patch_draft_flag():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--run-id",
            "food-run-llm-draft",
            "--generate-llm-patch-draft",
        ]
    )

    assert args.generate_llm_patch_draft is True


def test_cli_parser_accepts_explicit_smoke_credentials():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--run-id",
            "food-run-creds",
            "--smoke-email",
            "test1@example.com",
            "--smoke-password",
            "password123",
        ]
    )

    assert args.smoke_email == "test1@example.com"
    assert args.smoke_password == "password123"


def test_cli_runner_writes_explicit_smoke_credentials_to_manifest(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            str(source_root),
            "--generated-root",
            str(generated_root),
            "--runtime-root",
            str(runtime_root),
            "--run-id",
            "food-run-credentials",
            "--agent-version",
            "test-v1",
            "--smoke-email",
            "test1@example.com",
            "--smoke-password",
            "password123",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (generated_root / "food" / "food-run-credentials" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["credentials"] == {
        "email": "test1@example.com",
        "password": "password123",
    }


def test_cli_runner_emits_llm_role_execution_path(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            str(source_root),
            "--generated-root",
            str(generated_root),
            "--runtime-root",
            str(runtime_root),
            "--run-id",
            "food-run-llm-exec",
            "--approval",
            "analysis=approve",
            "--approval",
            "apply=approve",
            "--approval",
            "export=approve",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["llm_role_execution_path"].endswith("reports/llm-role-execution.json")
    assert payload["llm_codebase_interpretation_path"].endswith("reports/llm-codebase-interpretation.json")
    assert payload["llm_patch_proposal_execution_path"].endswith("reports/llm-patch-proposal-execution.json")


def test_cli_runner_passes_runtime_completion_loop_flag_to_orchestrator(monkeypatch, capsys):
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.load_generation_env", lambda: None)
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.build_onboarding_event_store", lambda redis_url: None)
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.close_onboarding_event_store", lambda store: None)

    captured: dict[str, object] = {}

    def fake_run_onboarding_generation(**kwargs):
        captured.update(kwargs)
        return {
            "run_root": "/tmp/generated/food/food-run-runtime-loop",
            "runtime_workspace": "/tmp/runtime/food/food-run-runtime-loop/workspace",
            "current_state": "completed",
            "runtime_completion_path": "/tmp/generated/food/food-run-runtime-loop/reports/runtime-completion.json",
        }

    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.run_onboarding_generation", fake_run_onboarding_generation)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            "/tmp/source",
            "--generated-root",
            "/tmp/generated",
            "--runtime-root",
            "/tmp/runtime",
            "--run-id",
            "food-run-runtime-loop",
            "--enable-runtime-completion-loop",
        ],
    )

    exit_code = run_onboarding_generation_main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["enable_runtime_completion_loop"] is True
    assert payload["runtime_completion_path"].endswith("reports/runtime-completion.json")


def test_cli_parser_accepts_approval_store_and_resume_flags():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--resume-run-id",
            "food-run-010",
            "--approval-store-root",
            "generated/approvals",
        ]
    )

    assert args.resume_run_id == "food-run-010"
    assert args.approval_store_root == "generated/approvals"


def test_cli_runner_stops_at_pending_approval_when_store_is_enabled(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    approval_root = tmp_path / "approvals"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            str(source_root),
            "--generated-root",
            str(generated_root),
            "--runtime-root",
            str(runtime_root),
            "--run-id",
            "food-run-pending",
            "--agent-version",
            "test-v1",
            "--approval-store-root",
            str(approval_root),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["current_state"] == "awaiting_analysis_approval"
    assert payload["pending_approval"]["approval_type"] == "analysis"


def test_cli_runner_can_resume_run_after_approval_decision(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"
    runtime_root = tmp_path / "runtime"
    approval_root = tmp_path / "approvals"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    first = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            str(source_root),
            "--generated-root",
            str(generated_root),
            "--runtime-root",
            str(runtime_root),
            "--run-id",
            "food-run-resume",
            "--agent-version",
            "test-v1",
            "--approval-store-root",
            str(approval_root),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    store = ApprovalStore(root=approval_root)
    store.record_decision(
        run_id="food-run-resume",
        approval_type="analysis",
        decision="approve",
        actor="U123",
    )

    second = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            str(source_root),
            "--generated-root",
            str(generated_root),
            "--runtime-root",
            str(runtime_root),
            "--resume-run-id",
            "food-run-resume",
            "--agent-version",
            "test-v1",
            "--approval-store-root",
            str(approval_root),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert second.returncode == 0, second.stderr
    payload = json.loads(second.stdout)
    assert payload["current_state"] == "awaiting_apply_approval"
    assert payload["pending_approval"]["approval_type"] == "apply"


def test_gateway_cli_parser_accepts_socket_mode_flags():
    parser = build_gateway_parser()

    args = parser.parse_args(
        [
            "--channel",
            "#onboarding-runs",
            "--approval-store-root",
            "generated/approvals",
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
        ]
    )

    assert args.channel == "#onboarding-runs"
    assert args.approval_store_root == "generated/approvals"
    assert args.site == "food"


def test_gateway_cli_parser_accepts_llm_resume_flags():
    parser = build_gateway_parser()

    args = parser.parse_args(
        [
            "--channel",
            "#onboarding-runs",
            "--approval-store-root",
            "generated/approvals",
            "--site",
            "food",
            "--source-root",
            "food",
            "--generated-root",
            "generated",
            "--runtime-root",
            "runtime",
            "--use-llm-roles",
            "--generate-llm-patch-draft",
            "--llm-provider",
            "openai",
            "--llm-model",
            "gpt-5-mini",
        ]
    )

    assert args.use_llm_roles is True
    assert args.generate_llm_patch_draft is True
    assert args.llm_provider == "openai"
    assert args.llm_model == "gpt-5-mini"
    assert args.source_root == "food"


def test_cli_can_build_slack_web_bridge_from_env(monkeypatch):
    class FakeWebClient:
        def __init__(self, token: str):
            self.token = token

        def chat_postMessage(self, **kwargs):
            captured["post"] = kwargs
            return {"ok": True, "ts": "1710000000.100"}

    captured: dict[str, object] = {}
    monkeypatch.setenv("SLACK_COORDINATOR_BOT_TOKEN", "xoxb-coordinator")
    monkeypatch.setenv("SLACK_ANALYZER_BOT_TOKEN", "xoxb-analyzer")
    monkeypatch.setenv("SLACK_GENERATOR_BOT_TOKEN", "xoxb-generator")

    bridge = build_slack_bridge_from_env(
        channel="#onboarding-runs",
        web_client_factory=lambda token: FakeWebClient(token),
    )

    assert isinstance(bridge, SlackWebBridge)
    assert bridge.channel == "#onboarding-runs"
    assert bridge.web_client.token == "xoxb-coordinator"
    assert bridge.role_web_clients["Analyzer"].token == "xoxb-analyzer"
    assert bridge.role_web_clients["Generator"].token == "xoxb-generator"


def test_cli_can_fallback_to_legacy_slack_bot_token(monkeypatch):
    class FakeWebClient:
        def __init__(self, token: str):
            self.token = token

        def chat_postMessage(self, **kwargs):
            return {"ok": True, "ts": "1710000000.100"}

    monkeypatch.delenv("SLACK_COORDINATOR_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-legacy")

    bridge = build_slack_bridge_from_env(
        channel="#onboarding-runs",
        web_client_factory=lambda token: FakeWebClient(token),
    )

    assert isinstance(bridge, SlackWebBridge)
    assert bridge.web_client.token == "xoxb-legacy"


def test_run_gateway_registers_socket_handler(tmp_path: Path):
    captured: dict[str, object] = {}
    listeners: list = []

    class FakeWebClient:
        def __init__(self, token: str):
            captured["bot_token"] = token

    class FakeSocketClient:
        def __init__(self, *, app_token: str, web_client):
            captured["app_token"] = app_token
            captured["web_client"] = web_client
            self.socket_mode_request_listeners = listeners

        def connect(self):
            captured["connected"] = True

        def disconnect(self):
            captured["disconnected"] = True

    exit_code = run_gateway(
        channel="#onboarding-runs",
        approval_store_root=tmp_path,
        bot_token="xoxb-test",
        app_token="xapp-test",
        socket_client_factory=lambda **kwargs: FakeSocketClient(**kwargs),
        web_client_factory=lambda token: FakeWebClient(token),
        connect=False,
        run_forever=False,
    )

    assert exit_code == 0
    assert captured["bot_token"] == "xoxb-test"
    assert captured["app_token"] == "xapp-test"
    assert len(listeners) == 1


def test_run_gateway_connects_and_enters_loop_once(tmp_path: Path):
    captured: dict[str, object] = {"sleep_calls": 0}

    class FakeWebClient:
        def __init__(self, token: str):
            self.token = token

    class FakeSocketClient:
        def __init__(self, *, app_token: str, web_client):
            self.socket_mode_request_listeners = []
            captured["app_token"] = app_token

        def connect(self):
            captured["connected"] = True

    def fake_sleep(_seconds: float):
        captured["sleep_calls"] = int(captured["sleep_calls"]) + 1
        raise KeyboardInterrupt

    exit_code = run_gateway(
        channel="#onboarding-runs",
        approval_store_root=tmp_path,
        bot_token="xoxb-test",
        app_token="xapp-test",
        socket_client_factory=lambda **kwargs: FakeSocketClient(**kwargs),
        web_client_factory=lambda token: FakeWebClient(token),
        connect=True,
        run_forever=True,
        sleep_fn=fake_sleep,
    )

    assert exit_code == 0
    assert captured["connected"] is True
    assert captured["sleep_calls"] == 1


def test_run_gateway_logs_connection_lifecycle(tmp_path: Path):
    class FakeLogger:
        def __init__(self):
            self.messages: list[str] = []

        def info(self, message: str, *args):
            self.messages.append(message % args if args else message)

    class FakeWebClient:
        def __init__(self, token: str):
            self.token = token

    class FakeSocketClient:
        def __init__(self, *, app_token: str, web_client):
            self.socket_mode_request_listeners = []

    logger = FakeLogger()

    exit_code = run_gateway(
        channel="#onboarding-runs",
        approval_store_root=tmp_path,
        bot_token="xoxb-test",
        app_token="xapp-test",
        socket_client_factory=lambda **kwargs: FakeSocketClient(**kwargs),
        web_client_factory=lambda token: FakeWebClient(token),
        connect=False,
        run_forever=False,
        logger=logger,
    )

    assert exit_code == 0
    assert "gateway started" in logger.messages[0]


def test_run_gateway_approve_action_can_trigger_resume(tmp_path: Path):
    captured: dict[str, object] = {}
    listeners: list = []

    class FakeWebClient:
        def __init__(self, token: str):
            self.token = token

        def chat_postMessage(self, **kwargs):
            captured["post"] = kwargs
            return {"ok": True, "ts": "1710000000.100"}

    class FakeSocketClient:
        def __init__(self, *, app_token: str, web_client):
            self.socket_mode_request_listeners = listeners

    class FakeLogger:
        def __init__(self):
            self.messages: list[str] = []

        def info(self, message: str, *args):
            self.messages.append(message % args if args else message)

        def exception(self, message: str, *args):
            self.messages.append(message % args if args else message)

    def resume_run(run_id: str, approval_type: str):
        captured["resume"] = (run_id, approval_type)

    logger = FakeLogger()
    exit_code = run_gateway(
        channel="#onboarding-runs",
        approval_store_root=tmp_path,
        bot_token="xoxb-test",
        app_token="xapp-test",
        socket_client_factory=lambda **kwargs: FakeSocketClient(**kwargs),
        web_client_factory=lambda token: FakeWebClient(token),
        connect=False,
        run_forever=False,
        logger=logger,
        resume_run=resume_run,
    )

    assert exit_code == 0
    request = {
        "envelope_id": "env-123",
        "payload": {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "value": json.dumps(
                        {
                            "run_id": "food-run-001",
                            "approval_type": "analysis",
                            "decision": "approve",
                        }
                    ),
                }
            ],
        },
    }

    listeners[0](None, request)

    assert captured["resume"] == ("food-run-001", "analysis")


def test_build_resume_runner_preserves_llm_flags(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    class FakeLogger:
        def info(self, message: str, *args):
            captured["info"] = message % args if args else message

        def exception(self, message: str, *args):
            captured["exception"] = message % args if args else message

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        "chatbot.scripts.run_slack_socket_gateway.subprocess.run",
        fake_run,
    )

    resume = _build_resume_runner(
        channel="C123",
        approval_store_root=tmp_path,
        site="food",
        source_root="food",
        generated_root="generated",
        runtime_root="runtime",
        agent_version="dev",
        use_llm_roles=True,
        generate_llm_patch_draft=True,
        llm_provider="openai",
        llm_model="gpt-5-mini",
        logger=FakeLogger(),
    )

    assert resume is not None
    resume("food-run-308", "analysis")

    cmd = captured["cmd"]
    assert "--use-llm-roles" in cmd
    assert "--generate-llm-patch-draft" in cmd
    assert "--llm-provider" in cmd
    assert "--llm-model" in cmd
    assert "gpt-5-mini" in cmd


def test_load_gateway_env_reads_root_dotenv(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    script_root = root / "chatbot" / "scripts"
    script_root.mkdir(parents=True)
    (root / ".env").write_text(
        "SLACK_BOT_TOKEN=xoxb-from-dotenv\nSLACK_APP_TOKEN=xapp-from-dotenv\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)

    load_gateway_env(project_root=root)

    import os

    assert os.getenv("SLACK_BOT_TOKEN") == "xoxb-from-dotenv"
    assert os.getenv("SLACK_APP_TOKEN") == "xapp-from-dotenv"


def test_load_generation_env_reads_root_dotenv(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / ".env").write_text(
        "SLACK_COORDINATOR_BOT_TOKEN=xoxb-coordinator\nSLACK_ANALYZER_BOT_TOKEN=xoxb-analyzer\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("SLACK_COORDINATOR_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_ANALYZER_BOT_TOKEN", raising=False)

    load_generation_env(project_root=root)

    import os

    assert os.getenv("SLACK_COORDINATOR_BOT_TOKEN") == "xoxb-coordinator"
    assert os.getenv("SLACK_ANALYZER_BOT_TOKEN") == "xoxb-analyzer"


def test_cli_runner_dispatches_v2_engine(monkeypatch, capsys):
    monkeypatch.setattr("chatbot.scripts.run_onboarding_generation.load_generation_env", lambda: None)
    monkeypatch.setattr(
        "chatbot.scripts.run_onboarding_generation.run_onboarding_generation",
        lambda **kwargs: pytest.fail("legacy engine should not run when --engine v2 is used"),
    )
    captured_kwargs = {}

    def _fake_v2_runner(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "engine": "v2",
            "run_root": "/tmp/generated/food/food-run-v2",
            "status": "exported",
            "latest_analysis_artifact": "/tmp/generated/food/food-run-v2/artifacts/01-analysis/snapshot/v0001.json",
            "latest_plan_artifact": "/tmp/generated/food/food-run-v2/artifacts/02-planning/integration-plan/v0001.json",
            "latest_compile_artifact": "/tmp/generated/food/food-run-v2/artifacts/03-compile/host-edit-program/v0001.json",
            "latest_validation_artifact": "/tmp/generated/food/food-run-v2/artifacts/05-validation/validation-bundle/v0001.json",
            "latest_export_artifact": "/tmp/generated/food/food-run-v2/artifacts/06-export/export-bundle/v0001.json",
        }

    monkeypatch.setattr(
        "chatbot.scripts.run_onboarding_generation.run_onboarding_generation_v2",
        _fake_v2_runner,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_onboarding_generation.py",
            "--site",
            "food",
            "--source-root",
            "/tmp/source",
            "--generated-root",
            "/tmp/generated",
            "--runtime-root",
            "/tmp/runtime",
            "--run-id",
            "food-run-v2",
            "--engine",
            "v2",
            "--chatbot-server-base-url",
            "http://localhost:8100",
        ],
    )

    exit_code = run_onboarding_generation_main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["engine"] == "v2"
    assert payload["status"] == "exported"
    assert captured_kwargs["max_repair_attempts"] == 2
