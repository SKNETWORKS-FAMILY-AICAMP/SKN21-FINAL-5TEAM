import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.generator_eval import run_generator_eval
from chatbot.src.onboarding.role_runner import RoleRunner


def test_generator_eval_runner_executes_all_fixtures_and_writes_report(tmp_path: Path):
    fixture_dir = tmp_path / "fixtures"
    report_path = tmp_path / "generator-eval-report.json"
    fixture_dir.mkdir()

    (fixture_dir / "food-basic.json").write_text(
        json.dumps(
            {
                "id": "food-basic",
                "site": "food",
                "input": {
                    "analysis": {"framework": {"backend": "django", "frontend": "react"}},
                    "recommended_outputs": ["chat_auth", "frontend_patch"],
                },
                "expected": {
                    "proposed_files": ["files/backend/chat_auth.py"],
                    "proposed_patches": ["patches/frontend_widget_mount.patch"],
                },
                "forbidden": ["food/backend/"],
            }
        ),
        encoding="utf-8",
    )
    (fixture_dir / "bilyeo-basic.json").write_text(
        json.dumps(
            {
                "id": "bilyeo-basic",
                "site": "bilyeo",
                "input": {
                    "analysis": {"framework": {"backend": "flask", "frontend": "vue"}},
                    "recommended_outputs": ["chat_auth"],
                },
                "expected": {
                    "proposed_files": ["files/backend/chat_auth.py"],
                    "proposed_patches": [],
                },
                "forbidden": ["bilyeo/backend/"],
            }
        ),
        encoding="utf-8",
    )

    seen_sites: list[str] = []
    role_runner = RoleRunner(
        responders={
            "Generator": lambda context: (
                seen_sites.append(context["site"]) or {
                    "claim": "Prepared overlay proposal",
                    "evidence": context["evidence"],
                    "confidence": 0.8,
                    "risk": "medium",
                    "next_action": "evaluate generated proposal",
                    "blocking_issue": "none",
                    "metadata": {
                        "proposed_files": ["files/backend/chat_auth.py"],
                        "proposed_patches": ["patches/frontend_widget_mount.patch"]
                        if context["site"] == "food"
                        else [],
                    },
                }
            )
        }
    )

    summary = run_generator_eval(
        fixture_dir=fixture_dir,
        role_runner=role_runner,
        report_path=report_path,
    )

    assert seen_sites == ["bilyeo", "food"]
    assert summary["total"] == 2
    assert summary["passed"] == 2
    assert summary["failed"] == 0
    assert summary["average_score"] == 1.0
    assert summary["failed_fixture_ids"] == []
    assert report_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["total"] == 2
    assert report["summary"]["average_score"] == 1.0
    assert report["results"][0]["id"] == "bilyeo-basic"
