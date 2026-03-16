import json
import subprocess
import sys
from pathlib import Path


def test_generator_eval_cli_runs_and_writes_report(tmp_path: Path):
    fixture_dir = tmp_path / "fixtures"
    report_path = tmp_path / "reports" / "generator-eval.json"
    fixture_dir.mkdir()

    (fixture_dir / "food-basic.json").write_text(
        json.dumps(
            {
                "id": "food-basic",
                "site": "food",
                "input": {
                    "analysis": {"framework": {"backend": "django", "frontend": "react"}},
                    "recommended_outputs": [
                        "chat_auth",
                        "order_adapter",
                        "product_adapter",
                        "frontend_patch",
                    ],
                },
                "expected": {
                    "proposed_files": [
                        "files/backend/chat_auth.py",
                        "files/backend/order_adapter_client.py",
                        "files/backend/product_adapter_client.py",
                    ],
                    "proposed_patches": [
                        "patches/frontend_widget_mount.patch",
                    ],
                },
                "forbidden": ["food/backend/"],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "chatbot/scripts/run_generator_eval.py",
            "--fixture-dir",
            str(fixture_dir),
            "--report-path",
            str(report_path),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "average_score": 1.0,
        "failed_fixture_ids": [],
        "score_distribution": {"1.0": 1},
    }
    assert report_path.exists()
