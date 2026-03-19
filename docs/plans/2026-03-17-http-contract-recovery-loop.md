# HTTP Contract Recovery Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 로그인 이후의 HTTP contract mismatch를 분류하고, 안전한 deterministic recovery를 적용한 뒤 smoke/evaluator를 재실행하는 bounded recovery loop를 추가한다.

**Architecture:** `Diagnostician`이 failure classification과 retry 가능 여부를 판단하고, `Recovery Planner`가 structured recovery payload를 만든다. `Deterministic Fixer`는 probe plan과 target/schema override만 수정한다. orchestrator는 recovery attempt를 기록하고 retry budget 내에서 validation을 재실행한다.

**Tech Stack:** Python, pytest, onboarding orchestrator/smoke/evaluator/recovery pipeline

---

### Task 1: Lock recovery taxonomy and payload contract in tests

**Files:**
- Create: `chatbot/tests/onboarding/test_recovery_planner.py`
- Modify: `chatbot/tests/onboarding/test_llm_role_runner.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

고정할 contract:
- Diagnostician context가 failure classification 입력을 받는다.
- recovery payload가 `classification`, `should_retry`, `proposed_probe_updates`, `proposed_schema_overrides`를 가진다.
- orchestrator가 recovery artifact path를 기록한다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_recovery_planner.py -v`
- `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k recovery -v`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k recovery -v`

Expected: FAIL

**Step 3: Write minimal implementation expectations**

failure taxonomy와 payload shape를 fixture/assertion으로 명확히 고정한다.

**Step 4: Run tests again**

같은 명령을 다시 실행한다.
Expected: still FAIL due to missing implementation

### Task 2: Add structured recovery planner module

**Files:**
- Create: `chatbot/src/onboarding/recovery_planner.py`
- Test: `chatbot/tests/onboarding/test_recovery_planner.py`

**Step 1: Write the failing test**

다음을 검증한다.
- known mismatch signature가 recovery classification으로 매핑된다.
- safe correction만 recovery payload에 포함된다.
- non-recoverable signature는 `should_retry=False`가 된다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_recovery_planner.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

classification rules와 recovery payload builder를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_recovery_planner.py -v`
Expected: PASS

### Task 3: Extend smoke contract and runner for recovery overrides

**Files:**
- Modify: `chatbot/src/onboarding/smoke_contract.py`
- Modify: `chatbot/src/onboarding/smoke_runner.py`
- Test: `chatbot/tests/onboarding/test_smoke_runner.py`

**Step 1: Write the failing tests**

고정할 behavior:
- recovered probe updates가 기존 smoke step에 merge된다.
- schema override가 `expects`/`exports`에 반영된다.
- results artifact가 recovery provenance를 남긴다.

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -k recovery -v`
Expected: FAIL

**Step 3: Implement**

step override merge와 recovery provenance 기록을 추가한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -k recovery -v`
Expected: PASS

### Task 4: Add recovered smoke plan artifact generation

**Files:**
- Modify: `chatbot/src/onboarding/overlay_generator.py`
- Create: `chatbot/src/onboarding/recovery_artifacts.py`
- Test: `chatbot/tests/onboarding/test_overlay_generator.py`

**Step 1: Write the failing tests**

고정할 behavior:
- recovery payload로부터 `recovered-smoke-plan.json`이 생성된다.
- probe url/body/header/exports override가 반영된다.

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_overlay_generator.py -k recovered -v`
Expected: FAIL

**Step 3: Implement**

recovered smoke artifact writer와 merge logic을 추가한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_overlay_generator.py -k recovered -v`
Expected: PASS

### Task 5: Wire Diagnostician to structured recovery output

**Files:**
- Modify: `chatbot/src/onboarding/role_runner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_llm_role_runner.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

고정할 behavior:
- Diagnostician metadata가 `failure_signature`, `root_cause_hypothesis`, `proposed_fix`뿐 아니라 `classification`과 `should_retry`를 포함한다.
- orchestrator가 recovery planner를 호출하고 artifact를 기록한다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k diagnostician -v`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k recovery -v`

Expected: FAIL

**Step 3: Implement**

Diagnostician context를 확장하고 recovery payload를 orchestrator로 전달한다.

**Step 4: Verify**

Run the same commands.
Expected: PASS

### Task 6: Add bounded retry loop with recovery attempts log

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/agent_contracts.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

고정할 behavior:
- recoverable mismatch는 retry budget 내에서 재실행된다.
- non-recoverable mismatch는 즉시 human review로 간다.
- repeated identical signature는 추가 retry 없이 멈춘다.
- `recovery-attempts.json`가 남는다.

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k retry -v`
Expected: FAIL

**Step 3: Implement**

bounded retry loop, duplicate signature stop rule, recovery attempts artifact를 추가한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k retry -v`
Expected: PASS

### Task 7: Preserve recovery provenance in export and run result

**Files:**
- Modify: `chatbot/src/onboarding/exporter.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_exporter.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

고정할 behavior:
- export metadata에 recovery provenance가 기록된다.
- run result에 recovery artifact path와 final recovery source가 포함된다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_exporter.py -k recovery -v`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k recovery_result -v`

Expected: FAIL

**Step 3: Implement**

export metadata와 final run result payload에 recovery provenance를 기록한다.

**Step 4: Verify**

Run the same commands.
Expected: PASS

### Task 8: Run focused recovery regression slice

**Step 1: Run**

`uv run pytest chatbot/tests/onboarding/test_recovery_planner.py chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_overlay_generator.py chatbot/tests/onboarding/test_llm_role_runner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_exporter.py -q`

Expected: PASS

**Step 2: Run broader onboarding regression**

`uv run pytest chatbot/tests/onboarding -q`

Expected: PASS or documented pre-existing unrelated failures only
