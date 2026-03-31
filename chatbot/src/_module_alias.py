from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
import types
from pathlib import Path


def _attach_module_alias(fullname: str, module: types.ModuleType) -> None:
    sys.modules[fullname] = module
    parent_name, _, child_name = fullname.rpartition(".")
    if not parent_name or not child_name:
        return
    parent_module = sys.modules.get(parent_name)
    if parent_module is not None:
        setattr(parent_module, child_name, module)


class _ChatbotSrcAliasLoader(importlib.abc.Loader):
    def __init__(self, canonical_name: str):
        self._canonical_name = canonical_name

    def create_module(self, spec):
        module = importlib.import_module(self._canonical_name)
        _attach_module_alias(spec.name, module)
        return module

    def exec_module(self, module) -> None:  # pragma: no cover - no-op alias loader
        return None


class _ChatbotSrcAliasFinder(importlib.abc.MetaPathFinder):
    PREFIX = "chatbot.src."

    def find_spec(self, fullname: str, path=None, target=None):
        if not fullname.startswith(self.PREFIX):
            return None
        canonical_name = f"src.{fullname[len(self.PREFIX):]}"
        canonical_spec = importlib.util.find_spec(canonical_name)
        if canonical_spec is None:
            return None
        loader = _ChatbotSrcAliasLoader(canonical_name)
        spec = importlib.util.spec_from_loader(
            fullname,
            loader,
            is_package=canonical_spec.submodule_search_locations is not None,
        )
        if spec is not None:
            spec.origin = canonical_spec.origin
        return spec


def install_chatbot_src_aliases(*, chatbot_ns: types.ModuleType | None = None) -> types.ModuleType:
    try:
        canonical_src = importlib.import_module("src")
    except ModuleNotFoundError:
        workspace_root = str(Path(__file__).resolve().parents[1])
        if workspace_root not in sys.path:
            sys.path.insert(0, workspace_root)
        canonical_src = importlib.import_module("src")
    if chatbot_ns is None:
        chatbot_ns = sys.modules.get("chatbot")
        if chatbot_ns is None:
            chatbot_ns = types.ModuleType("chatbot")
            sys.modules["chatbot"] = chatbot_ns

    setattr(chatbot_ns, "src", canonical_src)
    _attach_module_alias("chatbot.src", canonical_src)

    if not any(isinstance(finder, _ChatbotSrcAliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _ChatbotSrcAliasFinder())
    return canonical_src
