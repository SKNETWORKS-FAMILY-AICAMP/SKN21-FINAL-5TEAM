# Unified Generation Log Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 온보딩 generation 실행 전체를 시간순으로 추적할 수 있는 단일 `generation.log` 파일을 추가한다.

**Architecture:** `debug_logging.py`에 append-only generation log writer를 추가하고, orchestrator와 LLM/role logging 경로에서 공통 writer를 호출한다. 기존 `execution-trace.jsonl`과 `llm-debug/*.json`은 유지하되, `generation.log`에는 단계 요약과 artifact 경로를 남긴다.

**Tech Stack:** Python, pytest, onboarding orchestrator/debug logging

---

### Task 1: Add generation log writer primitive

**Files:**
- Modify: `chatbot/src/onboarding/debug_logging.py`
- Test: `chatbot/tests/onboarding/test_debug_logging.py`

**Step 1: Write the failing test**

`test_debug_logging.py`에 `append_generation_log()`가 `reports/generation.log`를 생성하고 두 줄 이상 append하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -v`
Expected: FAIL because `append_generation_log` does not exist yet

**Step 3: Write minimal implementation**

`debug_logging.py`에:
- `append_generation_log(...)`
- details 직렬화 helper
- `reports/generation.log` append 구현

를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/debug_logging.py chatbot/tests/onboarding/test_debug_logging.py
git commit -m "feat: add generation log writer"
```

### Task 2: Route orchestrator stage logs into generation.log

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

integration test에 onboarding run 후 결과 payload에 `generation_log_path`가 포함되고, `generation.log`에 `analysis_started`, `patch_proposal_written` 같은 핵심 이벤트가 남는 검증을 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k generation_log -v`
Expected: FAIL because result payload and log file do not exist yet

**Step 3: Write minimal implementation**

`orchestrator.py`에서:
- 공통 file+terminal log emit helper 추가
- 주요 단계 시작/완료/산출물 기록
- `_build_run_result()`에 `generation_log_path` 추가

를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k generation_log -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "feat: log generation timeline in orchestrator"
```

### Task 3: Add LLM codebase interpretation debug artifact + fallback logging

**Files:**
- Modify: `chatbot/src/onboarding/codebase_mapper.py`
- Test: `chatbot/tests/onboarding/test_codebase_mapper.py`

**Step 1: Write the failing test**

LLM payload validation 실패 시:
- `llm-debug/codebase-interpretation.json`이 생성되고
- `generation.log`에 fallback reason과 debug path가 남는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k codebase_interpretation -v`
Expected: FAIL because debug artifact/logging are incomplete

**Step 3: Write minimal implementation**

`codebase_mapper.py`에서:
- raw response / normalized payload / error 정보를 `write_llm_debug_artifact()`로 저장
- LLM 시작/성공/fallback을 `append_generation_log()`로 기록

를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k codebase_interpretation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/codebase_mapper.py chatbot/tests/onboarding/test_codebase_mapper.py
git commit -m "feat: log codebase interpretation debug timeline"
```

### Task 4: Mirror role runner activity into generation.log

**Files:**
- Modify: `chatbot/src/onboarding/role_runner.py`
- Test: `chatbot/tests/onboarding/test_llm_role_runner.py`

**Step 1: Write the failing test**

role 실행 완료 시 `generation.log`에 `role_started`, `role_completed`, `fallback_reason`가 남는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k generation_log -v`
Expected: FAIL because role runner does not write generation log lines

**Step 3: Write minimal implementation**

`role_runner.py`에 report root를 주입할 수 있게 하고:
- role 시작
- llm success
- fallback 발생
- debug artifact 경로

를 generation log에 남긴다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k generation_log -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/role_runner.py chatbot/tests/onboarding/test_llm_role_runner.py
git commit -m "feat: add role runner generation timeline logs"
```

### Task 5: Verify full flow and document result

**Files:**
- Modify: `docs/plans/2026-03-17-unified-generation-log-design.md` if implementation notes change

**Step 1: Run targeted tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -v`
- `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k codebase_interpretation -v`
- `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k generation_log -v`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k generation_log -v`

Expected: PASS

**Step 2: Run broader regression slice**

Run: `uv run pytest chatbot/tests/onboarding -q`
Expected: PASS or known unrelated failures documented

**Step 3: Confirm artifact shape manually**

Inspect one generated run and verify:
- `reports/generation.log` exists
- lines are time-ordered
- fallback/debug artifact paths are included

**Step 4: Commit**

```bash
git add docs/plans/2026-03-17-unified-generation-log-design.md
git commit -m "docs: record unified generation log verification"
```
