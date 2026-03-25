# LLM Patch Draft Recovery And Retry Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce `patch_draft` `hard_fallback` outcomes by recovering salvageable malformed unified diffs, retrying invalid patch drafts once with targeted error feedback, and recording enough metadata to distinguish recovered output from true failures.

**Architecture:** Keep the existing `patch_planner.py` entrypoint and output artifacts, but strengthen the `write_llm_patch_draft(...) -> _normalize_llm_patch_content(...) -> _validate_llm_patch_content(...)` path. First, salvage valid file sections from partially corrupted multi-file diffs. Second, if the normalized draft still fails validation, make one constrained retry using the validation error and current target file list. Preserve current artifact locations and add metadata rather than changing downstream consumers first.

**Tech Stack:** Python, pytest, Pydantic, unified diff parsing, existing onboarding debug/recovery logging

---

### Task 1: Reproduce The `food-run-041` Failure Mode In Tests

**Files:**
- Modify: `chatbot/tests/onboarding/test_llm_patch_draft.py`
- Reference: `generated/food/food-run-041/reports/llm-debug/patch-draft.json`
- Reference: `generated/food/food-run-041/reports/llm-patch-draft-execution.json`

**Step 1: Write the failing test**

Add a test that feeds `write_llm_patch_draft(...)` a multi-file unified diff where:
- the first file diff is valid
- the second file diff starts correctly
- a later hunk is malformed like `@@ malformed` or a corrupt trailing fragment

Expected assertions:
- the written patch keeps the first valid file diff
- execution metadata is not `hard_fallback`
- `recovery_reason` explains that trailing malformed content was removed

Example shape:

```python
def test_write_llm_patch_draft_recovers_valid_prefix_from_multifile_malformed_diff(tmp_path: Path):
    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,4 @@
 def login(request):
     return None
+def onboarding_chat_auth_token(request):
+    return None
--- a/backend/config/router.py
+++ b/backend/config/router.py
@@ malformed
"""
    )
```

**Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k valid_prefix_from_multifile_malformed_diff -q
```

Expected: FAIL because current code returns `hard_fallback` with `invalid_patch_format`.

**Step 3: Add one more failing test for retry behavior**

Add a second test using a sequential fake LLM:
- first response is malformed unified diff
- second response is valid unified diff

Expected assertions:
- `write_llm_patch_draft(...)` performs two LLM calls
- output patch is valid
- execution metadata records retry success

**Step 4: Run both tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k "valid_prefix_from_multifile_malformed_diff or retry" -q
```

Expected: FAIL on both tests before implementation.

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding/test_llm_patch_draft.py
git commit -m "test: capture llm patch draft fallback regressions"
```

### Task 2: Salvage Recoverable Multi-File Unified Diffs Before Hard Fallback

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Test: `chatbot/tests/onboarding/test_llm_patch_draft.py`

**Step 1: Write the minimal recovery helper**

Add a helper near `_normalize_llm_patch_content(...)` that:
- splits the diff into file sections beginning with `--- a/...` and `+++ b/...`
- keeps only sections with at least one valid `@@ -old,+new @@` hunk header
- drops the malformed trailing section once corruption is detected
- returns a stable `recovery_reason` such as `patch_invalid_trailing_file_section_removed`

Expected helper shape:

```python
def _salvage_valid_unified_diff_sections(content: str) -> tuple[str, str | None]:
    sections = _split_unified_diff_sections(content)
    valid_sections: list[str] = []
    dropped_invalid = False
    for section in sections:
        if _section_has_valid_file_headers(section) and _section_has_valid_hunk_header(section):
            valid_sections.append(section)
            continue
        dropped_invalid = True
        break
    if valid_sections and dropped_invalid:
        return ("\n".join(valid_sections).rstrip() + "\n", "patch_invalid_trailing_file_section_removed")
    return (content, None)
```

**Step 2: Integrate salvage into normalization**

Update `_normalize_llm_patch_content(...)` so the order is:
1. strip code fences
2. remove redundant `@@`
3. salvage valid unified diff sections
4. return normalized content and the first applied recovery reason

Do not silently rewrite target file paths in this task.

**Step 3: Run the focused tests**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k "valid_prefix_from_multifile_malformed_diff or malformed_patch or redundant_hunk_marker" -q
```

Expected: PASS for the new salvage test and existing normalization recovery tests.

**Step 4: Run the full llm patch draft test file**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/patch_planner.py chatbot/tests/onboarding/test_llm_patch_draft.py
git commit -m "feat: recover salvageable llm patch drafts"
```

### Task 3: Add A Single Retry Loop For `invalid_patch_format`

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/tests/onboarding/test_llm_patch_draft.py`

**Step 1: Write the failing retry test**

Add a fake LLM that returns:
- call 1: malformed unified diff
- call 2: valid unified diff for an allowed target file

Assert:
- two `invoke(...)` calls occurred
- output patch contains the corrected hunk
- execution metadata records retry success without `hard_fallback`
- debug payload records attempt count `2`

