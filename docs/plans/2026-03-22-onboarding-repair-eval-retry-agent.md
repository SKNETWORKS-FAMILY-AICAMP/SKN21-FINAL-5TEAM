# Onboarding Repair Eval Retry Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dual-loop onboarding repair system that retries run-scoped repairs first and promotes repeated failure signatures to generator fixes after the second recurrence.

**Architecture:** Extend the existing onboarding pipeline instead of replacing it. First, standardize failure signatures and persist repair history across runs. Second, separate run-scoped repair from generator-scoped repair. Third, add a promotion judge that escalates repeated pipeline bugs to `chatbot/src/onboarding` fixes and forces revalidation on a fresh run id.

**Tech Stack:** Python, pytest, JSON artifacts, existing onboarding orchestrator/recovery/runtime completion stack

---

### Task 1: Standardize Failure Signatures

**Files:**
- Modify: `chatbot/src/onboarding/failure_classifier.py`
- Modify: `chatbot/src/onboarding/frontend_evaluator.py`
- Modify: `chatbot/src/onboarding/runtime_completion_runner.py`
- Modify: `chatbot/src/onboarding/smoke_runner.py`
- Test: `chatbot/tests/onboarding/test_failure_classifier.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`
- Test: `chatbot/tests/onboarding/test_runtime_completion_runner.py`

**Step 1: Write the failing tests**

Add tests that assert repeated failure categories are normalized into stable signatures.

Examples:

```python
def test_classify_frontend_routes_child_violation_as_stable_signature():
    payload = classify_failure_signature(
        failure_reason="frontend_mount_violation",
        validation_errors=["routes child violation"],
    )
    assert payload["failure_signature"] == "frontend_mount_violation:routes_child_violation"
```

```python
def test_classify_invalid_llm_payload_structure_summary_type():
    payload = classify_failure_signature(
        failure_reason="invalid_llm_payload",
        validation_error="structure_summary Input should be a valid string",
    )
    assert payload["failure_signature"] == "codebase_interpretation:invalid_llm_payload.structure_summary_type"
```

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_failure_classifier.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_completion_runner.py -k "failure_signature or routes_child or structure_summary_type" -q
```

Expected: FAIL because stable signature output does not exist yet.

**Step 3: Implement minimal signature normalization**

Add helpers that:

- normalize stage/class/detail into one stable key
- map known validation errors to canonical details
- preserve raw evidence alongside the normalized signature

**Step 4: Run focused tests**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/failure_classifier.py chatbot/src/onboarding/frontend_evaluator.py chatbot/src/onboarding/runtime_completion_runner.py chatbot/src/onboarding/smoke_runner.py chatbot/tests/onboarding/test_failure_classifier.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_completion_runner.py
git commit -m "feat: standardize onboarding failure signatures"
```

### Task 2: Persist Run Repair History And Promotion Counters

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/run_resume.py`
- Create: `chatbot/src/onboarding/repair_history.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`
- Test: `chatbot/tests/onboarding/test_run_resume.py`

**Step 1: Write the failing tests**

Add tests for:

- writing a per-run repair history artifact
- incrementing a `site + failure_signature` counter
- distinguishing first failure from second recurrence

Example:

```python
def test_repair_history_counts_repeated_failure_signature(tmp_path: Path):
    record_failure_signature(...)
    record_failure_signature(...)
    history = load_repair_history(...)
    assert history["food"]["frontend_mount_violation:routes_child_violation"]["count"] == 2
```

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_run_resume.py -k "repair_history or repeated_failure_signature" -q
```

Expected: FAIL because no persistent repair history exists yet.

**Step 3: Implement repair history module**

Create `repair_history.py` with helpers to:

- append per-run attempt records
- load and update cumulative signature counters
- record `repair_scope`, `files_touched`, `evaluation_delta`, `promotion_decision`

Wire it into orchestrator after frontend/smoke/runtime completion failure classification.

**Step 4: Run focused tests**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/run_resume.py chatbot/src/onboarding/repair_history.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_run_resume.py
git commit -m "feat: persist onboarding repair history"
```

### Task 3: Separate Run-Level Repair From Generator Promotion

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Create: `chatbot/src/onboarding/promotion_judge.py`
- Modify: `chatbot/src/onboarding/recovery_planner.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`
- Test: `chatbot/tests/onboarding/test_recovery_planner.py`
- Test: `chatbot/tests/onboarding/test_promotion_judge.py`

**Step 1: Write the failing tests**

Add tests that assert:

- first occurrence of a failure signature stays `run_only`
- second occurrence promotes to `generator_promoted`
- site-local seam issues do not promote automatically

Example:

```python
def test_promotion_judge_promotes_on_second_repeat():
    judge = PromotionJudge(threshold=2)
    assert judge.decide(count=1, scope="run_only")["promote"] is False
    assert judge.decide(count=2, scope="run_only")["promote"] is True
