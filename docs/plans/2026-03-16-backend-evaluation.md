# Backend Evaluation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** merge simulation 결과를 대상으로 백엔드 Python 검증 리포트를 생성하고 onboarding 결과에 노출한다.

**Architecture:** runtime workspace에서 Python 백엔드 파일 목록을 수집하고 `py_compile` 기반 검증을 실행해 `backend-evaluation.json`에 기록한다. 이 평가는 기존 smoke 결과와 별도로 저장되며 merge simulation 이후 단계에서 수행된다.

**Tech Stack:** Python, pytest, py_compile, existing onboarding orchestrator/runtime pipeline

---

### Task 1: Add backend evaluation tests

**Files:**
- Create: `chatbot/tests/onboarding/test_backend_evaluator.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing tests**

- backend evaluator writes a report with checked files and pass/fail summary
- onboarding run returns `backend_evaluation_path`

**Step 2: Run tests to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_backend_evaluator.py chatbot/tests/onboarding/test_agent_integration.py -v`

**Step 3: Write minimal implementation**

- add backend evaluator module
- wire evaluation after merge simulation

**Step 4: Run tests to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_backend_evaluator.py chatbot/tests/onboarding/test_agent_integration.py -v`

### Task 2: Verify focused slice

**Files:**
- Modify as needed from earlier tasks

**Step 1: Run focused tests**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_backend_evaluator.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py -v`

**Step 2: Run compile verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/backend_evaluator.py chatbot/src/onboarding/orchestrator.py chatbot/scripts/run_onboarding_generation.py`

**Step 3: Record remaining gaps**

- true import graph/runtime dependency evaluation is still pending
- frontend build evaluation is not yet included
