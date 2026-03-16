import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.scripts.run_onboarding_generation import build_parser
from chatbot.scripts.run_onboarding_generation import build_slack_bridge_from_env
from chatbot.scripts.run_slack_socket_gateway import (
    build_parser as build_gateway_parser,
    load_gateway_env,
    run_gateway,
)
from chatbot.src.onboarding.slack_bridge import SlackWebBridge


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
    assert payload["current_state"] == "completed"


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


def test_gateway_cli_parser_accepts_socket_mode_flags():
    parser = build_gateway_parser()

    args = parser.parse_args(
        [
            "--channel",
            "#onboarding-runs",
            "--approval-store-root",
            "generated/approvals",
        ]
    )

    assert args.channel == "#onboarding-runs"
    assert args.approval_store_root == "generated/approvals"


def test_cli_can_build_slack_web_bridge_from_env(monkeypatch):
    class FakeWebClient:
        def __init__(self, token: str):
            self.token = token

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")

    bridge = build_slack_bridge_from_env(
        channel="#onboarding-runs",
        web_client_factory=lambda token: FakeWebClient(token),
    )

    assert isinstance(bridge, SlackWebBridge)
    assert bridge.channel == "#onboarding-runs"
    assert bridge.web_client.token == "xoxb-test"


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
