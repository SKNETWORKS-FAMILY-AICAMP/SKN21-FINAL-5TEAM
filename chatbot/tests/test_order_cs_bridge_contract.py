import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_order_cs_bridge_contract_is_normalized():
    module = importlib.import_module("chatbot.src.tools.adapter_order_tools")
    bridge_factory = getattr(module, "build_order_cs_bridge", None)

    assert callable(bridge_factory), "build_order_cs_bridge must exist"

    registry = bridge_factory(site_id="site-a")

    assert {"list_orders", "get_order_status", "cancel", "refund", "exchange"} <= set(registry)
