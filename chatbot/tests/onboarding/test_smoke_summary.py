import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.smoke_runner import summarize_smoke_results


def test_summarize_smoke_results_counts_required_and_optional_failures():
    summary = summarize_smoke_results(
        [
            {
                "step": "smoke-tests/login.sh",
                "step_id": "login",
                "returncode": 0,
                "required": True,
                "timed_out": False,
                "stderr": "",
            },
            {
                "step": "smoke-tests/product_api.sh",
                "step_id": "product",
                "returncode": 1,
                "required": True,
                "timed_out": False,
                "stderr": "bad response",
            },
            {
                "step": "smoke-tests/order_api.sh",
                "step_id": "order",
                "returncode": 124,
                "required": False,
                "timed_out": True,
                "stderr": "",
            },
            {
                "step": "smoke-tests/chat_auth_token.sh",
                "step_id": "chat-auth",
                "returncode": 127,
                "required": True,
                "timed_out": False,
                "stderr": "Smoke script not found: /tmp/missing.sh",
            },
        ]
    )

    assert summary["passed"] is False
    assert summary["total_steps"] == 4
    assert summary["failure_count"] == 3
    assert summary["required_failures"] == ["product", "chat-auth"]
    assert summary["optional_failures"] == ["order"]
    assert summary["timed_out_steps"] == ["order"]
    assert summary["missing_scripts"] == ["chat-auth"]
    assert summary["failure_signature"] == "smoke:chat_auth_127|order_124|product_1"


def test_summarize_smoke_results_sorts_failure_signature_stably():
    summary = summarize_smoke_results(
        [
            {
                "step": "smoke-tests/chat_auth_token.sh",
                "step_id": "chat-auth",
                "returncode": 127,
                "required": True,
                "timed_out": False,
                "stderr": "Smoke script not found: /tmp/missing.sh",
            },
            {
                "step": "smoke-tests/order_api.sh",
                "step_id": "order",
                "returncode": 124,
                "required": False,
                "timed_out": True,
                "stderr": "",
            },
            {
                "step": "smoke-tests/product_api.sh",
                "step_id": "product",
                "returncode": 1,
                "required": True,
                "timed_out": False,
                "stderr": "bad response",
            },
        ]
    )

    assert summary["failure_signature"] == "smoke:chat_auth_127|order_124|product_1"
