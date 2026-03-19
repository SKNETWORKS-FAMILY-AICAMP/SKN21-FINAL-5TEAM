# Context-Aware Insertion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace filename-heavy patch target selection with content-aware indexing and Django-first insertion heuristics.

**Architecture:** Extend `codebase_mapper.py` to emit structured local evidence, then consume that evidence in `patch_planner.py` so target selection and patch insertion become context-aware. Keep generation deterministic and validate the new behavior through existing runtime merge simulation.

**Tech Stack:** Python, pytest, local JSON artifacts, unified diff generation

---

### Task 1: Expand Codebase Map Evidence

**Files:**
- Modify: `chatbot/src/onboarding/codebase_mapper.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

Add a test that expects `codebase-map.json` to include structured evidence fields for Django auth and url configuration targets.

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -k codebase_map -v`

**Step 3: Write minimal implementation**

Add fields such as:
- `auth_candidates`
- `urlconf_candidates`
- `frontend_component_candidates`

Populate them from file contents, not only filenames.

**Step 4: Run test to verify it passes**

Run the same pytest command and confirm PASS.

### Task 2: Replace Filename Buckets With Evidence-Based Target Selection

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

Add a test proving Django project-level `urls.py` and auth-related `views.py` are preferred over unrelated `orders` and `products` modules when both exist.

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -k patch_proposal -v`

**Step 3: Write minimal implementation**

Consume the new codebase-map evidence and select targets using:
- auth signal score
- `urlpatterns` presence
- project-level route preference
- frontend app-shell markers

**Step 4: Run test to verify it passes**

Run the same pytest command and confirm PASS.

### Task 3: Stabilize Unified Diff Draft Output

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

Add a regression that verifies `proposed.patch` only touches the narrowed context-aware targets for a Django site.

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -k unified_diff_draft -v`

**Step 3: Write minimal implementation**

Ensure patch generation uses the selected evidence-driven targets and does not fan out to unrelated modules.

**Step 4: Run test to verify it passes**

Run the same pytest command and confirm PASS.

### Task 4: Verify Merge Simulation Still Reaches Evaluation

**Files:**
- Modify: `chatbot/src/onboarding/runtime_runner.py` only if needed
- Test: `chatbot/tests/onboarding/test_agent_integration.py`
- Test: `chatbot/tests/onboarding/test_runtime_runner.py`

**Step 1: Run focused regression**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_agent_integration.py -k "merge_simulation or backend_evaluation_artifact or frontend_evaluation_artifact" -v`

**Step 2: Fix any failures minimally**

Only patch runtime logic if the new target selection changes merge behavior.

**Step 3: Re-run focused regression**

Run the same pytest command until PASS.

### Task 5: Full Verification

**Files:**
- Verify only

**Step 1: Run targeted onboarding regression**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py -v`

**Step 2: Run syntax verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/codebase_mapper.py chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/runtime_runner.py chatbot/src/onboarding/orchestrator.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_cli_runner.py`

**Step 3: Inspect artifact behavior**

Confirm:
- `codebase-map.json` contains structured evidence
- `patch-proposal.json` explains target choice
- `proposed.patch` stays narrow
- merge simulation reaches evaluation on representative Django runs
