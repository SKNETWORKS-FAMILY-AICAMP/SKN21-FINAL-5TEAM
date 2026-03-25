import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_snapshot
from chatbot.src.onboarding_v2.apply import apply_edit_program
from chatbot.src.onboarding_v2.compile import compile_plan
from chatbot.src.onboarding_v2.planning import build_integration_plan


def test_apply_executor_materializes_food_changes(tmp_path: Path):
    snapshot = build_analysis_snapshot(site="food", source_root=ROOT / "food")
    plan = build_integration_plan(
        snapshot,
        chatbot_server_base_url="http://localhost:8100",
    )
    program = compile_plan(snapshot=snapshot, plan=plan, source_root=ROOT / "food")

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
