# Onboarding V2 LLM Cost Summary Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add cost estimation to `onboarding_v2` LLM usage tracking and expose the final summary as a stable artifact and engine result field.

**Architecture:** `llm_runtime.py` will normalize richer token metadata, `LlmUsageStore` will aggregate call-level usage into a summary with pricing-aware cost estimates, and `engine.py` will materialize that summary as a final export artifact. This keeps append-time bookkeeping in one place and avoids spreading cost math across stages.

**Tech Stack:** Python, Pydantic, pytest, existing onboarding v2 artifact/debug stores

---

### Task 1: Add failing tests for usage summary persistence

**Files:**
- Modify: `chatbot/tests/onboarding_v2/test_storage.py`
- Test: `chatbot/tests/onboarding_v2/test_storage.py`

**Step 1: Write the failing test**

Add a test that appends one LLM usage record and asserts the summary file includes token totals, pricing metadata, and `estimated_total_cost_usd`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_storage.py -q`
Expected: FAIL because `LlmUsageStore` does not yet write a summary or cost fields.

**Step 3: Write minimal implementation**

Update `chatbot/src/onboarding_v2/storage/llm_usage_store.py` to maintain a summary JSON with cost estimates and pricing metadata.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_storage.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding_v2/test_storage.py chatbot/src/onboarding_v2/storage/llm_usage_store.py
git commit -m "feat: summarize onboarding v2 llm usage costs"
```

### Task 2: Add failing test for final artifact exposure

**Files:**
- Modify: `chatbot/tests/onboarding_v2/test_engine_entry.py`
- Test: `chatbot/tests/onboarding_v2/test_engine_entry.py`

**Step 1: Write the failing test**

Add an engine entry test that runs a successful v2 flow with LLM usage records and asserts:
- the engine result contains a `latest_llm_usage_artifact` path
- the artifact JSON payload includes a final total cost

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_engine_entry.py -q`
Expected: FAIL because the engine does not create or return a usage summary artifact.

**Step 3: Write minimal implementation**

Update `chatbot/src/onboarding_v2/llm_runtime.py` and `chatbot/src/onboarding_v2/engine.py` to extract cached prompt usage, build the final summary artifact, and return its path.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_engine_entry.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/src/onboarding_v2/llm_runtime.py chatbot/src/onboarding_v2/engine.py
git commit -m "feat: publish onboarding v2 llm cost artifact"
```

### Task 3: Run focused verification

**Files:**
- Test: `chatbot/tests/onboarding_v2/test_storage.py`
- Test: `chatbot/tests/onboarding_v2/test_engine_entry.py`

**Step 1: Run focused verification**

Run: `uv run pytest chatbot/tests/onboarding_v2/test_storage.py chatbot/tests/onboarding_v2/test_engine_entry.py -q`
Expected: PASS with the new cost summary behavior covered.

**Step 2: Commit**

```bash
git add docs/plans/2026-03-26-onboarding-v2-llm-cost-summary-design.md docs/plans/2026-03-26-onboarding-v2-llm-cost-summary.md
git commit -m "docs: plan onboarding v2 llm cost summary"
```
