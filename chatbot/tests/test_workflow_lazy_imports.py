from __future__ import annotations

import builtins
import importlib
import sys


def test_workflow_import_does_not_eagerly_import_optional_subagents(monkeypatch) -> None:
    blocked_modules = {
        "chatbot.src.graph.nodes.discovery_subagent",
        "chatbot.src.graph.nodes.policy_rag_subagent",
        "chatbot.src.graph.nodes.form_action_subagent",
    }

    for module_name in [
        "chatbot.src.graph.workflow",
        *blocked_modules,
    ]:
        sys.modules.pop(module_name, None)

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in blocked_modules:
            raise AssertionError(f"unexpected eager import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    workflow = importlib.import_module("chatbot.src.graph.workflow")

    assert getattr(workflow, "graph_app", None) is not None
