# Onboarding Reliability Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 범용 온보딩 agent MVP의 실행 신뢰도를 높여, 생성 결과와 검증 결과를 데모 수준이 아니라 반복 실행 가능한 검증 파이프라인 수준으로 끌어올린다.

**Architecture:** 기존 `run_onboarding_generation()` 흐름을 유지하면서, `smoke_runner`를 계약 기반 실행기로 강화하고 `generator_eval`과 golden fixture를 확장한다. 이후 `orchestrator`의 diagnostician retry 루프에 실패 분류와 재시도 정책을 추가하고, 마지막으로 Slack/PR 연동을 실제 외부 시스템이 없어도 검증 가능한 exporter/bridge 계약까지 확장한다.

**Tech Stack:** Python, pytest, subprocess, pydantic, JSON fixtures, shell smoke scripts

---

### Task 1: Harden Smoke Contract and Runner

**Files:**
- Modify: `chatbot/src/onboarding/smoke_contract.py`
- Modify: `chatbot/src/onboarding/smoke_runner.py`
- Modify: `chatbot/src/onboarding/overlay_generator.py`
- Test: `chatbot/tests/onboarding/test_smoke_runner.py`
- Test: `chatbot/tests/onboarding/test_overlay_generator.py`

**Step 1: Write the failing test**

추가할 테스트:

```python
def test_load_smoke_plan_reads_step_metadata(tmp_path: Path):
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "tests": {
                    "smoke": [
                        {
                            "id": "chat-auth",
                            "script": "smoke-tests/chat_auth_token.sh",
                            "env": {"EXPECTED_STATUS": "200"},
                            "timeout_seconds": 5,
                            "required": True,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    plan = load_smoke_plan(run_root)

    assert plan.steps[0].id == "chat-auth"
    assert plan.steps[0].env == {"EXPECTED_STATUS": "200"}
```

```python
def test_run_smoke_tests_includes_timeout_and_env(tmp_path: Path):
    results = run_smoke_tests(
        run_root=run_root,
        runtime_workspace=workspace,
        plan=SmokeTestPlan(
            steps=[
                SmokeTestStep(
                    id="login",
                    script="smoke-tests/login.sh",
                    env={"EXPECTED_VALUE": "ok"},
                    timeout_seconds=1,
                    required=True,
                )
            ]
        ),
    )

    assert results[0]["step_id"] == "login"
    assert results[0]["timed_out"] is False
    assert results[0]["stdout"].strip() == "ok"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_overlay_generator.py -v`
Expected: FAIL because smoke plan currently only supports bare string paths

**Step 3: Write minimal implementation**

구현 내용:

- `SmokeTestStep` 모델 추가: `id`, `script`, `env`, `timeout_seconds`, `required`, `category`
- `SmokeTestPlan.steps`를 `list[SmokeTestStep]`로 변경하되, 기존 string manifest도 backward compatible 하게 허용
- `run_smoke_tests()` 결과에 `step_id`, `timed_out`, `required`, `category` 포함
- `subprocess.run(..., timeout=...)` 적용
- overlay scaffold 생성 시 기본 smoke step을 metadata 객체 형태로 기록

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_overlay_generator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/smoke_contract.py chatbot/src/onboarding/smoke_runner.py chatbot/src/onboarding/overlay_generator.py chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_overlay_generator.py
git commit -m "chatbot: harden onboarding smoke runner contract"
```

### Task 2: Add Smoke Result Classification and Summary Report

**Files:**
- Modify: `chatbot/src/onboarding/smoke_runner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Create: `chatbot/tests/onboarding/test_smoke_summary.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing test**

추가할 테스트:

```python
def test_summarize_smoke_results_counts_required_failures():
    summary = summarize_smoke_results(
        [
            {"step_id": "login", "returncode": 0, "required": True, "timed_out": False},
            {"step_id": "product", "returncode": 1, "required": True, "timed_out": False},
            {"step_id": "order", "returncode": 124, "required": False, "timed_out": True},
        ]
    )

    assert summary["passed"] is False
    assert summary["required_failures"] == ["product"]
    assert summary["optional_failures"] == ["order"]
```

```python
def test_orchestrator_writes_smoke_summary_report(tmp_path: Path):
    result = run_onboarding_generation(...)

    summary = json.loads((run_root / "reports" / "smoke-summary.json").read_text(encoding="utf-8"))
    assert summary["total_steps"] >= 1
    assert "required_failures" in summary
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_smoke_summary.py chatbot/tests/onboarding/test_orchestrator.py -v`
Expected: FAIL because there is no smoke summary helper or report file

**Step 3: Write minimal implementation**

구현 내용:

- `summarize_smoke_results(results)` helper 추가
- 실패를 `required_failures`, `optional_failures`, `missing_scripts`, `timed_out_steps`로 구분
- orchestrator가 `reports/smoke-summary.json`을 기록하도록 추가
- validator evidence에 summary 정보를 포함해 diagnostician 입력을 더 구조화

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_smoke_summary.py chatbot/tests/onboarding/test_orchestrator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/smoke_runner.py chatbot/src/onboarding/orchestrator.py chatbot/tests/onboarding/test_smoke_summary.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "chatbot: add smoke summary reporting"
```

