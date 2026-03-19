import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.runtime_completion_runner import run_runtime_completion


def test_runtime_completion_runner_contract_writes_failure_artifacts(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-013"
    runtime_workspace = tmp_path / "runtime" / "food" / "food-run-013" / "workspace"

    (runtime_workspace / "backend").mkdir(parents=True)
    (runtime_workspace / "backend" / "manage.py").write_text("print('django')\n", encoding="utf-8")
    (runtime_workspace / "frontend" / "src").mkdir(parents=True)
    (runtime_workspace / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "name": "food-frontend",
                "scripts": {
                    "dev": "react-scripts start",
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_runtime_completion(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        site="food",
        run_id="food-run-013",
    )

    assert result["passed"] is False
    assert result["failure_reason"] == "runtime_server_probes_not_implemented"
    assert result["attempt_count"] == 1
    assert result["backend_probe"]["plan"]["framework"] == "django"
    assert result["backend_probe"]["plan"]["command"] == [
        "python",
        "manage.py",
        "runserver",
        "127.0.0.1:8000",
    ]
    assert result["frontend_probe"]["plan"]["package_manager"] == "npm"
    assert result["frontend_probe"]["plan"]["command"] == ["npm", "run", "dev"]

    completion_report = run_root / "reports" / "runtime-completion.json"
    server_probe_report = run_root / "reports" / "runtime-server-probes.json"
    completion_payload = json.loads(completion_report.read_text(encoding="utf-8"))
    probe_payload = json.loads(server_probe_report.read_text(encoding="utf-8"))

    assert completion_payload["failure_reason"] == "runtime_server_probes_not_implemented"
    assert completion_payload["attempt_count"] == 1
    assert probe_payload["backend"]["plan"]["framework"] == "django"
    assert probe_payload["frontend"]["plan"]["command"] == ["npm", "run", "dev"]
