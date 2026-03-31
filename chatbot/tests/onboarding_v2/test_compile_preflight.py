import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.compile.preflight import run_chatbot_compile_preflight


def test_preflight_fails_on_banned_import(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    tools = workspace / "src" / "tools"
    tools.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "from src.tools.order_tools import x\napp = object()\n",
        encoding="utf-8",
    )
    (tools / "order_tools.py").write_text(
        "from ecommerce.backend.app.database import SessionLocal\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is False
    assert result.failure_code == "banned_import_detected"
    assert "ecommerce.backend" in result.failure_summary
    assert "SessionLocal" in result.failure_summary


def test_preflight_allows_local_sessionlocal_import(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    tools = workspace / "src" / "tools"
    tools.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "app = object()\n",
        encoding="utf-8",
    )
    (tools / "session.py").write_text(
        "SessionLocal = object()\n",
        encoding="utf-8",
    )
    (tools / "order_tools.py").write_text(
        "from .session import SessionLocal\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is True
    assert result.failure_code is None


def test_preflight_fails_when_server_fastapi_import_breaks(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    workspace.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "raise ModuleNotFoundError('boom')\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is False
    assert result.failure_code == "chatbot_runtime_import_failed"
    assert "server_fastapi" in result.failure_summary


def test_preflight_passes_on_clean_workspace(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    workspace.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "app = object()\n",
        encoding="utf-8",
    )
    (workspace / "src").mkdir()
    (workspace / "src" / "helpers.py").write_text(
        "def helper():\n    return 1\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is True
    assert result.failure_code is None
    assert result.failure_summary is None


def test_preflight_ignores_banned_terms_in_comments_and_docstrings(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    tools = workspace / "src" / "tools"
    tools.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "app = object()\n",
        encoding="utf-8",
    )
    (tools / "order_tools.py").write_text(
        "\"\"\"This docstring mentions ecommerce.backend and SessionLocal.\"\"\"\n"
        "# ecommerce.backend and SessionLocal should be ignored here too\n"
        "def helper():\n"
        "    return True\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is True
    assert result.failure_code is None


def test_preflight_fails_on_runtime_source_syntax_error(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    tools = workspace / "src" / "tools"
    tools.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "app = object()\n",
        encoding="utf-8",
    )
    (tools / "order_tools.py").write_text(
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is False
    assert result.failure_code == "chatbot_runtime_source_syntax_error"
    assert "syntax error" in result.failure_summary
    assert "src/tools/order_tools.py" in result.related_files


def test_preflight_ignores_syntax_error_in_tests_directory(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "app = object()\n",
        encoding="utf-8",
    )
    (tests_dir / "test_broken.py").write_text(
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is True
    assert result.failure_code is None


def test_preflight_ignores_syntax_error_in_bench_directory(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    bench_dir = workspace / "src" / "bench"
    bench_dir.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "app = object()\n",
        encoding="utf-8",
    )
    (bench_dir / "bench_broken.py").write_text(
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is True
    assert result.failure_code is None


def test_preflight_passes_on_generated_adapter_only_workspace(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    tools_dir = workspace / "src" / "tools"
    adapters_dir = workspace / "src" / "adapters"
    langchain_core_dir = workspace / "langchain_core"
    langgraph_dir = workspace / "langgraph"
    tools_dir.mkdir(parents=True)
    adapters_dir.mkdir(parents=True)
    langchain_core_dir.mkdir(parents=True)
    langgraph_dir.mkdir(parents=True)

    adapter_source = (ROOT / "chatbot" / "src" / "tools" / "adapter_order_tools.py").read_text(encoding="utf-8")
    adapter_runtime_source = adapter_source.replace("from chatbot.src.", "from src.")

    (workspace / "server_fastapi.py").write_text(
        "from src.tools.adapter_order_tools import register_exchange_via_adapter\n"
        "app = object()\n",
        encoding="utf-8",
    )
    (tools_dir / "adapter_order_tools.py").write_text(
        adapter_runtime_source,
        encoding="utf-8",
    )
    (adapters_dir / "schema.py").write_text(
        "class AdapterError(Exception):\n"
        "    def __init__(self, code, message):\n"
        "        self.code = code\n"
        "        self.message = message\n"
        "        super().__init__(message)\n\n"
        "class AuthenticatedContext:\n"
        "    def __init__(self, userId, siteId, accessToken=None):\n"
        "        self.userId = userId\n"
        "        self.siteId = siteId\n"
        "        self.accessToken = accessToken\n\n"
        "class GetDeliveryTrackingInput:\n"
        "    pass\n\n"
        "class GetOrderStatusInput:\n"
        "    def __init__(self, orderId):\n"
        "        self.orderId = orderId\n\n"
        "class OrderActionReason:\n"
        "    SIMPLE_CHANGE_OF_MIND = 'simple_change_of_mind'\n\n"
        "class OrderActionType:\n"
        "    CANCEL = 'cancel'\n"
        "    REFUND = 'refund'\n"
        "    EXCHANGE = 'exchange'\n\n"
        "class ProductSearchFilter:\n"
        "    def __init__(self, query='', inStockOnly=True, limit=10):\n"
        "        self.query = query\n"
        "        self.inStockOnly = inStockOnly\n"
        "        self.limit = limit\n\n"
        "class SubmitOrderActionInput:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.__dict__.update(kwargs)\n",
        encoding="utf-8",
    )
    (adapters_dir / "setup.py").write_text(
        "ORDER_CS_BRIDGE_OPERATIONS = ['exchange']\n"
        "def get_adapter(site_id):\n"
        "    return None\n",
        encoding="utf-8",
    )
    (langchain_core_dir / "tools.py").write_text(
        "def tool(*args, **kwargs):\n"
        "    def decorator(fn):\n"
        "        return fn\n"
        "    return decorator\n",
        encoding="utf-8",
    )
    (langgraph_dir / "types.py").write_text(
        "def interrupt(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is True
    assert result.failure_code is None


def test_preflight_ignores_banned_imports_outside_scan_paths(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    tools_dir = workspace / "src" / "tools"
    generated_dir = workspace / "src" / "adapters" / "generated" / "food"
    tools_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text(
        "app = object()\n",
        encoding="utf-8",
    )
    (tools_dir / "order_tools.py").write_text(
        "from ecommerce.backend.app.database import SessionLocal\n",
        encoding="utf-8",
    )
    (generated_dir / "adapter.py").write_text(
        "def build_adapter():\n    return object()\n",
        encoding="utf-8",
    )

    result = run_chatbot_compile_preflight(
        workspace,
        scan_paths=["src/adapters/generated/food/adapter.py"],
    )

    assert result.passed is True
    assert result.failure_code is None
