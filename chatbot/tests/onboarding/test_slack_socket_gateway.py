import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.approval_store import ApprovalStore
from chatbot.src.onboarding.slack_bridge import InMemorySlackBridge
from chatbot.src.onboarding.slack_socket_gateway import handle_interactive_action, register_socket_mode_handler


def test_gateway_records_button_click_decision(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)
    store.create_request(run_id="food-run-001", approval_type="apply")

    ack = handle_interactive_action(
        payload={
            "user": {"id": "U123"},
            "actions": [
                {
                    "value": json.dumps(
                        {
                        "run_id": "food-run-001",
                        "approval_type": "apply",
                        "decision": "approve",
                        }
                    ),
                }
            ],
        },
        store=store,
    )

    decision = store.get_decision(run_id="food-run-001", approval_type="apply")
    assert ack["ok"] is True
    assert decision is not None
    assert decision["status"] == "approved"
    assert decision["actor"] == "U123"


def test_gateway_ignores_non_pending_request(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)
    store.create_request(run_id="food-run-001", approval_type="export")
    store.record_decision(
        run_id="food-run-001",
        approval_type="export",
        decision="approve",
        actor="U123",
    )

    ack = handle_interactive_action(
        payload={
            "user": {"id": "U456"},
            "actions": [
                {
                    "value": json.dumps(
                        {
                        "run_id": "food-run-001",
                        "approval_type": "export",
                        "decision": "reject",
                        }
                    ),
                }
            ],
        },
        store=store,
    )

    decision = store.get_decision(run_id="food-run-001", approval_type="export")
    assert ack["ok"] is True
    assert ack["applied"] is False
    assert decision is not None
    assert decision["decision"] == "approve"
    assert decision["actor"] == "U123"


def test_register_socket_mode_handler_acknowledges_and_records_action(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)
    store.create_request(run_id="food-run-001", approval_type="apply")

    captured: dict[str, object] = {}

    class FakeSocketClient:
        def socket_mode_request_listeners(self):
            return []

    listeners: list = []

    class FakeClient:
        socket_mode_request_listeners = listeners

    def ack(envelope_id: str):
        captured["envelope_id"] = envelope_id

    register_socket_mode_handler(client=FakeClient(), store=store, ack=ack)

    request = {
        "envelope_id": "env-123",
        "payload": {
            "type": "block_actions",
            "user": {"id": "U123"},
            "actions": [
                {
                    "value": json.dumps(
                        {
                        "run_id": "food-run-001",
                        "approval_type": "apply",
                        "decision": "approve",
                        }
                    ),
                }
            ],
        },
    }

    listeners[0](None, request)

    decision = store.get_decision(run_id="food-run-001", approval_type="apply")
    assert captured["envelope_id"] == "env-123"
    assert decision is not None
    assert decision["status"] == "approved"


def test_gateway_parses_string_action_value():
    from chatbot.src.onboarding.slack_socket_gateway import parse_action_value

    parsed = parse_action_value('{"run_id":"food-run-001","approval_type":"apply","decision":"approve"}')

    assert parsed["run_id"] == "food-run-001"
    assert parsed["approval_type"] == "apply"
    assert parsed["decision"] == "approve"


def test_gateway_posts_decision_message_when_bridge_present(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)
    store.create_request(run_id="food-run-001", approval_type="apply")
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    ack = handle_interactive_action(
        payload={
            "user": {"id": "U123"},
            "actions": [
                {
                    "value": json.dumps(
                        {
                            "run_id": "food-run-001",
                            "approval_type": "apply",
                            "decision": "approve",
                        }
                    ),
                }
            ],
        },
        store=store,
        bridge=bridge,
    )

    assert ack["ok"] is True
    assert bridge.messages[-1]["message"]["text"].startswith("Approval decision recorded")
