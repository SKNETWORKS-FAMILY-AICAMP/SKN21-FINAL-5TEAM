import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.generator_eval import run_generator_eval
from chatbot.src.onboarding.role_runner import RoleRunner


def test_current_generator_path_passes_golden_fixtures():
    fixture_dir = Path(__file__).resolve().parent / "goldens" / "generator"

    role_runner = RoleRunner(
        responders={
            "Generator": lambda context: {
                "claim": "Prepared baseline overlay proposal",
                "evidence": context["evidence"],
                "confidence": 0.82,
                "risk": "medium",
                "next_action": "materialize all baseline overlay artifacts",
                "blocking_issue": "none",
                "metadata": {
                    "proposed_files": [
                        "files/backend/chat_auth.py",
                        "files/backend/order_adapter_client.py",
                        "files/backend/product_adapter_client.py",
                    ],
                    "proposed_patches": [
                        "patches/frontend_widget_mount.patch",
                    ],
                },
            }
        }
    )

    summary = run_generator_eval(
        fixture_dir=fixture_dir,
        role_runner=role_runner,
    )

    assert summary["total"] >= 6
    assert summary["failed"] == 0
    assert summary["failed_fixture_ids"] == []
