# LLM-First Role Runner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 각 onboarding role이 기본적으로 LLM을 먼저 사용하고, 실패 시 deterministic fallback으로 안전하게 진행되게 만든다.

**Architecture:** 기존 `LLMRoleRunner`와 `RoleRunner`를 조합한 `ReliableLLMRoleRunner`를 추가한다. role 실행 provenance를 `llm-role-execution.json`으로 저장하고, orchestrator와 Slack summary가 이 artifact를 노출하도록 연결한다.

**Tech Stack:** Python, LangChain message interface, existing onboarding orchestrator/test suite, pytest

---

### Task 1: Reliable runner 테스트 추가

**Files:**
- Test: `chatbot/tests/onboarding/test_llm_role_runner.py`

**Step 1: Write the failing test**
- LLM 성공 시 `source == "llm"`이 기록되는 테스트 추가
- invalid JSON 시 fallback payload가 반환되고 `source == "fallback"`이 기록되는 테스트 추가
- missing required field 시 fallback으로 전환되는 테스트 추가

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_llm_role_runner.py -k "reliable" -v`

Expected: FAIL because `ReliableLLMRoleRunner` does not exist yet

**Step 3: Write minimal implementation**
- `chatbot/src/onboarding/role_runner.py`에 `ReliableLLMRoleRunner` 추가
- `run_role()`는 `llm_runner.run_role()`를 먼저 시도
- 예외 또는 payload validation 실패 시 `fallback_runner.run_role()` 사용
- `execution_log` 조회 메서드 제공

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_llm_role_runner.py -k "reliable" -v`

Expected: PASS

### Task 2: orchestrator에 reliable runner 연결

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**
- `use_llm_roles=True` + 실패하는 fake LLM fixture로 run이 `completed`까지 가고 fallback 기록이 생기는 테스트 추가
- `llm-role-execution.json`이 생성되는 테스트 추가

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -k "llm_role_execution" -v`

Expected: FAIL because report is not generated yet

**Step 3: Write minimal implementation**
- `use_llm_roles=True`일 때 `ReliableLLMRoleRunner` 사용
- 종료 시 `reports/llm-role-execution.json` 저장
- `_build_run_result()`와 `_existing_summary_artifacts()`에 artifact 경로 추가

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -k "llm_role_execution" -v`

Expected: PASS

### Task 3: Slack summary 노출

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Test: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing test**
- `llm-role-execution.json`이 artifact로 주어졌을 때 summary에 fallback 여부와 llm/fallback 집계가 노출되는 테스트 추가

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -k "llm_role_execution" -v`

Expected: FAIL because summary does not read the artifact yet

**Step 3: Write minimal implementation**
- summary builder가 `llm-role-execution.json`을 읽어
  - llm success count
  - fallback count
  - fallback된 role 이름
  를 노출

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -k "llm_role_execution" -v`

Expected: PASS

### Task 4: CLI 회귀 및 결과 경로 반영

**Files:**
- Modify: `chatbot/scripts/run_onboarding_generation.py`
- Test: `chatbot/tests/onboarding/test_cli_runner.py`

**Step 1: Write the failing test**
- CLI 결과 JSON에 `llm_role_execution_path`가 포함되는 테스트 추가

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -k "llm_role_execution_path" -v`

Expected: FAIL because path is not returned yet

**Step 3: Write minimal implementation**
- CLI는 기존 옵션을 유지
- 결과 JSON에 new path를 그대로 전달

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -k "llm_role_execution_path" -v`

Expected: PASS

### Task 5: Full regression

**Files:**
- Verify only

**Step 1: Run targeted suite**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_llm_role_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_cli_runner.py -v`

Expected: PASS

**Step 2: Run broad onboarding suite**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_patch_comparison.py chatbot/tests/onboarding/test_llm_patch_draft.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_llm_role_runner.py chatbot/tests/onboarding/test_frontend_mount_generator.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_backend_evaluator.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_cli_runner.py chatbot/tests/onboarding/test_exporter.py -v`

Expected: PASS

**Step 3: Run compile verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/role_runner.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/slack_bridge.py chatbot/scripts/run_onboarding_generation.py`

Expected: exit code 0
