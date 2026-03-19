# Generation Log And LLM Patch Guardrails Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `generation.log`를 patch draft, simulation, smoke, export 단계까지 확장하고, malformed LLM patch draft를 placeholder + fallback metadata로 처리한다.

**Architecture:** `patch_planner.py`가 LLM patch 초안을 생성한 뒤 lightweight unified diff validation을 수행하고, 실패 시 placeholder patch와 execution/debug artifact를 기록한다. `orchestrator.py`는 patch draft, merge simulation, smoke tests, export 단계를 `generation.log`에 append한다.

**Tech Stack:** Python, pytest, onboarding orchestrator, patch planner

---

### Task 1: Add failing tests for malformed LLM patch placeholder

**Files:**
- Modify: `chatbot/tests/onboarding/test_llm_patch_draft.py`
- Modify: `chatbot/src/onboarding/patch_planner.py`

**Step 1: Write the failing test**

malformed unified diff를 반환하는 fake LLM이 들어왔을 때:
- `llm-proposed.patch`는 placeholder를 남기고
- execution/debug artifact가 생성되며
- fallback reason이 기록되는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k malformed -v`
Expected: FAIL because current implementation writes raw invalid patch directly

**Step 3: Write minimal implementation**

`patch_planner.py`에:
- patch validation helper
- placeholder content builder
- patch draft execution artifact writer
- generation log append

를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k malformed -v`
Expected: PASS

### Task 2: Extend generation.log across patch/simulation/smoke/export

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

generation run 후 `generation.log`에 다음 이벤트가 남는 테스트를 추가한다:
- `llm_patch_draft_started`
- `llm_patch_draft_completed` 또는 `llm_patch_draft_fallback`
- `llm_patch_simulation_completed`
- `merge_simulation_completed`
- `smoke_tests_completed`
- `export_completed`

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k generation_log -v`
Expected: FAIL because current timeline is too sparse

**Step 3: Write minimal implementation**

`orchestrator.py`에서 위 단계 직후 generation log를 append하도록 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k generation_log -v`
Expected: PASS

### Task 3: Verify targeted regression coverage

**Files:**
- Modify: none unless fixes are required

**Step 1: Run targeted suite**

Run:
- `uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -v`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k 'generation_log or llm_patch_draft' -v`

Expected: PASS

**Step 2: Run broader touched-area regression**

Run:
- `uv run pytest chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_patch_comparison.py chatbot/tests/onboarding/test_runtime_runner.py -q`

Expected: PASS
