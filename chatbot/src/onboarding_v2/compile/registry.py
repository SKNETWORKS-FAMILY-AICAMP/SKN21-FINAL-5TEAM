from __future__ import annotations

from collections.abc import Callable


class CompilerRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, Callable] = {}

    def register(self, strategy: str, compiler: Callable) -> None:
        self._registry[strategy] = compiler

    def resolve(self, strategy: str) -> Callable:
        if strategy not in self._registry:
            raise KeyError(f"compiler strategy not registered: {strategy}")
        return self._registry[strategy]
