# Runtime Completion Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** onboarding generation/export 이후 runtime workspace를 실제 실행 상태까지 자동 검증하고, chatbot mount 실패를 runtime repair loop로 복구한 뒤 최종 export patch로 수렴시키는 opt-in completion loop를 추가한다.

**Architecture:** `run_onboarding_generation.py`에 opt-in CLI 플래그를 추가하고, `orchestrator.py`는 export 완료 후 `runtime_completion_runner.py`를 호출한다. 새 runner는 backend/frontend 서버를 runtime workspace에서 기동하고 readiness/mount probe를 수행하며, 실패 시 기존 recovery planner와 repair action 체인을 runtime-only 수정으로 재사용한다. 성공 시 runtime diff를 다시 export artifact로 반영한다.

**Tech Stack:** Python, pytest, onboarding orchestrator/runtime runner/frontend evaluator/backend evaluator/recovery planner, subprocess, HTTP probes

---

### Task 1: Lock the opt-in CLI and orchestrator contract

**Files:**
- Modify: `chatbot/scripts/run_onboarding_generation.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

추가할 계약:

- `--enable-runtime-completion-loop` 플래그가 파서에서 인식된다.
- CLI가 orchestrator로 `enable_runtime_completion_loop=True`를 전달한다.
- orchestrator 결과에 completion artifact 경로가 포함될 자리를 고정한다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_cli_runner.py -k completion_loop -q`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k completion_loop_contract -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- CLI parser에 `--enable-runtime-completion-loop` 추가
- `run_onboarding_generation(...)` 호출 인자에 전달
- orchestrator result payload에 completion loop summary slot 추가

**Step 4: Run tests to verify they pass**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/scripts/run_onboarding_generation.py chatbot/tests/onboarding/test_cli_runner.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: add opt-in runtime completion loop flag"
```

### Task 2: Add a dedicated runtime completion runner contract

**Files:**
- Create: `chatbot/src/onboarding/runtime_completion_runner.py`
- Create: `chatbot/tests/onboarding/test_runtime_completion_runner.py`

**Step 1: Write the failing tests**

고정할 동작:

- completion runner가 backend/frontend probe plan을 만든다.
- probe 결과를 `runtime-completion.json`과 `runtime-server-probes.json`에 기록한다.
- 실패 시 `passed=False`, `failure_reason`, `attempt_count`를 포함한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k contract -q`

Expected: FAIL because runner module/behavior does not exist.

**Step 3: Write minimal implementation**

- result schema와 artifact writer를 먼저 구현
- runtime completion runner entrypoint를 추가

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k contract -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_completion_runner.py chatbot/tests/onboarding/test_runtime_completion_runner.py
git commit -m "feat: add runtime completion runner contract"
```

### Task 3: Implement runtime server boot and readiness probes

**Files:**
- Modify: `chatbot/src/onboarding/runtime_completion_runner.py`
- Modify: `chatbot/tests/onboarding/test_runtime_completion_runner.py`

**Step 1: Write the failing tests**

추가할 동작:

- frontend root의 package manager/scripts를 감지해 install/dev-build startup 계획을 만든다.
- backend framework에 맞는 실행 후보를 만든다.
- subprocess 기반 서버 기동 후 readiness HTTP probe를 수행한다.
- 실패 stdout/stderr가 artifact에 기록된다.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k readiness -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- backend/frontend startup plan builder 추가
- subprocess launch/terminate helper 추가
- HTTP readiness probe 추가
- `runtime-server-probes.json` 기록

**Step 4: Run tests to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k readiness -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_completion_runner.py chatbot/tests/onboarding/test_runtime_completion_runner.py
git commit -m "feat: add runtime server readiness probes"
```

### Task 4: Add mount probe and completion failure classification

**Files:**
- Modify: `chatbot/src/onboarding/runtime_completion_runner.py`
- Modify: `chatbot/src/onboarding/failure_classifier.py`
- Modify: `chatbot/src/onboarding/recovery_planner.py`
- Modify: `chatbot/tests/onboarding/test_runtime_completion_runner.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

고정할 동작:

- lightweight mount probe가 mount target page 응답과 widget wiring 존재를 기록한다.
- browser-backed probe가 가능한 환경에서는 `data-chatbot-status`를 확인한다.
- import resolution failure, dev server boot failure, mount missing이 각각 별도 failure class로 분류된다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k mount_probe -q`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k runtime_completion_failure -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- mount probe result schema 추가
- browser-backed probe는 환경 지원 시에만 실행하고, 미지원이면 `unsupported_environment`로 기록
- failure classifier와 recovery planner에 completion-loop failure class/action 추가

