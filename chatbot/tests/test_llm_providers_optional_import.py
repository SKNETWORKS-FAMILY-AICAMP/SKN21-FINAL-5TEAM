from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_llm_providers_imports_without_langchain_ollama(monkeypatch):
    monkeypatch.delitem(sys.modules, "langchain_ollama", raising=False)
    monkeypatch.delitem(sys.modules, "chatbot.src.graph.llm_providers", raising=False)

    module = importlib.import_module("chatbot.src.graph.llm_providers")

    policy = module.resolve_llm_runtime_policy(provider="openai", model="gpt-5-mini")

    assert policy.provider == "openai"
    assert policy.model == "gpt-5-mini"
