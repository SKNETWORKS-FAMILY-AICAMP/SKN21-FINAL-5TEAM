import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.frontend_evaluator import evaluate_frontend_workspace


def test_evaluate_frontend_workspace_detects_react_mount(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend" / "src").mkdir(parents=True)
    (workspace / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    report_path = evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert report_path.name == "frontend-evaluation.json"
    assert payload["framework"] == "react"
    assert payload["mount_candidates"] == ["frontend/src/App.js"]
    assert payload["passed"] is True


def test_evaluate_frontend_workspace_detects_vue_mount(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend" / "src").mkdir(parents=True)
    (workspace / "frontend" / "src" / "App.vue").write_text(
        "<template><Chatbot /></template>\n",
        encoding="utf-8",
    )

    report_path = evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["framework"] == "vue"
    assert payload["mount_candidates"] == ["frontend/src/App.vue"]
    assert payload["passed"] is True