### Task 3: Expand Generator Eval Rubric With Scored Checks

**Files:**
- Modify: `chatbot/src/onboarding/generator_eval.py`
- Modify: `chatbot/scripts/run_generator_eval.py`
- Modify: `chatbot/tests/onboarding/test_generator_rubric.py`
- Modify: `chatbot/tests/onboarding/test_generator_eval_runner.py`
- Modify: `chatbot/tests/onboarding/test_generator_eval_cli.py`

**Step 1: Write the failing test**

추가할 테스트:

```python
def test_evaluate_generator_proposal_returns_category_scores():
    result = evaluate_generator_proposal(
        fixture,
        proposed_files=["files/backend/chat_auth.py"],
        proposed_patches=["patches/frontend_widget_mount.patch"],
    )

    assert result.score == 0.75
    assert result.checks["required_files"] is True
    assert result.checks["forbidden_paths"] is True
    assert result.checks["required_patches"] is False
```

```python
def test_run_generator_eval_summary_includes_score_breakdown(tmp_path: Path):
    summary = run_generator_eval(...)
    assert "average_score" in summary
    assert summary["passed"] == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_rubric.py chatbot/tests/onboarding/test_generator_eval_runner.py chatbot/tests/onboarding/test_generator_eval_cli.py -v`
Expected: FAIL because eval currently returns only pass/fail deltas

**Step 3: Write minimal implementation**

구현 내용:

- `GeneratorEvalResult`에 `score`, `checks`, `notes` 추가
- 평가 기준을 최소 4개 카테고리로 분리
  - required files
  - required patches
  - no extra artifacts
  - no forbidden hits
- summary에 `average_score`, `failed_fixture_ids`, `score_distribution` 추가
- CLI stdout과 report JSON이 확장 필드를 그대로 내보내게 수정

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_rubric.py chatbot/tests/onboarding/test_generator_eval_runner.py chatbot/tests/onboarding/test_generator_eval_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/generator_eval.py chatbot/scripts/run_generator_eval.py chatbot/tests/onboarding/test_generator_rubric.py chatbot/tests/onboarding/test_generator_eval_runner.py chatbot/tests/onboarding/test_generator_eval_cli.py
git commit -m "chatbot: add scored generator eval rubric"
```

### Task 4: Grow Golden Fixture Coverage for Generator Quality

**Files:**
- Create: `chatbot/tests/onboarding/goldens/generator/django-template-only.json`
- Create: `chatbot/tests/onboarding/goldens/generator/fastapi-react-token-auth.json`
- Create: `chatbot/tests/onboarding/goldens/generator/spring-thymeleaf-basic.json`
- Modify: `chatbot/tests/onboarding/test_generator_golden_fixtures.py`
- Modify: `chatbot/tests/onboarding/test_generator_golden_regression.py`

**Step 1: Write the failing test**

추가할 테스트:

```python
def test_generator_golden_fixture_count_is_at_least_six():
    fixtures = load_generator_eval_fixtures(fixture_dir)
    assert len(fixtures) >= 6
```

```python
def test_generator_golden_regression_reports_failed_fixture_ids():
    payload = run_generator_eval(...)
    assert "failed_fixture_ids" in payload
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_generator_golden_regression.py -v`
Expected: FAIL because fixture count and regression summary are too small

**Step 3: Write minimal implementation**

구현 내용:

- golden fixture를 최소 3개 추가해서 backend/frontend/auth 조합 다양화
- fixture notes에 왜 해당 산출물이 필요한지 한 줄 근거 명시
- regression test가 fixture id 단위로 실패를 출력하도록 assertion 강화

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_generator_golden_regression.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding/goldens/generator chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_generator_golden_regression.py
git commit -m "chatbot: expand onboarding generator golden coverage"
```

### Task 5: Stabilize Diagnostician Retry Policy

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/role_runner.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`
- Create: `chatbot/tests/onboarding/test_retry_policy.py`

**Step 1: Write the failing test**

추가할 테스트:

```python
def test_retry_policy_does_not_retry_missing_script_failure(tmp_path: Path):
    results = _run_validation_with_retries(...)
    assert agent.retry_count == 0