```

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_promotion_judge.py chatbot/tests/onboarding/test_recovery_planner.py chatbot/tests/onboarding/test_orchestrator.py -k "promotion or generator_promoted or run_only" -q
```

Expected: FAIL because promotion logic does not exist yet.

**Step 3: Implement promotion judge**

Create `promotion_judge.py` with:

- recurrence threshold handling
- site-local vs pipeline-generalizable gating
- structured `promotion_decision`

Update orchestrator to:

- keep first failure in run repair loop
- emit promotion decision artifact on second recurrence
- route repeated pipeline bugs to generator repair path

**Step 4: Run focused tests**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/promotion_judge.py chatbot/src/onboarding/recovery_planner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_recovery_planner.py chatbot/tests/onboarding/test_promotion_judge.py
git commit -m "feat: add onboarding generator promotion judge"
```

### Task 4: Constrain Run Repair To Seam-Only Modifications

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/framework_strategies.py`
- Modify: `chatbot/src/onboarding/frontend_recovery.py`
- Modify: `chatbot/src/onboarding/exporter.py`
- Test: `chatbot/tests/onboarding/test_patch_planner.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`
- Test: `chatbot/tests/onboarding/test_exporter.py`

**Step 1: Write the failing tests**

Add tests that assert:

- run-level repair only touches auth seam, frontend mount seam, order bridge seam
- build artifacts like `frontend/build/static/js/main.*.js` are rejected as repair targets
- exporter does not re-export seam-external edits

Example:

```python
def test_run_repair_rejects_build_artifact_mount_target():
    decision = validate_repair_target("frontend/build/static/js/main.abc.js")
    assert decision["allowed"] is False
```

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_exporter.py -k "build_artifact or seam_only or seam_target" -q
```

Expected: FAIL because seam-only enforcement is incomplete.

**Step 3: Implement seam allowlist enforcement**

Update the relevant modules so run repair:

- only targets auth seam, frontend mount seam, order bridge seam
- rejects build outputs and non-source paths
- records explicit rejection reasons for disallowed targets

**Step 4: Run focused tests**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/framework_strategies.py chatbot/src/onboarding/frontend_recovery.py chatbot/src/onboarding/exporter.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_exporter.py
git commit -m "feat: restrict onboarding repair to seam targets"
```

### Task 5: Add Generator Repair Execution Path

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/role_runner.py`
- Modify: `chatbot/src/onboarding/generator_eval.py`
- Modify: `chatbot/src/onboarding/run_resume.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

Add tests that assert:

- when promotion triggers, the pipeline records `generator_promoted`
- generator repair path targets `chatbot/src/onboarding`
- post-promotion execution requires a fresh run id

Example:

```python
def test_promoted_generator_repair_requires_fresh_run_id(tmp_path: Path):
    result = run_promoted_repair(...)
    assert result["repair_scope"] == "generator_promoted"
    assert result["requires_fresh_run"] is True
```

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_orchestrator.py -k "generator_promoted or fresh_run_id or promoted_repair" -q
```

Expected: FAIL because generator promotion is not executable yet.

**Step 3: Implement generator repair path**

Update orchestrator and role execution so promoted failures:

- emit a generator repair work item
- scope file ownership to `chatbot/src/onboarding`
- force re-execution on a fresh run id rather than mutating prior run artifacts in place

**Step 4: Run focused tests**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/role_runner.py chatbot/src/onboarding/generator_eval.py chatbot/src/onboarding/run_resume.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: add onboarding generator repair path"
```

### Task 6: Verify End-To-End Loop Behavior

**Files:**
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`
- Reference: `generated/food/food-run-046/...`

**Step 1: Add end-to-end regression tests**

Cover at least these flows:

- first `frontend_mount_violation:routes_child_violation` => `run_only`
- second same signature => `generator_promoted`
- `codebase_interpretation:invalid_llm_payload.structure_summary_type` recovers without promotion
- build artifact mount target is rejected and classified as pipeline-generalizable

**Step 2: Run targeted end-to-end tests to verify they fail if wiring is incomplete**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_orchestrator.py -k "routes_child_violation or generator_promoted or structure_summary_type or build_artifact_selected" -q
```

Expected: PASS after prior tasks are complete.

**Step 3: Run a broader regression subset**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=test-key uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_agent_integration.py -k "failure_signature or promotion or run_only or generator_promoted or structure_summary_type or build_artifact or routes_child" -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "test: verify onboarding dual-loop repair flow"
```
