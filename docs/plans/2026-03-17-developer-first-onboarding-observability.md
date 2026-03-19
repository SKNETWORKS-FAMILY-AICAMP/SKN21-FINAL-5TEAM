# Developer-First Onboarding Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 온보딩 파이프라인의 상태 전이, LLM/recovery/fallback provenance, artifact write 경로를 canonical event model로 기록해 개발자 디버그 가시성을 높인다.

**Architecture:** `debug_logging.py`에 canonical onboarding event helper를 추가하고, `generation.log`와 `execution-trace.jsonl`은 그 이벤트를 각기 다른 형태로 렌더링한다. component producers는 event taxonomy에 맞는 structured payload를 넘기고, orchestrator는 stage transition owner로서 상위 lifecycle event만 관리한다.

**Tech Stack:** Python, pytest, onboarding orchestrator/debug logging/codebase mapper/role runner/patch planner

---

### Task 1: Add canonical onboarding event primitive

**Files:**
- Modify: `chatbot/src/onboarding/debug_logging.py`
- Test: `chatbot/tests/onboarding/test_debug_logging.py`

**Step 1: Write the failing test**

`append_onboarding_event()`가 canonical event를 받아:
- `generation.log`에 human-readable line을 남기고
- `execution-trace.jsonl` 또는 dedicated JSONL event artifact에 structured entry를 남기는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -k onboarding_event -v`
Expected: FAIL

**Step 3: Write minimal implementation**

`debug_logging.py`에:
- canonical event normalizer
- line renderer
- JSONL renderer
- compatibility wrapper

를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -k onboarding_event -v`
Expected: PASS

### Task 2: Make generation.log wrappers use canonical events

**Files:**
- Modify: `chatbot/src/onboarding/debug_logging.py`
- Test: `chatbot/tests/onboarding/test_debug_logging.py`

**Step 1: Write failing tests**

기존:
- `append_generation_log()`
- `append_execution_trace()`
- `append_recovery_event()`

가 canonical event rendering과 일관된 결과를 남기는 테스트를 추가한다.

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -k generation_log -v`
Expected: FAIL

**Step 3: Implement**

기존 API를 유지하되 내부적으로 `append_onboarding_event()`를 사용하도록 바꾼다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_debug_logging.py -k generation_log -v`
Expected: PASS

### Task 3: Add stage lifecycle events in orchestrator

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write failing tests**

- `analysis`, `planning`, `generation`, `validation`, `export` stage의 시작/완료 이벤트가 남는 테스트
- final result에 canonical event artifact path가 포함되는 테스트

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k observability -v`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k generation_log -v`

Expected: FAIL

**Step 3: Implement**

`orchestrator.py`에서 stage transition마다 canonical event를 기록한다. formatter는 `debug_logging.py`에 남기고, 여기서는 payload만 조립한다.

**Step 4: Verify**

Run the same commands; expected: PASS

### Task 4: Add component-level LLM/recovery provenance events

**Files:**
- Modify: `chatbot/src/onboarding/codebase_mapper.py`
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/role_runner.py`
- Test: `chatbot/tests/onboarding/test_codebase_mapper.py`
- Test: `chatbot/tests/onboarding/test_patch_planner.py`
- Test: `chatbot/tests/onboarding/test_llm_role_runner.py`

**Step 1: Write failing tests**

아래 이벤트가 component별로 남는 테스트를 추가한다.
- `llm_call_started`
- `llm_output_accepted`
- `recovery_applied`
- `hard_fallback_used`

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k recovery -v`
- `uv run pytest chatbot/tests/onboarding/test_patch_planner.py -k recovery -v`
- `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k recovered_llm -v`

Expected: FAIL

**Step 3: Implement**

각 component가 provenance event를 canonical shape로 기록하게 한다. debug artifact path와 recovery reason을 포함한다.

**Step 4: Verify**

Run the same commands; expected: PASS

### Task 5: Add frontend/runtime producer coverage

**Files:**
- Modify: `chatbot/src/onboarding/frontend_evaluator.py`
- Modify: `chatbot/src/onboarding/runtime_runner.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`
- Test: `chatbot/tests/onboarding/test_runtime_runner.py`

**Step 1: Write failing tests**

- frontend validation/recovery/hard fallback이 canonical event를 남기는 테스트
- runtime patch apply / simulation failure가 canonical event로 남는 테스트

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py -k observability -v`
- `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -k patch -v`

Expected: FAIL

**Step 3: Implement**

frontend/runtime component에서 producer event를 추가하되, sink formatting은 logging core에 맡긴다.

**Step 4: Verify**

Run the same commands; expected: PASS

### Task 6: Verify and prepare renderer handoff

**Files:**
- Modify: `docs/plans/2026-03-17-developer-first-onboarding-observability-design.md` if needed

**Step 1: Run**

`uv run pytest chatbot/tests/onboarding/test_debug_logging.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_llm_role_runner.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_runner.py -q`

Expected: PASS

**Step 2: Inspect one generated run manually**

확인 항목:
- canonical event artifact 존재
- `generation.log`와 event JSONL이 같은 lifecycle을 설명
- recovery/hard fallback reason과 debug artifact path가 포함됨

**Step 3: Commit**

```bash
git add chatbot/src/onboarding/debug_logging.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/codebase_mapper.py chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/role_runner.py chatbot/src/onboarding/frontend_evaluator.py chatbot/src/onboarding/runtime_runner.py chatbot/tests/onboarding
git commit -m "feat: add developer-first onboarding observability"
```
