import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_bundle
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.models.compile import EditProgram
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.planning import build_planning_bundle
from chatbot.src.onboarding.onboarding_ignore import runtime_copy_ignored_names


def _write_text(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_minimal_runtime_sources(tmp_path: Path) -> tuple[Path, Path]:
    host_root = tmp_path / "host-source"
    chatbot_root = tmp_path / "chatbot-source"
    _write_text(host_root / "backend" / "app.py", "print('host')\n")
    _write_text(chatbot_root / "server_fastapi.py", "app = object()\n")
    _write_text(chatbot_root / "src" / "__init__.py", "")
    _write_text(chatbot_root / "src" / "main.py", "print('chatbot')\n")
    _write_text(
        chatbot_root / "frontend" / "shared_widget" / "dist" / "widget.js",
        "console.log('widget');\n",
    )
    _write_text(chatbot_root / "chatbot_eval" / "benchmark" / "report.json", "{}\n")
    _write_text(chatbot_root / "tests" / "test_dummy.py", "def test_dummy():\n    assert True\n")
    _write_text(chatbot_root / ".pytest_cache" / "state", "cached\n")
    _write_text(chatbot_root / "src" / "chatbot_logs" / "server.log", "log\n")
    return host_root, chatbot_root


def test_apply_executor_materializes_food_changes(tmp_path: Path):
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    program = compile_plan(
        analysis_bundle=analysis_bundle,
        planning_bundle=planning_bundle,
        source_root=ROOT / "food",
    )

    result = apply_edit_program(
        host_source_root=ROOT / "food",
        chatbot_source_root=ROOT / "chatbot",
        runtime_root=tmp_path / "runtime",
        site="food",
        run_id="food-run-v2",
        edit_program=program,
    )

    workspace = Path(result.host_workspace_path)
    chatbot_workspace = Path(result.chatbot_workspace_path)
    assert result.passed is True
    assert (workspace / "backend" / "chat_auth.py").exists()
    app_js = (workspace / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    assert "__ORDER_CS_WIDGET_HOST_CONTRACT__" in app_js
    assert 'process.env.REACT_APP_CHATBOT_SERVER_BASE_URL || "http://127.0.0.1:8100"' in app_js
    assert "/api/chat/auth-token" in (workspace / "frontend" / "src" / "api" / "api.js").read_text(encoding="utf-8")
    order_views = (workspace / "backend" / "orders" / "views.py").read_text(encoding="utf-8")
    assert "new_option_id" in order_views
    assert "selected_product = get_object_or_404(Product, pk=new_option_id)" in order_views
    assert "if selected_product is not None:" in order_views
    assert '"new_option_id 값을 보내주세요."' not in order_views
    assert "order.product = selected_product" in order_views
    assert 'order.status = Order.Status.EXCHANGE_REQUESTED' in order_views
    assert (chatbot_workspace / "src" / "adapters" / "generated" / "food" / "adapter.py").exists()


def test_apply_executor_preserves_shared_widget_dist_bundle(tmp_path: Path):
    analysis_bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    planning_bundle = build_planning_bundle(
        snapshot=analysis_bundle.snapshot,
        analysis_bundle=analysis_bundle,
        chatbot_server_base_url="http://localhost:8100",
    )
    program = compile_plan(
        analysis_bundle=analysis_bundle,
        planning_bundle=planning_bundle,
        source_root=ROOT / "food",
    )

    result = apply_edit_program(
        host_source_root=ROOT / "food",
        chatbot_source_root=ROOT / "chatbot",
        runtime_root=tmp_path / "runtime",
        site="food",
        run_id="food-run-v2",
        edit_program=program,
    )

    source_bundle = Path(result.chatbot_source_snapshot_path) / "frontend" / "shared_widget" / "dist" / "widget.js"
    runtime_bundle = Path(result.chatbot_workspace_path) / "frontend" / "shared_widget" / "dist" / "widget.js"

    assert source_bundle.exists()
    assert runtime_bundle.exists()


def test_runtime_copy_ignore_helper_skips_chatbot_non_runtime_roots(tmp_path: Path):
    chatbot_root = tmp_path / "chatbot"
    chatbot_root.mkdir(parents=True)
    _write_text(chatbot_root / "server_fastapi.py", "app = object()\n")
    _write_text(chatbot_root / "src" / "__init__.py", "")
    _write_text(chatbot_root / "frontend" / "shared_widget" / "dist" / "widget.js", "ok\n")

    ignored_at_root = runtime_copy_ignored_names(
        str(chatbot_root),
        ["src", "frontend", "tests", "chatbot_eval", ".pytest_cache", "server_fastapi.py"],
    )
    ignored_under_src = runtime_copy_ignored_names(
        str(chatbot_root / "src"),
        ["chatbot_logs", "adapters"],
    )
    ignored_dist = runtime_copy_ignored_names(
        str(chatbot_root / "frontend" / "shared_widget"),
        ["dist"],
    )

    assert ignored_at_root == {"tests", "chatbot_eval", ".pytest_cache"}
    assert ignored_under_src == {"chatbot_logs"}
    assert ignored_dist == set()


def test_apply_executor_excludes_chatbot_non_runtime_trees_from_snapshot_and_workspace(
    tmp_path: Path,
):
    host_root, chatbot_root = _make_minimal_runtime_sources(tmp_path)

    result = apply_edit_program(
        host_source_root=host_root,
        chatbot_source_root=chatbot_root,
        runtime_root=tmp_path / "runtime",
        site="demo",
        run_id="demo-run-v2",
        edit_program=EditProgram(),
    )

    chatbot_snapshot = Path(result.chatbot_source_snapshot_path)
    chatbot_workspace = Path(result.chatbot_workspace_path)

    assert result.passed is True
    assert (chatbot_snapshot / "server_fastapi.py").exists()
    assert (chatbot_snapshot / "src" / "main.py").exists()
    assert (chatbot_workspace / "frontend" / "shared_widget" / "dist" / "widget.js").exists()
    assert not (chatbot_snapshot / "chatbot_eval").exists()
    assert not (chatbot_snapshot / "tests").exists()
    assert not (chatbot_snapshot / ".pytest_cache").exists()
    assert not (chatbot_snapshot / "src" / "chatbot_logs").exists()
    assert not (chatbot_workspace / "chatbot_eval").exists()
    assert not (chatbot_workspace / "tests").exists()
    assert not (chatbot_workspace / ".pytest_cache").exists()
    assert not (chatbot_workspace / "src" / "chatbot_logs").exists()


def test_apply_executor_summarizes_disk_full_runtime_copy_failures(tmp_path: Path, monkeypatch):
    host_root, chatbot_root = _make_minimal_runtime_sources(tmp_path)
    original_copytree = shutil.copytree

    def _fake_copytree(src, dst, *args, **kwargs):
        if Path(src) == chatbot_root:
            raise shutil.Error(
                [
                    (
                        str(chatbot_root / "chatbot_eval" / "benchmark" / "report.json"),
                        str(Path(dst) / "chatbot_eval" / "benchmark" / "report.json"),
                        "[Errno 28] No space left on device",
                    ),
                    (
                        str(chatbot_root / "tests" / "test_dummy.py"),
                        str(Path(dst) / "tests" / "test_dummy.py"),
                        "[Errno 28] No space left on device",
                    ),
                ]
            )
        return original_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(
        "chatbot.src.onboarding_v2.apply.executor.shutil.copytree",
        _fake_copytree,
    )

    result = apply_edit_program(
        host_source_root=host_root,
        chatbot_source_root=chatbot_root,
        runtime_root=tmp_path / "runtime",
        site="demo",
        run_id="demo-run-v2",
        edit_program=EditProgram(),
    )

    assert result.passed is False
    assert result.failure_summary == "runtime copy failed: no space left on device"
    assert result.failure_details["failure_code"] == "runtime_copy_no_space_left"
    assert result.failure_details["copy_context"] == "chatbot source snapshot"
    assert result.failure_details["offending_paths"] == [
        "chatbot_eval/benchmark/report.json",
        "tests/test_dummy.py",
    ]
    assert result.failed_bundles[0].bundle_id == "runtime_copy"
