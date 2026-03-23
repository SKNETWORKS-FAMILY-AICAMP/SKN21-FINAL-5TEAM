import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

SRC_ROOT = Path(__file__).resolve().parents[3] / "chatbot" / "src"
frontend_evaluator_path = SRC_ROOT / "onboarding" / "frontend_evaluator.py"
frontend_evaluator_module = "chatbot.src.onboarding.frontend_evaluator"
spec = importlib.util.spec_from_file_location(frontend_evaluator_module, frontend_evaluator_path)
frontend_evaluator = importlib.util.module_from_spec(spec)
frontend_evaluator.__package__ = "chatbot.src.onboarding"
spec.loader.exec_module(frontend_evaluator)
evaluate_frontend_workspace = frontend_evaluator.evaluate_frontend_workspace


def test_evaluate_frontend_workspace_detects_react_mount(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend").mkdir(parents=True, exist_ok=True)
    (workspace / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "echo build"}}),
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() {\n"
        "  fetch('/api/chat/auth-token', { method: 'POST', credentials: 'include' });\n"
        "  return <div>Chat</div>;\n"
        "}\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "App.js").write_text(
        'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
        "function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        frontend_evaluator,
        "run_frontend_build",
        lambda *, workspace, timeout=120: {
            "workspace": str(workspace),
            "package_manager": "npm",
            "install_result": {
                "command": ["npm", "install"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
            },
            "build_result": {
                "command": ["npm", "run", "build"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
            },
        },
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
    frontend_artifact = payload["frontend_artifact"]
    assert frontend_artifact["source"] == "llm"
    assert frontend_artifact["validation_status"] == "valid"
    assert frontend_artifact["widget_path"].endswith("SharedChatbotWidget.jsx")
    assert payload["install_attempted"] is True
    assert payload["build_attempted"] is True
    assert payload["build_command"] == ["npm", "run", "build"]
    assert payload["build_passed"] is True
    assert payload["runtime_checks"]["mount_exists"] is True
    assert payload["runtime_checks"]["widget_exists"] is True
    assert payload["runtime_checks"]["bootstrap_auth_fetch_present"] is True


def test_evaluate_frontend_workspace_detects_vue_mount(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend").mkdir(parents=True, exist_ok=True)
    (workspace / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "echo build"}}),
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "App.vue").write_text(
        "<template><SharedChatbotWidget /></template>\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        frontend_evaluator,
        "run_frontend_build",
        lambda *, workspace, timeout=120: {
            "workspace": str(workspace),
            "package_manager": "npm",
            "install_result": {
                "command": ["npm", "install"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
            },
            "build_result": {
                "command": ["npm", "run", "build"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
            },
        },
    )

    report_path = evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["framework"] == "vue"
    assert payload["mount_candidates"] == ["frontend/src/App.vue"]
    assert payload["passed"] is True
    frontend_artifact = payload["frontend_artifact"]
    assert frontend_artifact["source"] == "llm"
    assert frontend_artifact["validation_status"] == "valid"
    assert frontend_artifact["widget_path"].endswith("SharedChatbotWidget.jsx")
    assert payload["install_attempted"] is True
    assert payload["build_attempted"] is True
    assert payload["build_command"] == ["npm", "run", "build"]
    assert payload["build_passed"] is True
    assert payload["runtime_checks"]["mount_exists"] is True
    assert payload["runtime_checks"]["widget_exists"] is True


def test_evaluate_frontend_workspace_recovers_when_widget_missing(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"
    (workspace / "frontend" / "src").mkdir(parents=True)
    # Mount candidate includes inline SharedChatbotWidget usage but no external widget file
    (workspace / "frontend" / "src" / "App.js").write_text(
        "function SharedChatbotWidget() { return <div>inline</div>; }\n"
        "function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )

    report_path = evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    frontend_artifact = payload["frontend_artifact"]
    assert frontend_artifact["source"] == "recovered_llm"
    assert frontend_artifact["validation_status"] == "invalid"
    assert any("widget file" in error for error in frontend_artifact["validation_errors"])
    assert payload["build_attempted"] is False


def test_evaluate_frontend_workspace_hard_fallbacks_when_mount_missing(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"
    (workspace / "frontend" / "src").mkdir(parents=True)
    (workspace / "frontend" / "src" / "App.js").write_text(
        "function App() { return <div>No Chatbot</div>; }\n",
        encoding="utf-8",
    )

    report_path = evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    frontend_artifact = payload["frontend_artifact"]
    assert frontend_artifact["source"] == "hard_fallback"
    assert frontend_artifact["validation_status"] == "invalid"
    assert any("mount" in error for error in frontend_artifact["validation_errors"])
    assert payload["passed"] is False
    assert payload["build_attempted"] is False


def test_evaluate_frontend_workspace_emits_observability_events(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"
    (workspace / "frontend" / "src").mkdir(parents=True)
    (workspace / "frontend" / "src" / "App.js").write_text(
        "function SharedChatbotWidget() { return <div>inline</div>; }\n"
        "function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )

    evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )

    trace_path = report_root / "execution-trace.jsonl"
    trace_lines = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert any(item["component"] == "frontend_evaluator" and item["event"] == "stage_started" for item in trace_lines)
    assert any(item["component"] == "frontend_evaluator" and item["event"] == "recovery_applied" for item in trace_lines)
    assert any(item["component"] == "frontend_evaluator" and item["event"] == "stage_completed" for item in trace_lines)


def test_evaluate_frontend_workspace_emits_hard_fallback_event_when_build_fails(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend").mkdir(parents=True, exist_ok=True)
    (workspace / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "echo build"}}),
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "App.js").write_text(
        'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
        "function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        frontend_evaluator,
        "run_frontend_build",
        lambda *, workspace, timeout=120: {
            "workspace": str(workspace),
            "package_manager": "npm",
            "install_result": {
                "command": ["npm", "install"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
            },
            "build_result": {
                "command": ["npm", "run", "build"],
                "returncode": 1,
                "stdout": "",
                "stderr": "build failed",
                "timed_out": False,
            },
        },
    )

    evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )

    trace_lines = [
        json.loads(line)
        for line in (report_root / "execution-trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fallback_events = [
        item
        for item in trace_lines
        if item["component"] == "frontend_evaluator" and item["event"] == "hard_fallback_used"
    ]

    assert fallback_events
    assert fallback_events[-1]["source"] == "hard_fallback"
    assert fallback_events[-1]["recovery"] == {
        "applied": False,
        "reason": "frontend_build_failed",
    }


def test_evaluate_frontend_workspace_reports_install_failure_metadata(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend").mkdir(parents=True, exist_ok=True)
    (workspace / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "echo build"}}),
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "App.js").write_text(
        'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
        "function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        frontend_evaluator,
        "run_frontend_build",
        lambda *, workspace, timeout=120: {
            "workspace": str(workspace),
            "package_manager": "npm",
            "install_result": {
                "command": ["npm", "install"],
                "returncode": 1,
                "stdout": "",
                "stderr": "npm install failed",
                "timed_out": False,
            },
            "build_result": None,
        },
    )

    report_path = evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    build_validation = json.loads((report_root / "frontend-build-validation.json").read_text(encoding="utf-8"))
    frontend_artifact = payload["frontend_artifact"]

    assert build_validation["bootstrap_failure_stage"] == "install_environment_failed"
    assert build_validation["bootstrap_failure_reason"] == "npm install failed"
    assert build_validation["build_attempted"] is False
    assert build_validation["build_passed"] is False
    assert frontend_artifact["source"] == "hard_fallback"
    assert frontend_artifact["validation_status"] == "valid"


def test_evaluate_frontend_workspace_ignores_warning_only_build_output_when_artifact_exists(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend" / "build").mkdir(parents=True, exist_ok=True)
    (workspace / "frontend" / "build" / "index.html").write_text("ok", encoding="utf-8")
    (workspace / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "echo build"}}),
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "App.js").write_text(
        'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
        "function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        frontend_evaluator,
        "run_frontend_build",
        lambda *, workspace, timeout=120: {
            "workspace": str(workspace),
            "package_manager": "npm",
            "install_result": {
                "command": ["npm", "install"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
            },
            "build_result": {
                "command": ["npm", "run", "build"],
                "returncode": 1,
                "stdout": "",
                "stderr": "(node:10161) [DEP0176] DeprecationWarning: fs.F_OK is deprecated, use fs.constants.F_OK instead\n(Use `node --trace-deprecation ...` to show where the warning was created)",
                "timed_out": False,
            },
        },
    )


def test_evaluate_frontend_workspace_rejects_widget_inside_routes(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "App.js").write_text(
        'import { Routes } from "react-router-dom";\n'
        'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
        "export default function App() {\n"
        "  return (\n"
        "    <Routes>\n"
        "      <SharedChatbotWidget />\n"
        "    </Routes>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )

    payload = json.loads(
        evaluate_frontend_workspace(runtime_workspace=workspace, report_root=report_root).read_text(encoding="utf-8")
    )

    assert payload["passed"] is False
    assert "routes child violation" in payload["frontend_artifact"]["validation_errors"]


def test_evaluate_frontend_workspace_rejects_widget_outside_frontend_src(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend" / "chatbot").mkdir(parents=True)
    (workspace / "frontend" / "src").mkdir(parents=True)
    (workspace / "frontend" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "App.js").write_text(
        'import SharedChatbotWidget from "../chatbot/SharedChatbotWidget";\n'
        "function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )

    payload = json.loads(
        evaluate_frontend_workspace(runtime_workspace=workspace, report_root=report_root).read_text(encoding="utf-8")
    )

    assert payload["passed"] is False
    assert "widget path outside frontend/src" in payload["frontend_artifact"]["validation_errors"]


def test_evaluate_frontend_workspace_ignores_node_modules_directories(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    report_root = tmp_path / "reports"

    (workspace / "frontend").mkdir(parents=True, exist_ok=True)
    (workspace / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"build": "echo build"}}),
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "chatbot").mkdir(parents=True)
    (workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx").write_text(
        "export default function SharedChatbotWidget() { return <div>Chat</div>; }\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "src" / "App.js").write_text(
        'import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";\n'
        "function App() { return <SharedChatbotWidget />; }\n",
        encoding="utf-8",
    )
    (workspace / "frontend" / "node_modules" / "big.js").mkdir(parents=True)
    (workspace / "frontend" / "node_modules" / "big.js" / "index.js").write_text(
        "export const big = true;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        frontend_evaluator,
        "run_frontend_build",
        lambda *, workspace, timeout=120: {
            "workspace": str(workspace),
            "package_manager": "npm",
            "install_result": {
                "command": ["npm", "install"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
            },
            "build_result": {
                "command": ["npm", "run", "build"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
            },
        },
    )

    report_path = evaluate_frontend_workspace(
        runtime_workspace=workspace,
        report_root=report_root,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["framework"] == "react"
    assert payload["mount_candidates"] == ["frontend/src/App.js"]
