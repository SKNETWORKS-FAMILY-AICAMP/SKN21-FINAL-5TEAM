from __future__ import annotations

from typing import Any, Callable

from chatbot.src.graph.llm_providers import make_chat_llm


def build_repair_llm_factory(
    *,
    provider: str,
    model: str,
    llm_builder: Callable[[str, str, float], Any] = make_chat_llm,
) -> Callable[[], Any]:
    return lambda: llm_builder(provider, model, 0)
