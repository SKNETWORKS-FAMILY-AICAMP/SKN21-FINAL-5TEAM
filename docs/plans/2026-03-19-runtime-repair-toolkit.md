# Runtime Repair Toolkit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** runtime completion loop에 backend/frontend import and boot 오류를 고칠 수 있는 deterministic repair toolkit을 추가한다.

**Architecture:** completion loop의 stderr/traceback를 더 구체적인 failure signature로 정규화하고, runtime workspace 기준 module resolver/import rewriter를 사용해 repair action을 실제 적용한다. 첫 구현은 Django backend import resolution과 shared widget frontend import resolution을 범용 helper로 묶는 데 집중한다.

**Tech Stack:** Python, pytest, onboarding orchestrator/runtime completion runner, subprocess stderr classification, line-based file rewrite

---

### Task 1: Lock traceback-driven backend failure classification

**Files:**
- Modify: `chatbot/src/onboarding/runtime_completion_runner.py`
- Modify: `chatbot/src/onboarding/failure_classifier.py`
- Modify: `chatbot/tests/onboarding/test_runtime_completion_runner.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

- `ModuleNotFoundError: No module named 'backend'` stderr가 `backend_import_resolution_failed`로 정규화된다.
- Django `urls.py` import traceback가 broad `backend_readiness_failed`보다 구체적인 signature를 만든다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k backend_import_resolution -q`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k backend_import_resolution_failed -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- `runtime_completion_runner.py`에 traceback classifier helper 추가
- `failure_classifier.py`에 `backend_import_resolution_failed`, `django_urlconf_import_failed` 대응 추가

**Step 4: Run tests to verify they pass**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_completion_runner.py chatbot/src/onboarding/failure_classifier.py chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: classify backend import resolution failures"
```

### Task 2: Add runtime Python module resolver and import rewriter

**Files:**
- Create: `chatbot/src/onboarding/runtime_repair_toolkit.py`
- Create: `chatbot/tests/onboarding/test_runtime_repair_toolkit.py`

**Step 1: Write the failing tests**

- broken module name에서 runtime workspace 내 candidate file을 찾는다.
- caller file context를 기준으로 replacement import path를 계산한다.
- exact import line만 rewrite한다.

**Step 2: Run test to verify it fails**

Run:
- `uv run pytest chatbot/tests/onboarding/test_runtime_repair_toolkit.py -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- `resolve_python_module_candidates(...)`
- `choose_runtime_import_replacement(...)`
- `rewrite_python_import_line(...)`

**Step 4: Run test to verify it passes**

Run:
- `uv run pytest chatbot/tests/onboarding/test_runtime_repair_toolkit.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_repair_toolkit.py chatbot/tests/onboarding/test_runtime_repair_toolkit.py
git commit -m "feat: add runtime python import repair toolkit"
```

### Task 3: Implement Django runtime boot repair

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/runtime_repair_toolkit.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`
- Modify: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

- `repair_backend_entrypoint`가 Django urlconf import mismatch를 실제 수정한다.
- `food-run-015`와 같은 `from backend.chat_auth import chat_auth_token` 오류가 runtime workspace에서 `from chat_auth import chat_auth_token` 또는 equivalent valid import로 바뀐다.
- repair 후 second attempt에서 completion loop가 retry 가능 상태가 된다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k backend_import_repair -q`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k repair_backend_entrypoint -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- `_apply_repair_actions(...)`에 `repair_backend_entrypoint` 구현
- traceback context를 읽어 target file/import를 선택
- runtime workspace만 수정

**Step 4: Run tests to verify they pass**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/runtime_repair_toolkit.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "fix: repair django runtime import mismatches"
```

### Task 4: Generalize frontend import repair onto the toolkit

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/runtime_repair_toolkit.py`
- Modify: `chatbot/tests/onboarding/test_runtime_completion_runner.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing tests**

- `repair_shared_widget_import`가 toolkit helper를 사용하도록 고정한다.
- frontend shared widget import recovery가 기존 동작을 유지한다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k shared_widget_import_failure -q`
- `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k shared_widget_import_failure -q`

Expected: FAIL

**Step 3: Write minimal implementation**

- 기존 frontend import rewrite를 toolkit helper로 이전
- duplicated line-rewrite logic 제거

**Step 4: Run tests to verify they pass**

Run the same commands.

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/runtime_repair_toolkit.py chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "refactor: route frontend import repair through runtime toolkit"
```

### Task 5: Verify the runtime repair slice

**Files:**
- Verify only

**Step 1: Run focused regression**

```bash
uv run pytest \
  chatbot/tests/onboarding/test_runtime_repair_toolkit.py \
  chatbot/tests/onboarding/test_runtime_completion_runner.py \
  chatbot/tests/onboarding/test_orchestrator.py \
  chatbot/tests/onboarding/test_agent_integration.py -q
```

Expected: PASS

**Step 2: Run broader onboarding regression**

```bash
uv run pytest \
  chatbot/tests/onboarding/test_cli_runner.py \
  chatbot/tests/onboarding/test_runtime_runner.py \
  chatbot/tests/onboarding/test_frontend_evaluator.py \
  chatbot/tests/onboarding/test_backend_evaluator.py \
  chatbot/tests/onboarding/test_runtime_completion_runner.py \
  chatbot/tests/onboarding/test_orchestrator.py \
  chatbot/tests/onboarding/test_agent_integration.py \
  chatbot/tests/onboarding/test_exporter.py -q
```

Expected: PASS

**Step 3: Run py_compile sanity**

```bash
uv run python -m py_compile \
  chatbot/scripts/run_onboarding_generation.py \
  chatbot/src/onboarding/orchestrator.py \
  chatbot/src/onboarding/runtime_completion_runner.py \
  chatbot/src/onboarding/runtime_repair_toolkit.py \
  chatbot/src/onboarding/failure_classifier.py \
  chatbot/src/onboarding/recovery_planner.py
```

Expected: exit 0
