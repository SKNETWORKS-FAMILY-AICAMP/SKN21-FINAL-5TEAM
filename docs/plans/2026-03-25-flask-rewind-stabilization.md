# Flask Wiring And Repair Rewind Stabilization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stabilize Flask backend wiring generation and make repair rewind stage selection deterministic from override footprint instead of trusting the LLM response.

**Architecture:** Add focused compiler helpers in the Flask strategy to parse the auth contract path, generate blueprint-relative routes, and insert blueprint registration only for supported factory or module-level app patterns. Move rewind stage derivation into the engine, keep the LLM `rewind_to` as an advisory request, and emit both requested and effective rewind metadata in repair artifacts, events, and debug records.

**Tech Stack:** Python, pytest, Pydantic, Flask strategy compiler, onboarding_v2 engine/repair pipeline

---

### Task 1: Flask Wiring Regression Tests

**Files:**
- Modify: `chatbot/tests/onboarding_v2/test_compiler.py`
- Test: `chatbot/tests/onboarding_v2/test_compiler.py`

**Step 1: Write the failing tests**

Add tests that assert:
- factory pattern inserts blueprint import and registration inside `create_app()`
- module-level app pattern inserts registration after `app = Flask(...)`
- generated handler path is `backend/chat_auth.py`
- generated route is only `"/auth-token"` and blueprint registration uses `/api/chat`
- unsupported Flask wiring raises a compile failure

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_compiler.py -q -ra`
Expected: FAIL in the new Flask tests because current compiler appends raw text and uses absolute blueprint route

**Step 3: Write minimal implementation**

Update the Flask compiler and planner default path logic to satisfy the new tests.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_compiler.py -q -ra`
Expected: PASS

### Task 2: Effective Rewind Regression Tests

**Files:**
- Modify: `chatbot/tests/onboarding_v2/test_repair.py`
- Modify: `chatbot/tests/onboarding_v2/test_engine_entry.py`
- Test: `chatbot/tests/onboarding_v2/test_repair.py`
- Test: `chatbot/tests/onboarding_v2/test_engine_entry.py`

**Step 1: Write the failing tests**

Add tests that assert:
- engine derives `compile` when compile overrides exist even if LLM requests `validation`
- engine derives `planning` and `analysis` for earlier override footprints
- repair artifact payload and events include both `requested_rewind_to` and `effective_rewind_to`
- `latest_rewind_to` reflects the effective stage

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_repair.py chatbot/tests/onboarding_v2/test_engine_entry.py -q -ra`
Expected: FAIL because engine currently uses `decision.rewind_to` directly

**Step 3: Write minimal implementation**

Update engine rewind derivation and emitted metadata without changing the advisory meaning of `RepairDecision.rewind_to`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_repair.py chatbot/tests/onboarding_v2/test_engine_entry.py -q -ra`
Expected: PASS

### Task 3: Final Regression Sweep

**Files:**
- Modify: `chatbot/src/onboarding_v2/compile/strategies/backend/flask.py`
- Modify: `chatbot/src/onboarding_v2/planning/planner.py`
- Modify: `chatbot/src/onboarding_v2/engine.py`
- Modify: `chatbot/src/onboarding_v2/models/common.py`
- Modify: `chatbot/src/onboarding_v2/repair/diagnosis.py`

**Step 1: Run focused regression suite**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_repair.py chatbot/tests/onboarding_v2/test_engine_entry.py -q -ra`

**Step 2: Fix any remaining mismatches**

Keep changes scoped to Flask compiler support and deterministic rewind metadata.

**Step 3: Re-run focused regression suite**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_repair.py chatbot/tests/onboarding_v2/test_engine_entry.py -q -ra`
Expected: PASS
