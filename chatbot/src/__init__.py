from __future__ import annotations

import importlib
from typing import Any


def __getattr__(name: str) -> Any:
    if name.startswith("__"):
        raise AttributeError(name)
    return importlib.import_module(f"{__name__}.{name}")
