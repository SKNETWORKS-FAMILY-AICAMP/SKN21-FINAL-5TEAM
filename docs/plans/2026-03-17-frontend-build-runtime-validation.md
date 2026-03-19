# Frontend Build Runtime Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** runtime workspace에서 frontend install/build와 lightweight runtime validation을 실행해 LLM-first frontend onboarding 결과가 실제 앱 수준에서 최소한 깨지지 않는지 검증한다.

**Architecture:** `frontend_evaluator.py`를 artifact existence validator에서 build/runtime validation runner로 확장한다. build/install command 선택은 LLM-first proposal을 허용하되, deterministic runner가 실제 실행과 결과 수집을 담당한다. recovery는 command/path normalization까지만 허용하고, 실패 시 `hard_fallback`으로 기록한다.

**Tech Stack:** Python, pytest, onboarding frontend evaluator/runtime runner/recovery/orchestrator

---

### Task 1: Lock frontend build validation contract in tests

**Files:**
- Modify: `chatbot/tests/onboarding/test_frontend_evaluator.py`
- Modify: `chatbot/tests/onboarding/test_runtime_runner.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

다음을 먼저 테스트로 고정한다.
- frontend evaluation payload에 `install_attempted`, `build_attempted`, `build_passed`, `build_command`가 포함된다.
- build 성공 시 output artifact와 static runtime checks가 남는다.
- orchestrator가 frontend build validation report path를 결과에 포함한다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py -k build -v`
- `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -k frontend -v`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k frontend_build -v`

Expected: FAIL

**Step 3: Write minimal implementation expectations**

fixture와 assertion으로 contract shape를 명확히 고정한다.

**Step 4: Run tests again**

Run the same commands; expected: still FAIL but due to missing implementation, not bad test setup

### Task 2: Add frontend build/install runner

**Files:**
- Create: `chatbot/src/onboarding/frontend_build_runner.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`

**Step 1: Write the failing test**

`frontend_build_runner`가 workspace와 build plan을 받아:
- install/build 명령 실행 결과를 반환하고
- stdout/stderr/returncode를 수집하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py -k install_attempted -v`
Expected: FAIL

**Step 3: Write minimal implementation**

runner를 추가해:
- package manager 감지
- install/build command 실행
- timeout/exit code/stdout/stderr 수집

을 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py -k install_attempted -v`
Expected: PASS

### Task 3: Extend frontend evaluator with build + static runtime checks

**Files:**
- Modify: `chatbot/src/onboarding/frontend_evaluator.py`
- Modify: `chatbot/src/onboarding/frontend_recovery.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`

**Step 1: Write failing tests**

- build success -> `build_passed == True`
- build failure -> recovery attempted
- recovery success -> `source == "recovered_llm"`
- recovery failure -> `source == "hard_fallback"`
- mount/widget/import static checks가 payload에 포함됨

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py -v`
Expected: FAIL

**Step 3: Implement**

`frontend_evaluator.py`에서:
- 기존 widget/mount validation 유지
- build runner 호출
- static runtime checks 추가
- recovery path 통합

을 구현한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py -v`
Expected: PASS

### Task 4: Wire build/runtime validation into orchestrator

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write failing tests**

- onboarding run 후 `frontend-evaluation.json` 또는 `frontend-build-validation.json`이 생성되는 테스트
- result payload에 해당 report path와 source provenance가 포함되는 테스트

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k frontend_build -v`
Expected: FAIL

**Step 3: Implement**

orchestrator가 frontend artifact validation 이후 build/runtime validation을 호출하고, 결과 artifact path를 run result에 포함하도록 연결한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k frontend_build -v`
Expected: PASS

### Task 5: Add runtime workspace integration coverage

**Files:**
- Modify: `chatbot/src/onboarding/runtime_runner.py`
- Test: `chatbot/tests/onboarding/test_runtime_runner.py`

**Step 1: Write failing tests**

- runtime workspace에 frontend generated files가 복사된 뒤 build validator가 그 경로를 사용할 수 있는 테스트
- build failure artifact가 report에 정리되는 테스트

**Step 2: Run tests**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -k build -v`
Expected: FAIL

**Step 3: Implement**

runtime workspace와 frontend evaluator 사이 연결에 필요한 helper를 추가한다. source tree mutation은 하지 않고 report collection만 지원한다.

**Step 4: Verify**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -k build -v`
Expected: PASS

### Task 6: Verify touched suites

**Step 1: Run**

`uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_orchestrator.py -q`

Expected: PASS

**Step 2: Run broader regression slice**

`uv run pytest chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_frontend_mount_generator.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_orchestrator.py -q`

Expected: PASS
