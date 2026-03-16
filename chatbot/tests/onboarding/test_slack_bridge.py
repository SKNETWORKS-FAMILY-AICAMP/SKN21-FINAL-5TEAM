import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.agent_contracts import AgentMessage, ApprovalType, RunEvent, RunState
from chatbot.src.onboarding.slack_bridge import InMemorySlackBridge, SlackWebBridge


def test_slack_bridge_posts_root_message_and_preserves_thread_key():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    payload = bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    assert payload["channel"] == "#onboarding-runs"
    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["run_id"] == "food-run-001"


def test_slack_bridge_posts_agent_message_into_same_thread():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    event = RunEvent(
        event_type="analysis.completed",
        run_id="food-run-001",
        state=RunState.ANALYZING,
        payload={"phase": "analysis"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Analyzer",
        claim="Detected session auth",
        evidence=["session token cookie is read in login flow"],
        confidence=0.91,
        risk="medium",
        next_action="forward auth capability to planner",
        blocking_issue="none",
    )

    payload = bridge.post_agent_message(event=event, message=message)

    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["role"] == "Analyzer"
    assert payload["message"]["event_type"] == "analysis.completed"


def test_slack_bridge_posts_approval_request_payload():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    payload = bridge.post_approval_request(
        run_id="food-run-001",
        approval_type=ApprovalType.APPLY,
        summary="Overlay is ready to apply",
        recommended_option="approve",
        risk_if_approved="runtime patch may fail",
        risk_if_rejected="run will stop before validation",
        available_actions=["approve", "reject"],
    )

    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["approval_type"] == "apply"
    assert payload["message"]["recommended_option"] == "approve"
    actions = payload["message"]["actions"]
    assert actions[0]["text"] == "Approve"
    approve_value = json.loads(actions[0]["value"])
    assert approve_value["run_id"] == "food-run-001"
    assert approve_value["approval_type"] == "apply"
    assert approve_value["decision"] == "approve"
    assert actions[1]["text"] == "Reject"
    reject_value = json.loads(actions[1]["value"])
    assert reject_value["decision"] == "reject"


def test_slack_bridge_keeps_all_messages_in_memory():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    bridge.post_approval_request(
        run_id="food-run-001",
        approval_type=ApprovalType.ANALYSIS,
        summary="Confirm analysis",
        recommended_option="approve",
        risk_if_approved="bad analysis propagates",
        risk_if_rejected="run pauses",
        available_actions=["approve", "reject"],
    )

    assert len(bridge.messages) == 2
    assert all(entry["thread_key"] == "food-run-001" for entry in bridge.messages)


def test_slack_bridge_preserves_diagnostic_evidence():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    event = RunEvent(
        event_type="diagnosis.completed",
        run_id="food-run-001",
        state=RunState.DIAGNOSING,
        payload={"phase": "diagnosis"},
        created_at="2026-03-16T10:00:00+09:00",
    )
    message = AgentMessage(
        role="Diagnostician",
        claim="Structural failure should stop retries",
        evidence=[
            "failure signature: missing:127",
            "retryable: False",
            "missing scripts: ['missing']",
        ],
        confidence=0.9,
        risk="high",
        next_action="request_human_review",
        blocking_issue="missing smoke script",
    )

    payload = bridge.post_agent_message(event=event, message=message)

    assert payload["message"]["role"] == "Diagnostician"
    assert "retryable: False" in payload["message"]["evidence"]


def test_slack_bridge_can_record_export_approval_decision():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    payload = bridge.record_approval_decision(
        run_id="food-run-001",
        approval_type="export",
        decision="approve",
    )

    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["approval_type"] == "export"
    assert payload["message"]["decision"] == "approve"


def test_slack_web_bridge_stores_thread_ts_from_root_message():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)

    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    event = RunEvent(
        event_type="analysis.completed",
        run_id="food-run-001",
        state=RunState.ANALYZING,
        payload={"phase": "analysis"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Analyzer",
        claim="Detected session auth",
        evidence=["session token cookie is read in login flow"],
        confidence=0.91,
        risk="medium",
        next_action="forward auth capability to planner",
        blocking_issue="none",
    )

    bridge.post_agent_message(event=event, message=message)

    assert client.calls[1]["thread_ts"] == "1710000000.100"


def test_slack_web_bridge_posts_block_kit_approval_message():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    payload = bridge.post_approval_request(
        run_id="food-run-001",
        approval_type=ApprovalType.APPLY,
        summary="Overlay is ready to apply",
        recommended_option="approve",
        risk_if_approved="runtime patch may fail",
        risk_if_rejected="run will stop before validation",
        available_actions=["approve", "reject"],
    )

    blocks = client.calls[-1]["blocks"]
    assert blocks[-1]["type"] == "actions"
    assert blocks[-1]["elements"][0]["type"] == "button"
    assert blocks[-1]["elements"][0]["text"]["text"] == "Approve"
    assert payload["message"]["approval_type"] == "apply"


def test_slack_web_bridge_includes_generator_targets_in_message_text():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    event = RunEvent(
        event_type="generation.completed",
        run_id="food-run-001",
        state=RunState.GENERATING,
        payload={"phase": "generation"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Generator",
        claim="Prepared overlay artifact proposal",
        evidence=["proposal ready"],
        confidence=0.88,
        risk="medium",
        next_action="materialize proposed files and patches",
        blocking_issue="none",
        metadata={
            "proposed_files": ["files/backend/chat_auth.py"],
            "proposed_patches": ["patches/frontend_widget_mount.patch"],
        },
    )

    bridge.post_agent_message(event=event, message=message)

    assert "chat_auth.py" in client.calls[-1]["text"]
