from __future__ import annotations

import builtins
import importlib
import sys


def _purge_modules(*prefixes: str) -> None:
    for module_name in list(sys.modules):
        if any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in prefixes
        ):
            sys.modules.pop(module_name, None)


def _block_optional_ecommerce_imports(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ecommerce.backend" or name.startswith("ecommerce.backend."):
            raise ModuleNotFoundError(f"blocked optional import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_chat_core_router_imports_without_optional_ecommerce_backend(monkeypatch) -> None:
    _purge_modules(
        "chatbot.src.api.v1.endpoints.chat",
        "chatbot.src.api.v1.endpoints.chat_extensions_ecommerce",
        "chatbot.src.tools.service_tools",
        "ecommerce",
    )
    _block_optional_ecommerce_imports(monkeypatch)

    module = importlib.import_module("chatbot.src.api.v1.endpoints.chat")

    assert getattr(module, "router", None) is not None


def test_server_fastapi_imports_core_routes_without_optional_ecommerce_backend(monkeypatch) -> None:
    _purge_modules(
        "chatbot.server_fastapi",
        "chatbot.src.api.v1.endpoints.chat",
        "chatbot.src.api.v1.endpoints.chat_extensions_ecommerce",
        "chatbot.src.tools.service_tools",
        "ecommerce",
    )
    _block_optional_ecommerce_imports(monkeypatch)

    module = importlib.import_module("chatbot.server_fastapi")
    route_paths = {route.path for route in module.app.routes}
    extension_state = getattr(module.app.state, "optional_extensions", {})

    assert "/widget.js" in route_paths
    assert "/api/v1/chat/stream" in route_paths
    assert "/api/v1/chat/auth-token" not in route_paths
    assert extension_state["ecommerce_chat"]["enabled"] is False
