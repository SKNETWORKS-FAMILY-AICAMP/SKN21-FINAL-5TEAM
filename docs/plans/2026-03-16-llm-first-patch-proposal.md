# LLM-First Patch Proposal Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `patch-proposal.json` 생성을 LLM-first로 바꾸고 fallback/provenance를 남긴다.

**Architecture:** deterministic codebase map은 유지하고, patch proposal만 LLM-first runner로 생성한다. LLM 응답은 schema + candidate validation을 거치고 실패 시 기존 proposal builder를 fallback으로 사용한다.

**Tech Stack:** Python, pydantic, pytest, onboarding orchestrator

---

### Task 1: Proposal runner 테스트 추가

**Files:**
- Modify: `chatbot/tests/onboarding/test_patch_planner.py`

**Step 1: Write failing tests**
- LLM proposal success
- invalid JSON fallback
- invalid target path fallback

**Step 2: Run focused tests to verify failure**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_patch_planner.py -k 'llm_first_patch_proposal' -v`

**Step 3: Implement minimal runner**

**Step 4: Re-run focused tests**

**Step 5: Commit**

### Task 2: Orchestrator integration

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`

**Step 1: Write failing integration tests**
- `use_llm_roles=True`에서 patch proposal execution artifact 생성

**Step 2: Run tests to verify failure**

**Step 3: Wire runner into onboarding flow**

**Step 4: Re-run tests**

### Task 3: Slack / result surface

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Add failing test for summary exposure**

**Step 2: Implement minimal summary support**

**Step 3: Re-run focused tests**

### Task 4: Full verification

**Files:**
- Verify existing onboarding suite

**Step 1: Run full onboarding regression**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_patch_comparison.py chatbot/tests/onboarding/test_llm_patch_draft.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_llm_role_runner.py chatbot/tests/onboarding/test_frontend_mount_generator.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_backend_evaluator.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_cli_runner.py chatbot/tests/onboarding/test_exporter.py -v`

**Step 2: Run compile verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_slack_bridge.py`
