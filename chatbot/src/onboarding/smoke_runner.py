from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .smoke_contract import SmokeTestPlan, SmokeTestStep


def load_smoke_plan(run_root: str | Path) -> SmokeTestPlan:
    root = Path(run_root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    tests = manifest.get("tests") or {}
    raw_steps = list(tests.get("smoke") or [])
    steps: list[SmokeTestStep] = []
    for item in raw_steps:
        if isinstance(item, str):
            step_id = Path(item).stem.replace("_", "-")
            steps.append(SmokeTestStep(id=step_id, script=item))
            continue
        steps.append(SmokeTestStep.model_validate(item))
    return SmokeTestPlan(steps=steps)


def run_smoke_tests(
    *,
    run_root: str | Path,
    runtime_workspace: str | Path,
    plan: SmokeTestPlan,
) -> list[dict]:
    root = Path(run_root)
    workspace = Path(runtime_workspace)
    results: list[dict] = []

    for step in plan.steps:
        script_path = (root / step.script).resolve()
        if not script_path.exists():
            results.append(
                {
                    "step": step.script,
                    "step_id": step.id,
                    "required": step.required,
                    "category": step.category,
                    "timed_out": False,
                    "returncode": 127,
                    "stdout": "",
                    "stderr": f"Smoke script not found: {script_path}",
                }
            )
            continue

        try:
            proc = subprocess.run(
                [str(script_path)],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
                timeout=step.timeout_seconds,
                env={**os.environ, **step.env},
            )
            returncode = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            timed_out = True
        results.append(
            {
                "step": step.script,
                "step_id": step.id,
                "required": step.required,
                "category": step.category,
                "timed_out": timed_out,
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        )

    return results


def summarize_smoke_results(results: list[dict]) -> dict:
    failures = [result for result in results if result.get("returncode") != 0]
    required_failures = [
        result.get("step_id") or result.get("step")
        for result in failures
        if result.get("required", True)
    ]
    optional_failures = [
        result.get("step_id") or result.get("step")
        for result in failures
        if not result.get("required", True)
    ]
    timed_out_steps = [
        result.get("step_id") or result.get("step")
        for result in failures
        if result.get("timed_out") is True
    ]
    missing_scripts = [
        result.get("step_id") or result.get("step")
        for result in failures
        if "Smoke script not found:" in (result.get("stderr") or "")
    ]

    return {
        "passed": len(required_failures) == 0,
        "total_steps": len(results),
        "failure_count": len(failures),
        "required_failures": required_failures,
        "optional_failures": optional_failures,
        "timed_out_steps": timed_out_steps,
        "missing_scripts": missing_scripts,
    }
