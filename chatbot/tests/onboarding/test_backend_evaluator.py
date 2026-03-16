import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.backend_evaluator import evaluate_backend_workspace


def test_evaluate_backend_workspace_writes_report(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "backend" / "users").mkdir(parents=True)
    (workspace / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    report_path = evaluate_backend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert report_path.name == "backend-evaluation.json"
    assert payload["passed"] is True
    assert payload["checked_files"] == ["backend/users/views.py"]
    assert payload["failed_files"] == []


def test_evaluate_backend_workspace_detects_fastapi_entrypoint(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "backend" / "app").mkdir(parents=True)
    (workspace / "backend" / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )

    report_path = evaluate_backend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["framework"] == "fastapi"
    assert payload["entrypoint_smoke"][0]["path"] == "backend/app/main.py"
    assert payload["entrypoint_smoke"][0]["ok"] is True


def test_evaluate_backend_workspace_detects_flask_entrypoint(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "backend").mkdir(parents=True)
    (workspace / "backend" / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )

    report_path = evaluate_backend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["framework"] == "flask"
    assert payload["entrypoint_smoke"][0]["path"] == "backend/app.py"
    assert payload["entrypoint_smoke"][0]["ok"] is True


def test_evaluate_backend_workspace_detects_django_urlconf(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "backend" / "foodshop").mkdir(parents=True)
    (workspace / "backend" / "foodshop" / "urls.py").write_text(
        "from django.urls import path\nurlpatterns = []\n",
        encoding="utf-8",
    )

    report_path = evaluate_backend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["framework"] == "django"
    assert payload["entrypoint_smoke"][0]["path"] == "backend/foodshop/urls.py"
    assert payload["entrypoint_smoke"][0]["ok"] is True
