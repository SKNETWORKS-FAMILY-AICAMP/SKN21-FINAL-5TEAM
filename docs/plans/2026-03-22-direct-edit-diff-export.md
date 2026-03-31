# Direct Edit + Diff Export Onboarding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 온보딩 생성 파이프라인을 patch-first 구조에서 runtime direct-edit + final diff export 구조로 전환한다.

**Architecture:** planning은 edit target 선정과 operation schema 생성으로 제한하고, generation/repair는 runtime workspace 파일을 직접 수정한다. export 단계에서만 `source_root` 대비 diff를 `approved.patch`로 내보내고, clean replay validation으로 재현성을 검증한다.

**Tech Stack:** Python, pytest, onboarding orchestrator, runtime runner, exporter, pydantic JSON artifacts, UTF-8 file rewriting, unified diff export

---

### Task 1: Introduce direct-edit artifacts and apply helper

**Files:**
- Create: `chatbot/src/onboarding/workspace_editor.py`
- Modify: `chatbot/src/onboarding/manifest.py`
- Modify: `chatbot/src/onboarding/run_generator.py`
- Test: `chatbot/tests/onboarding/test_workspace_editor.py`
- Test: `chatbot/tests/onboarding/test_runtime_runner.py`

**Step 1: Write the failing tests**

- Add `test_apply_direct_edit_operations_supports_replace_insert_and_append`.
- Add `test_apply_direct_edit_operations_rejects_paths_outside_workspace`.
- Extend manifest/runtime tests to accept `edit_artifacts` without requiring new patch files.

Example operation payload to encode in the test:

```python
{
    "path": "backend/users/views.py",
    "operation": "insert_after",
    "anchor": "def logout(request):",
    "content": "\n\ndef onboarding_chat_auth_token(request):\n    return None\n",
}
```

**Step 2: Run test to verify it fails**

Run:
- `uv run pytest chatbot/tests/onboarding/test_workspace_editor.py -q`
- `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -k edit_artifacts -q`

Expected: FAIL because no direct-edit helper or manifest field exists yet.

**Step 3: Write minimal implementation**

- Create `apply_direct_edit_operations(workspace_root, operations)` in `workspace_editor.py`.
- Add strict validation:
  - relative path only
  - no `..`
  - UTF-8 text files only
  - supported operations limited to `replace_text`, `insert_after`, `insert_before`, `append_text`
- Extend `OverlayManifest` with `edit_artifacts: list[str] = []`.
- Ensure run bundle defaults include `edit_artifacts`.

**Step 4: Run test to verify it passes**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/workspace_editor.py chatbot/src/onboarding/manifest.py chatbot/src/onboarding/run_generator.py chatbot/tests/onboarding/test_workspace_editor.py chatbot/tests/onboarding/test_runtime_runner.py
git commit -m "feat: add direct edit artifacts and workspace editor"
```

### Task 2: Convert patch planning outputs into edit planning outputs

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Test: `chatbot/tests/onboarding/test_patch_planner.py`
- Test: `chatbot/tests/onboarding/test_llm_patch_draft.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing tests**

- Add a planner test that `write_llm_patch_draft(...)` is replaced or wrapped by a direct-edit artifact writer that emits `reports/edit-plan.json`.
- Add a test that valid LLM output is normalized into edit operations instead of unified diff text.
- Add a compatibility test that `patch-proposal.json` still records target files and reasons.

Example normalized edit payload to assert:

```json
{
  "operations": [
    {
      "path": "backend/foodshop/urls.py",
      "operation": "insert_after",
      "anchor": "path(\"api/users/\", include(\"users.urls\")),",
      "content": "\n    path(\"api/chat/auth-token\", onboarding_chat_auth_token),"
    }
  ],
  "source": "llm"
}
```

**Step 2: Run test to verify it fails**

Run:
- `uv run pytest chatbot/tests/onboarding/test_patch_planner.py -k direct_edit -q`
- `uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k direct_edit -q`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k edit_plan -q`

Expected: FAIL because planner still emits patch text and patch-specific recovery codes.

**Step 3: Write minimal implementation**

- Add `write_edit_plan(...)` and `write_llm_edit_draft(...)` in `patch_planner.py`.
- Keep `patch-proposal.json` as the target-selection artifact.
- Emit:
  - `reports/edit-plan.json`
  - `reports/edit-execution.json` metadata skeleton
- Preserve legacy helper names behind a compatibility wrapper only if callers still import them.
- Update Slack summaries to describe “edit targets” rather than “patch files”.

**Step 4: Run test to verify it passes**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_llm_patch_draft.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "feat: emit direct edit plans instead of patch drafts"
```

