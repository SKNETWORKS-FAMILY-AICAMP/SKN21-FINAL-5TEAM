from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.core.config import settings
from chatbot.src.graph.llm_providers import resolve_llm_runtime_policy


def test_resolve_runtime_policy_uses_server_defaults(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "vllm")
    monkeypatch.setattr(settings, "VLLM_MODEL", "Qwen/server-default")

    policy = resolve_llm_runtime_policy()

    assert policy.provider == "vllm"
    assert policy.model == "Qwen/server-default"
    assert policy.planner_prompt_variant == "strict-schema"


def test_resolve_runtime_policy_maps_huggingface_alias_to_local(monkeypatch):
    monkeypatch.setattr(settings, "HF_MODEL_ID", "Qwen/local-default")

    policy = resolve_llm_runtime_policy(provider="huggingface", model=None)

    assert policy.provider == "local"
    assert policy.model == "Qwen/local-default"
    assert policy.planner_prompt_variant == "strict-label-text"


def test_resolve_runtime_policy_prefers_explicit_model_over_defaults(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_MODEL", "gpt-server-default")

    policy = resolve_llm_runtime_policy(provider="openai", model="gpt-user-override")

    assert policy.provider == "openai"
    assert policy.model == "gpt-user-override"
