from __future__ import annotations

import json
from pathlib import Path


def generate_backend_tool_registry(run_root: str | Path) -> Path:
    root = Path(run_root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    analysis = manifest.get("analysis") or {}
    enabled_tools = _resolve_enabled_tools(analysis=analysis)

    content = _build_tool_registry_content(enabled_tools=enabled_tools)
    output_path = root / "files" / "backend" / "tool_registry.py"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _resolve_enabled_tools(*, analysis: dict) -> list[str]:
    contract = analysis.get("integration_contract") or {}
    product_contract = contract.get("product_adapter") or {}
    order_contract = contract.get("order_adapter") or {}
    if product_contract.get("tool_names") or order_contract.get("tool_names"):
        return [
            *[str(item) for item in (product_contract.get("tool_names") or []) if str(item)],
            *[str(item) for item in (order_contract.get("tool_names") or []) if str(item)],
        ]

    enabled_tools: list[str] = []
    if analysis.get("product_api"):
        enabled_tools.append("product_list")
        if (analysis.get("product_api_shape") or {}).get("mode") != "root_array":
            enabled_tools.append("product_get")
    if analysis.get("order_api"):
        enabled_tools.append("orders_list")
        enabled_tools.append("orders_get")
        enabled_tools.append("orders_action")
    return enabled_tools


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
        "orders_list": '    registry["orders_list"] = order_adapter.list_orders',
        "orders_get": '    registry["orders_get"] = order_adapter.get_order',
        "orders_action": '    registry["orders_action"] = order_adapter.submit_order_action',
    }
    lines = header + [mappings[item] for item in enabled_tools if item in mappings] + ["    return registry", ""]
    return "\n".join(lines)
