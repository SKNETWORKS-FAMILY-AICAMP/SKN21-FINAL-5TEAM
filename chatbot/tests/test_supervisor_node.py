from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.graph.nodes import supervisor
from chatbot.src.schemas.planner import TaskIntent


def test_supervisor_order_cs_only_converts_pure_disallowed_queue_to_unsupported_notice() -> None:
    result = supervisor.supervisor_node(
        {
            "pending_tasks": [TaskIntent.WRITE_REVIEW],
            "completed_tasks": [],
            "agent_results": {},
            "capability_profile": "order_cs_only",
        }
    )

    assert result["current_active_task"] is None
    assert result["pending_tasks"] == []
    assert result["completed_tasks"] == [TaskIntent.GENERAL_CHAT]
    assert "지원하지 않습니다" in result["agent_results"][TaskIntent.GENERAL_CHAT]


def test_supervisor_order_cs_only_keeps_allowed_order_task_and_records_notice() -> None:
    result = supervisor.supervisor_node(
        {
            "pending_tasks": [TaskIntent.ORDER_CS, TaskIntent.WRITE_REVIEW],
            "completed_tasks": [],
            "agent_results": {},
            "capability_profile": "order_cs_only",
        }
    )

    assert result["current_active_task"] == TaskIntent.ORDER_CS
    assert result["pending_tasks"] == []
    assert result["completed_tasks"] == [TaskIntent.GENERAL_CHAT]
    assert "지원하지 않습니다" in result["agent_results"][TaskIntent.GENERAL_CHAT]


def test_supervisor_retrieval_profile_blocks_image_when_discovery_corpus_missing() -> None:
    result = supervisor.supervisor_node(
        {
            "pending_tasks": [TaskIntent.SEARCH_SIMILAR_IMAGE, TaskIntent.POLICY_RAG],
            "completed_tasks": [],
            "agent_results": {},
            "capability_profile": "order_cs_plus_retrieval",
            "enabled_retrieval_corpora": ["faq"],
        }
    )

    assert result["current_active_task"] == TaskIntent.POLICY_RAG
    assert result["pending_tasks"] == []
    assert result["completed_tasks"] == [TaskIntent.GENERAL_CHAT]
    assert "지원하지 않습니다" in result["agent_results"][TaskIntent.GENERAL_CHAT]
