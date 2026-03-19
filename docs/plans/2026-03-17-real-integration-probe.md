# Real Integration Probe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** fake smoke scaffold를 structured real integration probe pipeline으로 교체해 `login`, `chat token`, `product`, `order`를 실제 호출 기반으로 검증한다.

**Architecture:** `smoke_contract.py`에서 shell-script step 대신 structured HTTP probe step을 정의하고, `overlay_generator.py`는 default probe plan을 manifest에 기록한다. `smoke_runner.py`는 probe를 순차 실행하면서 runtime context를 누적하고 request/response summary를 `smoke-results.json`에 남긴다. orchestrator는 기존 smoke summary wiring을 유지하되 새 probe 결과를 소비한다.

**Tech Stack:** Python, pytest, onboarding smoke contract/runner/overlay generator/orchestrator

---

### Task 1: Lock structured probe contract in tests

**Files:**
- Modify: `chatbot/tests/onboarding/test_smoke_runner.py`
- Modify: `chatbot/tests/onboarding/test_overlay_generator.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

다음을 테스트로 고정한다.
- manifest `tests.smoke`가 shell script 문자열이 아니라 structured probe step을 저장한다.
- smoke result에 request/response summary와 exported state가 포함된다.
- orchestrator가 새 probe 결과 artifact를 그대로 소비한다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -v`
- `uv run pytest chatbot/tests/onboarding/test_overlay_generator.py -k smoke -v`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k smoke -v`

Expected: FAIL

**Step 3: Write minimal implementation expectations**

fixture와 assertion으로 contract shape를 명확히 고정한다.

**Step 4: Run tests again**

Run the same commands; expected: still FAIL due to missing implementation

### Task 2: Extend smoke contract to structured HTTP probes

**Files:**
- Modify: `chatbot/src/onboarding/smoke_contract.py`
- Test: `chatbot/tests/onboarding/test_smoke_runner.py`

**Step 1: Write the failing test**

`SmokeTestStep`가 아래를 검증하도록 테스트를 추가한다.
- `kind == "http"`
- `method`, `url`, `expects`
- `exports`, `uses`

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -k contract -v`
Expected: FAIL

**Step 3: Write minimal implementation**

structured probe schema와 backward-compat normalization을 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -k contract -v`
Expected: PASS

### Task 3: Generate default login/chat/product/order probe plan

**Files:**
- Modify: `chatbot/src/onboarding/overlay_generator.py`
- Test: `chatbot/tests/onboarding/test_overlay_generator.py`

**Step 1: Write the failing test**

default smoke steps가 네 가지 structured probe를 생성하는 테스트를 추가한다.
- `login`
- `chat-auth-token`
- `product-api`
- `order-api`

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_overlay_generator.py -k smoke -v`
Expected: FAIL

**Step 3: Implement**

analysis/auth/product/order 힌트를 기반으로 default probe plan을 생성한다. 기존 echo shell script 생성은 제거하거나 optional compatibility 경로로 내린다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_overlay_generator.py -k smoke -v`
Expected: PASS

### Task 4: Implement probe runner with runtime context passing

**Files:**
- Modify: `chatbot/src/onboarding/smoke_runner.py`
- Test: `chatbot/tests/onboarding/test_smoke_runner.py`

**Step 1: Write the failing tests**

- HTTP probe execution 결과가 status/json/body summary를 남기는 테스트
- `exports`로 context를 저장하는 테스트
- 후속 step이 `uses` 템플릿을 resolve하는 테스트
- missing endpoint/failure status를 올바르게 기록하는 테스트

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -v`
Expected: FAIL

**Step 3: Implement**

`smoke_runner.py`를 structured HTTP runner로 바꾼다. request/response summary, timeout, exported state, per-step provenance를 payload에 포함한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -v`
Expected: PASS

### Task 5: Wire new probe results into orchestrator and summary

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

- smoke results가 structured probe result shape를 유지하는 테스트
- smoke summary가 request/response 기반 required failure를 올바르게 계산하는 테스트

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k smoke -v`
Expected: FAIL

**Step 3: Implement**

orchestrator는 기존 wiring을 유지하되, 새 probe 결과를 추가 가공 없이 artifact로 저장한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k smoke -v`
Expected: PASS

### Task 6: Verify touched suites

**Step 1: Run**

`uv run pytest chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_overlay_generator.py chatbot/tests/onboarding/test_orchestrator.py -q`

Expected: PASS

**Step 2: Run broader regression slice**

`uv run pytest chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_overlay_generator.py chatbot/tests/onboarding/test_orchestrator.py -q`

Expected: PASS
