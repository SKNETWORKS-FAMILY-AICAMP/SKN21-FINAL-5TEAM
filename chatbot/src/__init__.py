from __future__ import annotations

import importlib
from typing import Any

from ._module_alias import install_chatbot_src_aliases


install_chatbot_src_aliases()


def __getattr__(name: str) -> Any:
    if name.startswith("__"):
        raise AttributeError(name)
    return importlib.import_module(f"{__name__}.{name}")
