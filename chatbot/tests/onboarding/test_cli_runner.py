import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.scripts.run_onboarding_generation import build_parser


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
