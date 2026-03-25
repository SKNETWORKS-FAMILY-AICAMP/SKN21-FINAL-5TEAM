from __future__ import annotations

from typing import Any, Callable


def build_repair_llm_factory(
    *,
    provider: str,
    model: str,
    llm_builder: Callable[[str, str, float], Any] | None = None,
) -> Callable[[], Any]:
    def _build() -> Any:
        builder = llm_builder
        if builder is None:
            from chatbot.src.graph.llm_providers import make_chat_llm

            builder = make_chat_llm
        return builder(provider, model, 0)

    return _build
