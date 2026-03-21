# LLM-First Onboarding Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Shift onboarding generation and repair to an LLM-first decision pipeline where deterministic logic acts only as safety guardrails.

**Architecture:** Keep the current dual-loop repair system, but invert control. LLM modules become the default path for target selection, repair strategy, and promotion recommendation. Deterministic modules remain only to reject unsafe targets, enforce seam ownership, require fresh runs after promotion, and validate patch application.

**Tech Stack:** Python, pytest, JSON artifacts, existing onboarding orchestrator/patch planner/runtime repair stack

---

### Task 1: Add Guardrail-Aware LLM Target Retry For Patch Proposals

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/framework_strategies.py`
- Test: `chatbot/tests/onboarding/test_patch_planner.py`

**Step 1: Write the failing tests**

Add tests that assert:
- an LLM-selected build artifact target is rejected with a structured rejection reason
- the rejection reason is fed into one retry attempt
- a second LLM response that chooses a source seam target is accepted

**Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_patch_planner.py -k "retry or build_artifact_target or rejection_reason" -q
```

Expected: FAIL because patch proposal retry-on-rejection does not exist.

**Step 3: Write minimal implementation**

Implement in `patch_planner.py`:
- `invalid seam target` rejection capture
- one retry path for `write_llm_first_patch_proposal(...)`
- debug artifact fields for `rejection_reason`, `retry_attempt_count`, `retry_source`

Keep `framework_strategies.py` as validator-only logic.

**Step 4: Run test to verify it passes**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/framework_strategies.py chatbot/tests/onboarding/test_patch_planner.py
git commit -m "feat: retry llm patch proposals after guardrail rejection"
```

### Task 2: Make LLM Decide Frontend Mount Insertion Strategy

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/frontend_recovery.py`
- Test: `chatbot/tests/onboarding/test_patch_planner.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`

**Step 1: Write the failing tests**

Add tests that assert:
- an LLM proposal can specify `mount_context = outside_routes`
- `<Routes>` child insertion is rejected
- a retry can produce a valid mount placement outside `<Routes>`

**Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_frontend_evaluator.py -k "routes_child or mount_context or outside_routes" -q
```

Expected: FAIL because mount-context-aware retry does not exist.

**Step 3: Write minimal implementation**

Update patch planning so LLM output can carry:
- `mount_context`
- `insertion_anchor`
- `rejection_reason`

Update frontend recovery to treat invalid mount context as a retryable planning issue, not only a hard fallback.

**Step 4: Run test to verify it passes**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/frontend_recovery.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_frontend_evaluator.py
git commit -m "feat: let llm choose safe frontend mount context"
```

### Task 3: Replace Rule-First Recovery Planning With LLM Repair Recommendations

**Files:**
- Modify: `chatbot/src/onboarding/recovery_planner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/role_runner.py`
- Test: `chatbot/tests/onboarding/test_recovery_planner.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

Add tests that assert:
- repair planning accepts an LLM recommendation payload
- deterministic recovery classification is used only when LLM recommendation is absent or invalid
- rejection reasons from guardrails are recorded in the repair artifact

**Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_recovery_planner.py chatbot/tests/onboarding/test_orchestrator.py -k "llm_repair_recommendation or guardrail_rejection or repair_scope" -q
```

Expected: FAIL because recovery is still rule-first.

**Step 3: Write minimal implementation**

Implement:
- `LLM repair recommendation` normalization in `recovery_planner.py`
- orchestrator wiring that prefers recommendation payloads over built-in classification
- role prompt updates so Diagnostician emits structured repair recommendations

**Step 4: Run test to verify it passes**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/recovery_planner.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/role_runner.py chatbot/tests/onboarding/test_recovery_planner.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: prefer llm repair recommendations in recovery planning"
```

### Task 4: Make Promotion Recommendation LLM-First, Gate Deterministic

**Files:**
- Modify: `chatbot/src/onboarding/promotion_judge.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/repair_history.py`
- Test: `chatbot/tests/onboarding/test_promotion_judge.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

Add tests that assert:
- LLM can recommend `generator_promoted`
- deterministic gate still blocks promotion below threshold
- deterministic gate still blocks site-local signatures even if LLM recommends promotion

**Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_promotion_judge.py chatbot/tests/onboarding/test_orchestrator.py -k "llm_recommendation or below_threshold or site_local" -q
```

Expected: FAIL because promotion judge does not consume LLM recommendation yet.

**Step 3: Write minimal implementation**

Change `promotion_judge.py` so it:
- accepts `recommendation_scope`
- only decides gate outcome
- records why a recommendation was denied

Wire `orchestrator.py` and `repair_history.py` to persist both recommendation and gate result.

**Step 4: Run test to verify it passes**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/promotion_judge.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/repair_history.py chatbot/tests/onboarding/test_promotion_judge.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: gate llm promotion recommendations deterministically"
```

### Task 5: Expand Runtime LLM Repair Beyond Import Errors

**Files:**
- Modify: `chatbot/src/onboarding/runtime_llm_repair.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`
- Test: `chatbot/tests/onboarding/test_runtime_completion_runner.py`

**Step 1: Write the failing tests**

Add tests that assert:
- runtime LLM repair can react to mount/router/auth-bootstrap evidence, not only Python import tracebacks
- runtime LLM repair runs before canned deterministic repair actions for those failures
- failed runtime LLM repair leaves explicit rejection metadata

**Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=test-key uv run pytest chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_runtime_completion_runner.py -k "runtime_llm_repair or mount_probe or auth_bootstrap" -q
```

Expected: FAIL because runtime LLM repair is import-focused today.

**Step 3: Write minimal implementation**

Extend runtime repair so it:
- reads broader evidence payloads
- builds candidate files from frontend/backend runtime failures
- records `llm_repair_applied`, `llm_repair_failure_reason`, and `guardrail_rejection_reason`

**Step 4: Run test to verify it passes**

Run the same command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_llm_repair.py chatbot/src/onboarding/orchestrator.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_runtime_completion_runner.py
git commit -m "feat: extend llm runtime repair to frontend and auth failures"
```

### Task 6: Verify LLM-First End-To-End Behavior

**Files:**
- Modify: `chatbot/tests/onboarding/test_codebase_mapper.py`
- Modify: `chatbot/tests/onboarding/test_patch_planner.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Add end-to-end regression tests**

Cover at least:
- build artifact target gets rejected, then LLM retry converges to `frontend/src/App.js`
- first `frontend_mount_violation:routes_child_violation` stays `run_only`
- second same signature becomes `generator_promoted` only after threshold gate
- `structure_summary_type` recovers as `recovered_llm` without promotion

**Step 2: Run targeted tests to verify behavior**

Run:
```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=test-key uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_agent_integration.py -k "llm_first or build_artifact_selected or routes_child_violation or generator_promoted or structure_summary_type" -q
```

Expected: PASS.

**Step 3: Run broader regression subset**

Run:
```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=test-key uv run pytest chatbot/tests/onboarding/test_failure_classifier.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_smoke_summary.py chatbot/tests/onboarding/test_run_resume.py chatbot/tests/onboarding/test_recovery_planner.py chatbot/tests/onboarding/test_promotion_judge.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_exporter.py chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_agent_integration.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "test: verify llm-first onboarding repair flow"
```
