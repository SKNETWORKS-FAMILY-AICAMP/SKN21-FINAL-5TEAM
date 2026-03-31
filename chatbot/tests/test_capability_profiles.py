from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.capability_profiles import split_tasks_for_profile


def test_retrieval_profile_allows_text_discovery_when_image_corpus_enabled():
    allowed, disallowed = split_tasks_for_profile(
        ["SEARCH_SIMILAR_TEXT"],
        capability_profile="order_cs_plus_retrieval",
        enabled_retrieval_corpora=["discovery_image"],
    )

    assert allowed == ["SEARCH_SIMILAR_TEXT"]
    assert disallowed == []


def test_retrieval_profile_blocks_text_discovery_without_discovery_corpus():
    allowed, disallowed = split_tasks_for_profile(
        ["SEARCH_SIMILAR_TEXT"],
        capability_profile="order_cs_plus_retrieval",
        enabled_retrieval_corpora=["faq"],
    )

    assert allowed == []
    assert disallowed == ["SEARCH_SIMILAR_TEXT"]