### Task 3: Rewire orchestrator generation and validation around runtime direct edits

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/runtime_runner.py`
- Modify: `chatbot/src/onboarding/debug_logging.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`
- Test: `chatbot/tests/onboarding/test_runtime_runner.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`
- Test: `chatbot/tests/onboarding/test_cli_runner.py`

**Step 1: Write the failing tests**

- Add an orchestrator test that generation writes `edit-plan.json` and applies edits into `runtime/.../workspace` before validation.
- Add a runtime runner test that `simulate_runtime_merge(...)` continues to apply generated files and static template patches, but does not expect `proposed.patch` or `llm-proposed.patch`.
- Add an integration test that result payload includes `edit_plan_path` and `edit_execution_path`.
- Add a CLI payload test that exported metadata still exists while edit artifacts are added.

**Step 2: Run test to verify it fails**

Run:
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k direct_edit -q`
- `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -k direct_edit -q`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k direct_edit -q`
- `uv run pytest chatbot/tests/onboarding/test_cli_runner.py -k edit_plan -q`

Expected: FAIL because generation still writes `proposed.patch` and validation still simulates candidate patch merges.

**Step 3: Write minimal implementation**

- In `orchestrator.py`:
  - replace `write_unified_diff_draft(...)`
  - replace `write_llm_patch_draft(...)`
  - apply edit operations directly to runtime workspace after `prepare_runtime_workspace(...)`
  - write `edit-execution.json`
- In `runtime_runner.py`:
  - keep static patch support for template artifacts in `manifest.patch_targets`
  - stop treating LLM/deterministic generated edits as candidate patch artifacts
- Add new execution trace/log events:
  - `edit_plan_written`
  - `edit_application_started`
  - `edit_application_completed`

**Step 4: Run test to verify it passes**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/runtime_runner.py chatbot/src/onboarding/debug_logging.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py
git commit -m "refactor: run onboarding generation through runtime direct edits"
```

### Task 4: Convert runtime LLM repair from patch apply to direct edits

**Files:**
- Modify: `chatbot/src/onboarding/runtime_llm_repair.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_retry_policy.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

- Add a repair test that LLM runtime repair returns edit operations and applies them through `workspace_editor.py`.
- Add a retry-policy test that server restart / smoke rerun still occurs after a successful direct edit repair.
- Add an integration test that repair artifacts record `applied_edits` instead of `patch_path`.

Example repair payload to use in tests:

```json
{
  "operations": [
    {
      "path": "backend/foodshop/urls.py",
      "operation": "replace_text",
      "old": "from backend.chat_auth import chat_auth_token",
      "new": "from chat_auth import chat_auth_token"
    }
  ]
}
```

**Step 2: Run test to verify it fails**

Run:
- `uv run pytest chatbot/tests/onboarding/test_retry_policy.py -k runtime_repair -q`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k llm_runtime_repair -q`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k runtime_repair -q`

Expected: FAIL because runtime repair still expects unified diff responses and patch target extraction.

**Step 3: Write minimal implementation**

- Replace `_runtime_repair_system_prompt()` output contract from unified diff to JSON edit payload.
- Remove `_apply_patch_file(...)` dependency from `runtime_llm_repair.py`.
- Validate candidate file paths against the same allowlist rules used by `workspace_editor.py`.
- Keep debug artifacts, but change failure reasons to:
  - `edit_payload_invalid`
  - `edit_target_rejected`
  - `edit_apply_failed`

**Step 4: Run test to verify it passes**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_llm_repair.py chatbot/src/onboarding/orchestrator.py chatbot/tests/onboarding/test_retry_policy.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "refactor: apply runtime llm repair as direct edits"
```

### Task 5: Export final diff and add clean replay validation

**Files:**
- Modify: `chatbot/src/onboarding/exporter.py`
- Modify: `chatbot/src/onboarding/runtime_runner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/run_resume.py`
- Test: `chatbot/tests/onboarding/test_exporter.py`
- Test: `chatbot/tests/onboarding/test_export_approval_contract.py`
- Test: `chatbot/tests/onboarding/test_runtime_runner.py`
- Test: `chatbot/tests/onboarding/test_run_resume.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing tests**

- Add an exporter test that `export_runtime_patch(...)` records `edit_artifacts`, `replay_report_path`, and `replay_passed`.
- Add a runtime runner test that clean replay applies `approved.patch` to a fresh workspace and writes `export-replay-validation.json`.
- Add a resume test that export/replay metadata is sufficient to resume from the export boundary.
- Add an integration test that `approved.patch` is generated only after runtime validation succeeds.

**Step 2: Run test to verify it fails**

Run:
- `uv run pytest chatbot/tests/onboarding/test_exporter.py -k replay -q`
- `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -k replay_validation -q`
- `uv run pytest chatbot/tests/onboarding/test_run_resume.py -k replay -q`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k approved_patch_export -q`