Example assertion:

```python
assert len(fake_llm.calls) == 2
assert execution["source"] == "recovered_llm"
assert execution["recovery_reason"] == "invalid_patch_format_retry_succeeded"
assert debug_payload["attempt_count"] == 2
```

**Step 2: Run the test to verify it fails**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k retry_succeeded -q
```

Expected: FAIL because current code makes only one call and falls back immediately.

**Step 3: Implement the retry loop**

In `write_llm_patch_draft(...)`:
- keep the first LLM response and debug artifact
- if validation fails with `invalid_patch_format`, make one retry call
- send the retry prompt:
  - original malformed patch
  - validation error message
  - strict target file list
  - reminder to return only unified diff text
- re-run normalization and validation on the retry content
- if retry succeeds, write the recovered patch and metadata

Use a small helper rather than duplicating prompt construction:

```python
def _llm_patch_retry_human_payload(... ) -> str:
    return json.dumps(
        {
            "error": validation_error,
            "previous_patch": previous_patch,
            "allowed_target_files": allowed_target_files,
            "instruction": "Return only corrected unified diff.",
        },
        ensure_ascii=False,
        indent=2,
    )
```

**Step 4: Re-run targeted tests**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k "retry_succeeded or valid_prefix_from_multifile_malformed_diff" -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/patch_planner.py chatbot/tests/onboarding/test_llm_patch_draft.py
git commit -m "feat: retry invalid llm patch drafts once"
```

### Task 4: Expand Debug Artifacts So Hard Fallbacks Are Actionable

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/tests/onboarding/test_llm_patch_draft.py`

**Step 1: Write the failing observability test**

Add a test that forces final hard fallback and asserts the debug artifact contains:
- `attempt_count`
- `normalization_recovery_reason`
- `validation_error`
- `retry_validation_error` when retry also fails
- `final_status`

Expected shape:

```python
assert debug_payload["attempt_count"] == 2
assert debug_payload["validation_error"]["reason"] == "invalid_patch_format"
assert debug_payload["final_status"] == "hard_fallback"
```

**Step 2: Run the test to verify it fails**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k debug_payload -q
```

Expected: FAIL because current payload does not carry full retry history.

**Step 3: Implement metadata expansion**

Update `debug_payload` and execution metadata writing so each run captures:
- `attempt_count`
- `attempts`: list of `raw_content`, `normalized_content`, `validation_error`, `recovery_reason`
- top-level `final_status`

Keep the existing fields for backward compatibility.

**Step 4: Run focused tests**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k "debug_payload or malformed_patch" -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/patch_planner.py chatbot/tests/onboarding/test_llm_patch_draft.py
git commit -m "feat: record llm patch retry diagnostics"
```

### Task 5: Verify Downstream Compatibility With Existing Onboarding Flows

**Files:**
- Modify if needed: `chatbot/tests/onboarding/test_patch_planner.py`
- Modify if needed: `chatbot/tests/onboarding/test_orchestrator.py`
- Modify if needed: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Add or update a regression test**

Cover one end-to-end path where:
- patch proposal is deterministic
- patch draft comes from LLM and is recovered
- downstream comparison still prefers the usable patch

The test should assert no consumer breaks when execution metadata now includes retry fields.

**Step 2: Run the focused downstream tests**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=test-key uv run pytest chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_agent_integration.py -k "write_unified_diff_draft or frontend_diff or materializes_only_generator_proposals" -q
```

Expected: PASS.

**Step 3: Run the full relevant verification set**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=test-key uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_agent_integration.py -q
```

Expected: PASS.

**Step 4: Inspect a real generated run artifact**

Re-check:
- `generated/food/food-run-041/reports/llm-debug/patch-draft.json`
- `generated/food/food-run-041/reports/llm-patch-draft-execution.json`

Confirm future runs would now distinguish:
- recovered malformed prefix
- retry success
- unrecoverable final failure

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "test: verify llm patch draft recovery compatibility"
```

### Task 6: Plan The Next Migration From Diff Drafts To File-Edit Execution

**Files:**
- Create: `docs/plans/2026-03-21-llm-file-edit-executor.md`
- Reference: `chatbot/src/onboarding/patch_planner.py`
- Reference: `chatbot/src/onboarding/orchestrator.py`

**Step 1: Write the design-only follow-up plan**

Capture a separate migration plan for:
- replacing raw unified diff generation with file-scoped edit operations
- adding per-file retry instead of whole-patch retry
- retaining rollback and artifact logging

**Step 2: Keep this out of the current implementation**

Do not mix executor migration into the current patch-draft recovery branch.

**Step 3: Commit**

```bash
git add docs/plans/2026-03-21-llm-file-edit-executor.md
git commit -m "docs: plan llm file edit executor migration"
```

**Plan complete and saved to `docs/plans/2026-03-21-llm-patch-draft-recovery-and-retry-loop.md`. Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
