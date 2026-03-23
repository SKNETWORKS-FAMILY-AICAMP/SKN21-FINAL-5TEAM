from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .role_runner import RoleRunner


class GeneratorEvalInput(BaseModel):
    analysis: dict[str, Any]
    recommended_outputs: list[str]

    model_config = ConfigDict(extra="forbid")


class GeneratorEvalExpected(BaseModel):
    proposed_files: list[str]
    proposed_patches: list[str]
    target_paths: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class GeneratorEvalFixture(BaseModel):
    id: str
    site: str
    input: GeneratorEvalInput
    expected: GeneratorEvalExpected
    forbidden: list[str]
    notes: str | None = None

    model_config = ConfigDict(extra="forbid")


class GeneratorEvalResult(BaseModel):
    id: str
    site: str
    passed: bool
    score: float
    checks: dict[str, bool]
    missing_files: list[str]
    extra_files: list[str]
    missing_patches: list[str]
    extra_patches: list[str]
    missing_targets: list[str]
    extra_targets: list[str]
    forbidden_hits: list[str]
    actual: dict[str, list[str]]

    model_config = ConfigDict(extra="forbid")


def load_generator_eval_fixture(path: str | Path) -> GeneratorEvalFixture:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return GeneratorEvalFixture.model_validate(payload)


def load_generator_eval_fixtures(fixture_dir: str | Path) -> list[GeneratorEvalFixture]:
    root = Path(fixture_dir)
    return [load_generator_eval_fixture(path) for path in sorted(root.glob("*.json"))]


def evaluate_generator_proposal(
    fixture: GeneratorEvalFixture,
    *,
    proposed_files: list[str],
    proposed_patches: list[str],
    target_paths: list[str] | None = None,
) -> GeneratorEvalResult:
    expected_files = fixture.expected.proposed_files
    expected_patches = fixture.expected.proposed_patches
    expected_targets = fixture.expected.target_paths
    actual_targets = list(target_paths or [])

    missing_files = [item for item in expected_files if item not in proposed_files]
    extra_files = [item for item in proposed_files if item not in expected_files]
    missing_patches = [item for item in expected_patches if item not in proposed_patches]
    extra_patches = [item for item in proposed_patches if item not in expected_patches]
    missing_targets = [item for item in expected_targets if item not in actual_targets]
    extra_targets = [item for item in actual_targets if item not in expected_targets]

    forbidden_hits = [
        item
        for item in [*proposed_files, *proposed_patches, *actual_targets]
        if any(token in item for token in fixture.forbidden)
    ]

    checks = {
        "required_files": len(missing_files) == 0,
        "required_patches": len(missing_patches) == 0,
        "no_extra_artifacts": len(extra_files) == 0 and len(extra_patches) == 0,
        "no_forbidden_hits": len(forbidden_hits) == 0,
    }
    score = sum(1 for passed in checks.values() if passed) / len(checks)

    return GeneratorEvalResult(
        id=fixture.id,
        site=fixture.site,
        passed=not any([missing_files, extra_files, missing_patches, extra_patches, forbidden_hits]),
        score=score,
        checks=checks,
        missing_files=missing_files,
        extra_files=extra_files,
        missing_patches=missing_patches,
        extra_patches=extra_patches,
        missing_targets=missing_targets,
        extra_targets=extra_targets,
        forbidden_hits=forbidden_hits,
        actual={
            "proposed_files": proposed_files,
            "proposed_patches": proposed_patches,
            "target_paths": actual_targets,
        },
    )


def run_generator_eval(
    *,
    fixture_dir: str | Path,
    role_runner: RoleRunner,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    fixtures = load_generator_eval_fixtures(fixture_dir)
    results: list[GeneratorEvalResult] = []

    for fixture in fixtures:
        context = {
            "site": fixture.site,
            "analysis": fixture.input.analysis,
            "recommended_outputs": fixture.input.recommended_outputs,
            "evidence": _build_generator_eval_evidence(fixture),
        }
        message = role_runner.run_role("Generator", context)
        results.append(
            evaluate_generator_proposal(
                fixture,
                proposed_files=list(message.metadata.get("proposed_files") or []),
                proposed_patches=list(message.metadata.get("proposed_patches") or []),
                target_paths=list(message.metadata.get("target_paths") or []),
            )
        )

    summary = {
        "total": len(results),
        "passed": sum(1 for result in results if result.passed),
        "failed": sum(1 for result in results if not result.passed),
        "average_score": (
            sum(result.score for result in results) / len(results)
            if results
            else 0.0
        ),
        "failed_fixture_ids": [result.id for result in results if not result.passed],
        "score_distribution": _build_score_distribution(results),
    }
    payload = {
        "summary": summary,
        "results": [result.model_dump() for result in results],
    }

    if report_path is not None:
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return summary


def _build_score_distribution(results: list[GeneratorEvalResult]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for result in results:
        key = f"{result.score:.1f}"
        distribution[key] = distribution.get(key, 0) + 1
    return distribution


def _build_generator_eval_evidence(fixture: GeneratorEvalFixture) -> list[str]:
    framework = fixture.input.analysis.get("framework", {})
    auth = fixture.input.analysis.get("auth", {})
    product_api = fixture.input.analysis.get("product_api", [])
    order_api = fixture.input.analysis.get("order_api", [])
    frontend_mount_points = fixture.input.analysis.get("frontend_mount_points", [])
    return [
        f"site: {fixture.site}",
        f"backend framework: {framework.get('backend', 'unknown')}",
        f"frontend framework: {framework.get('frontend', 'unknown')}",
        f"auth style: {auth.get('auth_style', 'unknown')}",
        f"recommended outputs: {fixture.input.recommended_outputs}",
        f"product api candidates: {product_api}",
        f"order api candidates: {order_api}",
        f"frontend mount points: {frontend_mount_points}",
    ]