Expected: FAIL because export metadata does not yet include replay validation and candidate patch simulation is still the old gate.

**Step 3: Write minimal implementation**

- Extend `export_runtime_patch(...)` metadata with:
  - `edit_artifacts`
  - `replay_report_path`
  - `replay_passed`
- Add `simulate_exported_patch_replay(...)` in `runtime_runner.py`.
- Call replay validation from `orchestrator.py` after export and before final approval-ready state.
- Teach `run_resume.py` to read replay status from `export-metadata.json`.

**Step 4: Run test to verify it passes**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/exporter.py chatbot/src/onboarding/runtime_runner.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/run_resume.py chatbot/tests/onboarding/test_exporter.py chatbot/tests/onboarding/test_export_approval_contract.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_run_resume.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "feat: export final runtime diff with replay validation"
```

### Task 6: Remove patch-first assumptions from comparison and observability

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Test: `chatbot/tests/onboarding/test_patch_comparison.py`
- Test: `chatbot/tests/onboarding/test_debug_logging.py`
- Test: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing tests**

- Add a comparison test that `patch-comparison.json` compares exported deterministic diff vs exported LLM diff rather than raw draft patch files.
- Add a debug logging test that canonical events include `edit_plan_written` and `export_replay_validation_completed`.
- Add a Slack bridge test that review messaging references direct edits and final export patch rather than “runtime patch may fail”.

**Step 2: Run test to verify it fails**

Run:
- `uv run pytest chatbot/tests/onboarding/test_patch_comparison.py -q`
- `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -k edit_plan -q`
- `uv run pytest chatbot/tests/onboarding/test_slack_bridge.py -k direct_edit -q`

Expected: FAIL because observability still assumes patch drafts and candidate patch simulation.

**Step 3: Write minimal implementation**

- Rename or reinterpret comparison payload fields so they describe exported diffs.
- Update generation/validation/export logs to talk about edit application and replay validation.
- Preserve old JSON keys only where external contracts require compatibility.

**Step 4: Run test to verify it passes**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_patch_comparison.py chatbot/tests/onboarding/test_debug_logging.py chatbot/tests/onboarding/test_slack_bridge.py
git commit -m "refactor: align onboarding observability with direct edit flow"
```

### Task 7: Run the full onboarding regression slice

**Files:**
- Verify only

**Step 1: Run focused direct-edit regression**

```bash
uv run pytest \
  chatbot/tests/onboarding/test_workspace_editor.py \
  chatbot/tests/onboarding/test_patch_planner.py \
  chatbot/tests/onboarding/test_llm_patch_draft.py \
  chatbot/tests/onboarding/test_runtime_runner.py \
  chatbot/tests/onboarding/test_orchestrator.py \
  chatbot/tests/onboarding/test_retry_policy.py \
  chatbot/tests/onboarding/test_exporter.py \
  chatbot/tests/onboarding/test_run_resume.py -q
```

Expected: PASS

**Step 2: Run broader end-to-end regression**

```bash
uv run pytest \
  chatbot/tests/onboarding/test_agent_integration.py \
  chatbot/tests/onboarding/test_cli_runner.py \
  chatbot/tests/onboarding/test_export_approval_contract.py \
  chatbot/tests/onboarding/test_patch_comparison.py \
  chatbot/tests/onboarding/test_slack_bridge.py \
  chatbot/tests/onboarding/test_debug_logging.py -q
```

Expected: PASS

**Step 3: Run compile sanity**

```bash
uv run python -m py_compile \
  chatbot/src/onboarding/workspace_editor.py \
  chatbot/src/onboarding/patch_planner.py \
  chatbot/src/onboarding/orchestrator.py \
  chatbot/src/onboarding/runtime_llm_repair.py \
  chatbot/src/onboarding/runtime_runner.py \
  chatbot/src/onboarding/exporter.py \
  chatbot/src/onboarding/run_resume.py
```

Expected: exit 0

**Step 4: Manual acceptance spot-check**

- Run one real site generation, preferably `food`, with direct-edit mode enabled.
- Confirm these artifacts exist:
  - `reports/edit-plan.json`
  - `reports/edit-execution.json`
  - `reports/export-metadata.json`
  - `reports/export-replay-validation.json`
  - `reports/approved.patch`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding chatbot/tests/onboarding docs/plans/2026-03-22-direct-edit-diff-export-design.md docs/plans/2026-03-22-direct-edit-diff-export.md
git commit -m "refactor: switch onboarding pipeline to direct edit and diff export"
```
