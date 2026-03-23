# Soft Recovery And Hard Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** onboarding LLM-first 단계가 strict validation 실패 시 `recovered_llm` 또는 `hard_fallback`으로 분기되도록 만들고, Slack/generation.log/artifact에 source distribution을 명확히 노출한다.

**Architecture:** component별 strict validation은 유지하되, 실패 시 공통 recovery layer가 실행용 payload normalization을 시도한다. recovery 성공 시 `recovered_llm`, 실패 시 `hard_fallback`을 사용하며, 각 단계는 recovery event와 provenance를 artifact로 남긴다.

**Tech Stack:** Python, pytest, onboarding orchestrator, role runner, codebase mapper, patch planner, slack bridge

---

### Task 1: Add recovery event primitive

**Files:**
- Modify: `chatbot/src/onboarding/debug_logging.py`
- Test: `chatbot/tests/onboarding/test_debug_logging.py`

**Step 1: Write the failing test**

`append_recovery_event()`가 `reports/recovery-events.json`에 component/source/reason을 append하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -k recovery -v`
Expected: FAIL

**Step 3: Write minimal implementation**

append-only JSON list writer를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -k recovery -v`
Expected: PASS

### Task 2: Add soft recovery to codebase interpretation

**Files:**
- Modify: `chatbot/src/onboarding/codebase_mapper.py`
- Test: `chatbot/tests/onboarding/test_codebase_mapper.py`

**Step 1: Write failing tests**

- recovery 성공 시 `source == "recovered_llm"`
- recovery 실패 시 `source == "hard_fallback"`
- recovery reason/hard fallback reason이 artifact에 기록되는 테스트 추가

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k recovery -v`

**Step 3: Implement**

현재 normalization 로직을 recovery layer 형태로 재구성하고 recovery event를 기록한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k recovery -v`

### Task 3: Add soft recovery to role runner

**Files:**
- Modify: `chatbot/src/onboarding/role_runner.py`
- Test: `chatbot/tests/onboarding/test_llm_role_runner.py`

**Step 1: Write failing tests**

- `Generator`의 annotated confidence가 `recovered_llm`로 기록되는 테스트
- 진짜 복구 불가능 payload는 `hard_fallback`으로 기록되는 테스트

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k recovered_llm -v`

**Step 3: Implement**

role normalization을 recovery-aware source state로 변경한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k recovered_llm -v`

### Task 4: Add soft recovery / hard fallback to patch proposal and patch draft

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Test: `chatbot/tests/onboarding/test_patch_planner.py`
- Test: `chatbot/tests/onboarding/test_llm_patch_draft.py`

**Step 1: Write failing tests**

- patch proposal recovery success -> `recovered_llm`
- patch draft trivial normalization -> `recovered_llm`
- malformed diff -> `hard_fallback`

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_patch_planner.py -k recovery -v`
- `uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k recovery -v`

**Step 3: Implement**

patch proposal/draft execution artifacts에 source/recovery fields를 추가하고 recovery event 기록을 붙인다.

**Step 4: Verify**

Run the same commands; expect PASS

### Task 5: Surface source counts in Slack summary and generation log

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Test: `chatbot/tests/onboarding/test_slack_bridge.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write failing tests**

- summary에 `llm`, `recovered_llm`, `hard_fallback` count가 나오는 테스트
- generation.log에 `recovery_started`, `recovery_succeeded`, `hard_fallback_used`가 나오는 테스트

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_slack_bridge.py -k recovered_llm -v`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k recovery -v`

**Step 3: Implement**

summary builder와 timeline logging을 source-aware로 확장한다.

**Step 4: Verify**

Run the same commands; expect PASS

### Task 6: Verify touched suites

**Step 1: Run**

`uv run pytest chatbot/tests/onboarding/test_debug_logging.py chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_llm_role_runner.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_llm_patch_draft.py chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_agent_integration.py -q`

Expected: PASS