```

```python
def test_retry_policy_retries_transient_failure_once(tmp_path: Path):
    results = _run_validation_with_retries(...)
    assert agent.retry_count == 1
    assert results[-1]["returncode"] == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_retry_policy.py chatbot/tests/onboarding/test_orchestrator.py -v`
Expected: FAIL because retry logic currently only checks `retry_budget`

**Step 3: Write minimal implementation**

구현 내용:

- smoke summary 기반 `failure_signature` 계산 helper 추가
- missing script, patch apply failure, auth contract mismatch 같은 구조적 실패는 즉시 human review
- timeout, flaky command, temporary non-zero 같은 일시 실패만 retry 허용
- diagnostician evidence에 `failure_signature`, `timed_out_steps`, `missing_scripts`, `required_failures` 포함

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_retry_policy.py chatbot/tests/onboarding/test_orchestrator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/role_runner.py chatbot/tests/onboarding/test_retry_policy.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "chatbot: stabilize diagnostician retry policy"
```

### Task 6: Persist Retry Evidence for Human Review

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

추가할 테스트:

```python
def test_failed_retry_writes_diagnostic_report(tmp_path: Path):
    result = run_onboarding_generation(...)
    report = json.loads((run_root / "reports" / "diagnostic-report.json").read_text(encoding="utf-8"))
    assert report["final_action"] == "request_human_review"
```

```python
def test_slack_bridge_message_includes_retry_context():
    event = bridge.events[-1]
    assert "failure_signature" in event["message"]["evidence"][0]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_agent_integration.py -v`
Expected: FAIL because diagnostic evidence is not persisted as a dedicated report

**Step 3: Write minimal implementation**

구현 내용:

- `reports/diagnostic-report.json` 생성
- retry 시도 횟수, 최종 실패 분류, human review 필요 이유 저장
- Slack bridge 이벤트 payload에 진단 근거 요약 추가

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_agent_integration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "chatbot: persist onboarding diagnostic evidence"
```

### Task 7: Add Approval Event Contract for Real Slack/PR Integration

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/src/onboarding/exporter.py`
- Modify: `chatbot/src/onboarding/agent_contracts.py`
- Create: `chatbot/tests/onboarding/test_export_approval_contract.py`
- Modify: `chatbot/tests/onboarding/test_exporter.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing test**

추가할 테스트:

```python
def test_export_report_contains_pr_metadata_placeholders(tmp_path: Path):
    export_overlay_patch(...)
    metadata = json.loads((reports_root / "export-metadata.json").read_text(encoding="utf-8"))
    assert metadata["pr"]["title"]
    assert metadata["pr"]["body"]
    assert metadata["pr"]["head_branch"]
```

```python
def test_slack_bridge_can_record_export_approval_decision():
    bridge.record_approval_decision(run_id="food-run-001", approval_type="export", decision="approve")
    assert bridge.approval_log[-1]["approval_type"] == "export"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_export_approval_contract.py chatbot/tests/onboarding/test_exporter.py chatbot/tests/onboarding/test_slack_bridge.py -v`
Expected: FAIL because export metadata and approval event contract are too thin

**Step 3: Write minimal implementation**

구현 내용:

- exporter metadata에 PR 제목/본문/head branch placeholder 추가
- Slack bridge에 approval decision 기록용 메모리 계약 추가
- agent contract에 export approval event schema 보강
- 실제 GitHub/Slack API 호출은 하지 않고, 다음 단계 연동에 필요한 payload만 표준화

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_export_approval_contract.py chatbot/tests/onboarding/test_exporter.py chatbot/tests/onboarding/test_slack_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/slack_bridge.py chatbot/src/onboarding/exporter.py chatbot/src/onboarding/agent_contracts.py chatbot/tests/onboarding/test_export_approval_contract.py chatbot/tests/onboarding/test_exporter.py chatbot/tests/onboarding/test_slack_bridge.py
git commit -m "chatbot: define approval contract for export handoff"
```

### Task 8: Add End-to-End Reliability CLI Snapshot

**Files:**
- Modify: `chatbot/scripts/run_onboarding_generation.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`
- Create: `docs/plans/2026-03-15-onboarding-reliability-checklist.md`

**Step 1: Write the failing test**

추가할 테스트:

```python
def test_cli_runner_can_emit_report_paths(tmp_path: Path):
    result = subprocess.run([... "--print-report-paths"], ...)
    payload = json.loads(result.stdout)
    assert "smoke_summary_path" in payload
    assert "diagnostic_report_path" in payload
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: FAIL because CLI currently returns only run root and runtime workspace

**Step 3: Write minimal implementation**

구현 내용:

- CLI에 `--print-report-paths` 옵션 추가
- orchestrator 결과에 `smoke_summary_path`, `diagnostic_report_path`, `export_metadata_path` 노출
- 체크리스트 문서에 데모 전 검증 순서 기록

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/scripts/run_onboarding_generation.py chatbot/tests/onboarding/test_cli_runner.py docs/plans/2026-03-15-onboarding-reliability-checklist.md
git commit -m "chatbot: expose onboarding reliability reports in cli"
```
