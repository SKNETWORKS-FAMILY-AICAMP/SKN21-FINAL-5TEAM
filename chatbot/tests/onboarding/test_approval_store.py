import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.approval_store import ApprovalStore


def test_approval_store_records_and_reads_decision(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)

    store.create_request(run_id="food-run-001", approval_type="apply")
    store.record_decision(
        run_id="food-run-001",
        approval_type="apply",
        decision="approve",
        actor="U123",
    )

    decision = store.get_decision(run_id="food-run-001", approval_type="apply")

    assert decision is not None
    assert decision["request_id"] == "food-run-001:apply"
    assert decision["status"] == "approved"
    assert decision["decision"] == "approve"
    assert decision["actor"] == "U123"


def test_approval_store_consumes_decision_once(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)

    store.create_request(run_id="food-run-001", approval_type="export")
    store.record_decision(
        run_id="food-run-001",
        approval_type="export",
        decision="reject",
        actor="U234",
    )

    consumed = store.consume_decision(run_id="food-run-001", approval_type="export")

    assert consumed is not None
    assert consumed["status"] == "consumed"
    assert consumed["decision"] == "reject"

    refreshed = json.loads((tmp_path / "food-run-001__export.json").read_text(encoding="utf-8"))
    assert refreshed["status"] == "consumed"
    assert refreshed["consumed_at"] is not None
