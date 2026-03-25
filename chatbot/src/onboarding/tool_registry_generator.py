from __future__ import annotations

import json
from pathlib import Path

ORDER_BRIDGE_TOOLS = [
    "list_orders",
    "get_order_status",
    "cancel",
    "refund",
    "exchange",
]


def generate_backend_tool_registry(run_root: str | Path) -> Path:
    root = Path(run_root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    analysis = manifest.get("analysis") or {}
    enabled_tools: list[str] = []
    if analysis.get("product_api"):
        enabled_tools.append("product_list")
    if analysis.get("product_api"):
        enabled_tools.append("product_get")
    if analysis.get("order_api"):
        enabled_tools.extend(ORDER_BRIDGE_TOOLS)

    content = _build_tool_registry_content(enabled_tools=enabled_tools)
    output_path = root / "files" / "backend" / "tool_registry.py"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _build_tool_registry_content(*, enabled_tools: list[str]) -> str:
    header = [
        "from backend.order_adapter_client import GeneratedOrderAdapterClient",
        "from backend.product_adapter_client import GeneratedProductAdapterClient",
        "",
        "",
        "def build_tool_registry(base_url: str) -> dict[str, object]:",
        "    product_adapter = GeneratedProductAdapterClient(base_url=base_url)",
        "    order_adapter = GeneratedOrderAdapterClient(base_url=base_url)",
        "    registry: dict[str, object] = {}",
    ]
    mappings = {
        "product_list": '    registry["product_list"] = product_adapter.list_products',
        "product_get": '    registry["product_get"] = product_adapter.get_product',
        "list_orders": '    registry["list_orders"] = order_adapter.list_orders',
        "get_order_status": '    registry["get_order_status"] = order_adapter.get_order_status',
        "cancel": '    registry["cancel"] = order_adapter.cancel',
        "refund": '    registry["refund"] = order_adapter.refund',
        "exchange": '    registry["exchange"] = order_adapter.exchange',
    }
    lines = header + [mappings[item] for item in enabled_tools if item in mappings] + ["    return registry", ""]
    return "\n".join(lines)