**Step 4: Run tests to verify they pass**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_completion_runner.py chatbot/src/onboarding/failure_classifier.py chatbot/src/onboarding/recovery_planner.py chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: classify runtime completion and mount probe failures"
```

### Task 5: Integrate runtime-only repair loop and export reconciliation

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/runtime_completion_runner.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`
- Modify: `chatbot/tests/onboarding/test_exporter.py`

**Step 1: Write the failing tests**

고정할 동작:

- export 완료 후 opt-in일 때만 completion runner가 호출된다.
- completion failure 시 runtime workspace에만 repair action이 적용된다.
- completion 성공 후 export patch와 metadata가 다시 갱신된다.
- retry budget 초과 시 `HUMAN_REVIEW_REQUIRED`로 종료된다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k runtime_completion -q`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k runtime_completion -q`
- `uv run pytest chatbot/tests/onboarding/test_exporter.py -k runtime_completion -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- orchestrator export 완료 직후 conditional completion loop 추가
- runtime-only repair application과 retry bookkeeping 추가
- 성공 시 `export_runtime_patch(...)` 재실행
- result payload에 completion artifact 경로 포함

**Step 4: Run tests to verify they pass**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/runtime_completion_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_exporter.py
git commit -m "feat: add runtime completion repair loop after export"
```

### Task 6: Cover the observed shared-widget runtime failure

**Files:**
- Modify: `chatbot/tests/onboarding/test_runtime_completion_runner.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

실제 관찰된 케이스를 고정한다.

- generated CRA runtime frontend가 `@shared-chatbot/ChatbotWidget` import를 resolve하지 못하면 completion loop가 이를 `frontend_import_resolution_failed`로 기록한다.
- recovery action이 runtime wrapper를 보정하거나 vendored path로 전환한 뒤 probe를 재시도한다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k shared_widget_import_failure -q`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k shared_widget_import_failure -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- stderr 패턴 기반 failure normalization 추가
- runtime-only repair action 추가
- 재검증 경로를 loop에 연결

**Step 4: Run tests to verify they pass**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/src/onboarding/runtime_completion_runner.py chatbot/src/onboarding/failure_classifier.py chatbot/src/onboarding/recovery_planner.py
git commit -m "fix: recover shared widget runtime import failures"
```

### Task 7: Verify the full onboarding slice

**Step 1: Run focused regression**

```bash
uv run pytest \
  chatbot/tests/onboarding/test_cli_runner.py \
  chatbot/tests/onboarding/test_runtime_completion_runner.py \
  chatbot/tests/onboarding/test_orchestrator.py \
  chatbot/tests/onboarding/test_agent_integration.py \
  chatbot/tests/onboarding/test_exporter.py -q
```

Expected: PASS

**Step 2: Run broader onboarding regression**

```bash
uv run pytest \
  chatbot/tests/onboarding/test_runtime_runner.py \
  chatbot/tests/onboarding/test_frontend_evaluator.py \
  chatbot/tests/onboarding/test_backend_evaluator.py \
  chatbot/tests/onboarding/test_cli_runner.py \
  chatbot/tests/onboarding/test_orchestrator.py \
  chatbot/tests/onboarding/test_agent_integration.py \
  chatbot/tests/onboarding/test_runtime_completion_runner.py -q
```

Expected: PASS

**Step 3: Run py_compile sanity**

```bash
uv run python -m py_compile \
  chatbot/scripts/run_onboarding_generation.py \
  chatbot/src/onboarding/orchestrator.py \
  chatbot/src/onboarding/runtime_completion_runner.py \
  chatbot/src/onboarding/frontend_evaluator.py \
  chatbot/src/onboarding/recovery_planner.py \
  chatbot/src/onboarding/failure_classifier.py
```

Expected: exit 0
