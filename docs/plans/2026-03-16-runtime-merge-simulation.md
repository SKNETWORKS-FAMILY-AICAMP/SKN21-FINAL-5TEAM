# Runtime Merge Simulation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 원본을 수정하지 않고 `generated/files`, `generated/patches`, proposal patch를 runtime workspace에 통합 적용한 뒤 post-merge 상태처럼 평가한다.

**Architecture:** runtime workspace를 단순 복사본이 아니라 simulated merge environment로 취급한다. onboarding 실행은 원본 read-only 분석 후 생성 산출물을 runtime workspace에 순차 적용하고, 그 통합 결과를 smoke/build/evaluation 대상으로 삼는다.

**Tech Stack:** Python, pytest, existing onboarding runtime runner, patch/export pipeline

---

### Task 1: Add merge simulation report tests

**Files:**
- Modify: `chatbot/tests/onboarding/test_runtime_runner.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing tests**

- runtime merge simulation report is written under `reports/merge-simulation.json`
- report lists applied overlay files and patch artifacts

**Step 2: Run tests to verify they fail**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_agent_integration.py -v`

**Step 3: Write minimal implementation**

- add simulation function that records which generated assets were applied into runtime workspace
- persist merge simulation report during onboarding run

**Step 4: Run tests to verify they pass**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_agent_integration.py -v`

### Task 2: Evaluate simulated merge output

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/runtime_runner.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing tests**

- post-merge evaluation reads merge simulation report
- run result exposes `merge_simulation_path`

**Step 2: Run tests to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

**Step 3: Write minimal implementation**

- wire merge simulation artifact into orchestrator run result
- ensure evaluation runs against merged runtime workspace only

**Step 4: Run tests to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

### Task 3: Verify focused slice

**Files:**
- Modify as needed from earlier tasks

**Step 1: Run focused tests**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_patch_apply.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py -v`

**Step 2: Run compile verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/runtime_runner.py chatbot/src/onboarding/orchestrator.py chatbot/scripts/run_onboarding_generation.py`

**Step 3: Record remaining gaps**

- framework-aware build/test beyond smoke is still pending
- proposal patch generation remains heuristic until actual unified diff generation is added
