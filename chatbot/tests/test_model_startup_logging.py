from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.infrastructure.model_startup_logging import configure_model_startup_logging


def test_configure_model_startup_logging_sets_quiet_defaults(monkeypatch):
    monkeypatch.delenv("TRANSFORMERS_NO_ADVISORY_WARNINGS", raising=False)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
    logging.getLogger("huggingface_hub").setLevel(logging.INFO)
    logging.getLogger("transformers").setLevel(logging.INFO)

    configure_model_startup_logging()

    assert os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] == "1"
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert logging.getLogger("huggingface_hub").level == logging.WARNING
    assert logging.getLogger("transformers").level == logging.ERROR


def test_configure_model_startup_logging_keeps_stricter_existing_levels():
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("transformers").setLevel(logging.CRITICAL)

    configure_model_startup_logging()

    assert logging.getLogger("httpx").level == logging.ERROR
    assert logging.getLogger("transformers").level == logging.CRITICAL
