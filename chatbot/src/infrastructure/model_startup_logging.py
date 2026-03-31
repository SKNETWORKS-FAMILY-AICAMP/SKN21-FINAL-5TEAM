from __future__ import annotations

import logging
import os

_QUIET_LOGGER_LEVELS = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "huggingface_hub": logging.WARNING,
    "transformers": logging.ERROR,
}


def _set_minimum_level(logger_name: str, level: int) -> None:
    logger = logging.getLogger(logger_name)
    current = logger.level
    if current == logging.NOTSET or current < level:
        logger.setLevel(level)


def configure_model_startup_logging() -> None:
    """
    Reduce known Hugging Face/Transformers startup noise without affecting app logs.
    """
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

    for logger_name, level in _QUIET_LOGGER_LEVELS.items():
        _set_minimum_level(logger_name, level)

    try:
        from transformers.utils import logging as transformers_logging

        transformers_logger = logging.getLogger("transformers")
        previous_level = transformers_logger.level
        transformers_logging.set_verbosity_error()
        if previous_level > logging.ERROR:
            transformers_logger.setLevel(previous_level)
        transformers_logging.disable_progress_bar()
    except Exception:
        pass

    try:
        from huggingface_hub.utils import disable_progress_bars

        disable_progress_bars()
    except Exception:
        pass
