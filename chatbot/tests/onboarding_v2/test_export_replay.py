import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.export import export_and_replay
from chatbot.src.onboarding_v2.storage import ArtifactStore


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copytree(source: Path, target: Path) -> None:
    shutil.copytree(source, target)


def _host_frontend_mount() -> str:
    return """const ORDER_CS_WIDGET_HOST_CONTRACT = {
  chatbotServerBaseUrl: "http://127.0.0.1:8100",
  authBootstrapPath: "/api/chat/auth-token",
  widgetBundlePath: "/widget.js",
  widgetElementTag: "order-cs-widget",
  mountMode: "floating_launcher",
};

globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"] = ORDER_CS_WIDGET_HOST_CONTRACT;

export default function App() {
  return <order-cs-widget />;
}
"""


def _build_replay_fixture(tmp_path: Path) -> dict[str, Path]:
    host_source_root = tmp_path / "host-source"
    chatbot_source_root = tmp_path / "chatbot-source"
    host_baseline_root = tmp_path / "host-baseline"
    chatbot_baseline_root = tmp_path / "chatbot-baseline"
    host_runtime_workspace = tmp_path / "host-runtime"
    chatbot_runtime_workspace = tmp_path / "chatbot-runtime"
    generated_root = tmp_path / "generated" / "demo" / "demo-run-v2"
    runtime_root = tmp_path / "runtime"

    _write(
        host_source_root / "backend" / "app.py",
        "from flask import Flask\napp = Flask(__name__)\n",
    )
    _write(host_source_root / "frontend" / "src" / "App.js", _host_frontend_mount())
    _write(
        chatbot_source_root / "src" / "adapters" / "setup.py",
        "ORDER_CS_BRIDGE_OPERATIONS = ('list_orders',)\n",
    )
    _write(
        chatbot_source_root / "src" / "adapters" / "generated" / "demo" / "adapter.py",
        "class DemoAdapter:\n    pass\n",
    )

    _copytree(host_source_root, host_baseline_root)
    _copytree(chatbot_source_root, chatbot_baseline_root)
    _copytree(host_baseline_root, host_runtime_workspace)
    _copytree(chatbot_baseline_root, chatbot_runtime_workspace)

    _write(
        host_runtime_workspace / "backend" / "app.py",
        "from flask import Flask\napp = Flask(__name__)\napp.config['PATCHED'] = True\n",
    )
    _write(
        chatbot_runtime_workspace / "src" / "adapters" / "setup.py",
        "ORDER_CS_BRIDGE_OPERATIONS = ('list_orders', 'cancel')\n",
    )

    return {
        "host_source_root": host_source_root,
        "chatbot_source_root": chatbot_source_root,
        "host_baseline_root": host_baseline_root,
        "chatbot_baseline_root": chatbot_baseline_root,
        "host_runtime_workspace": host_runtime_workspace,
        "chatbot_runtime_workspace": chatbot_runtime_workspace,
        "generated_root": generated_root,
        "runtime_root": runtime_root,
    }


def test_export_replay_applies_exported_patch(tmp_path: Path):
    fixture = _build_replay_fixture(tmp_path)

    export_bundle_ref, replay_result, replay_ref = export_and_replay(
        host_source_root=fixture["host_source_root"],
        chatbot_source_root=fixture["chatbot_source_root"],
        host_baseline_root=fixture["host_baseline_root"],
        chatbot_baseline_root=fixture["chatbot_baseline_root"],
        host_runtime_workspace=fixture["host_runtime_workspace"],
        chatbot_runtime_workspace=fixture["chatbot_runtime_workspace"],
        host_allowed_targets={"backend/app.py"},
        chatbot_allowed_targets={"src/adapters/setup.py"},
        runtime_root=fixture["runtime_root"],
        run_root=fixture["generated_root"],
        site="demo",
        run_id="demo-run-v2",
        artifact_store=ArtifactStore(fixture["generated_root"]),
    )

    assert export_bundle_ref.version == 1
    assert replay_ref.version == 1
    assert replay_result.passed is True
    assert replay_result.target_match_passed is True
    assert replay_result.static_validation_passed is True
    assert replay_result.mismatched_targets == []


def test_export_replay_fails_when_replay_targets_do_not_match_runtime(tmp_path: Path):
    fixture = _build_replay_fixture(tmp_path)

    def _fake_apply_patch_file(*, patch_path, workspace):
        del patch_path, workspace
        return None

    with patch(
        "chatbot.src.onboarding_v2.export.replay._apply_patch_file",
        _fake_apply_patch_file,
    ):
        _, replay_result, _ = export_and_replay(
            host_source_root=fixture["host_source_root"],
            chatbot_source_root=fixture["chatbot_source_root"],
            host_baseline_root=fixture["host_baseline_root"],
            chatbot_baseline_root=fixture["chatbot_baseline_root"],
            host_runtime_workspace=fixture["host_runtime_workspace"],
            chatbot_runtime_workspace=fixture["chatbot_runtime_workspace"],
            host_allowed_targets={"backend/app.py"},
            chatbot_allowed_targets={"src/adapters/setup.py"},
            runtime_root=fixture["runtime_root"],
            run_root=fixture["generated_root"],
            site="demo",
            run_id="demo-run-v2",
            artifact_store=ArtifactStore(fixture["generated_root"]),
        )

    assert replay_result.passed is False
    assert replay_result.target_match_passed is False
    assert replay_result.mismatched_targets == [
        "chatbot:src/adapters/setup.py",
        "host:backend/app.py",
    ]


def test_export_replay_fails_when_static_validation_fails(tmp_path: Path):
    fixture = _build_replay_fixture(tmp_path)
    _write(
        fixture["host_runtime_workspace"] / "backend" / "app.py",
        "def broken(:\n",
    )

    _, replay_result, _ = export_and_replay(
        host_source_root=fixture["host_source_root"],
        chatbot_source_root=fixture["chatbot_source_root"],
        host_baseline_root=fixture["host_baseline_root"],
        chatbot_baseline_root=fixture["chatbot_baseline_root"],
        host_runtime_workspace=fixture["host_runtime_workspace"],
        chatbot_runtime_workspace=fixture["chatbot_runtime_workspace"],
        host_allowed_targets={"backend/app.py"},
        chatbot_allowed_targets={"src/adapters/setup.py"},
        runtime_root=fixture["runtime_root"],
        run_root=fixture["generated_root"],
        site="demo",
        run_id="demo-run-v2",
        artifact_store=ArtifactStore(fixture["generated_root"]),
    )

    assert replay_result.passed is False
    assert replay_result.target_match_passed is True
    assert replay_result.static_validation_passed is False
    assert "python compile failed" in (replay_result.static_validation_summary or "")
