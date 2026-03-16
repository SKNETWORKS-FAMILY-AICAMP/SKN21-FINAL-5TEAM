# Slack Approval Resume Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Slack approval 버튼 클릭이 실제 실행 제어로 이어지도록 generation CLI를 pending/resume 방식으로 확장한다.

**Architecture:** generation CLI는 `ApprovalStore`를 사용해 approval 요청을 파일로 기록하고, decision이 없으면 `pending_approval` 상태로 종료한다. 같은 CLI에 `--resume-run-id`를 추가해 기존 run 산출물을 기반으로 다음 approval 단계부터 재개하며, Slack thread는 동일 run id 기준으로 이어진다.

**Tech Stack:** Python, pytest, existing onboarding orchestrator, file-based ApprovalStore

---

### Task 1: Add pending approval regression tests

**Files:**
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`

**Step 1: Write the failing tests**

- generation with `slack_bridge + approval_store` returns `pending_approval` instead of auto-completing
- CLI parser/execution supports `--approval-store-root` and `--resume-run-id`

**Step 2: Run tests to verify they fail**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py -v`

**Step 3: Write minimal implementation**

- wire approval store into generation CLI
- expose resume flags in parser

**Step 4: Run tests to verify they pass**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py -v`

### Task 2: Make orchestrator stop on pending and resume later

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/agent_orchestrator.py`

**Step 1: Write the failing tests**

- orchestrator stops after analysis/apply/export request when waiting on store
- resume continues from the correct next stage after a consumed decision

**Step 2: Run tests to verify they fail**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

**Step 3: Write minimal implementation**

- create approval requests even when Slack bridge is enabled
- no implicit approve when an approval store is present
- add resume path that reconstructs stage from existing artifacts and consumed approvals

**Step 4: Run tests to verify they pass**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

### Task 3: Verify end-to-end CLI flow

**Files:**
- Modify as needed from earlier tasks

**Step 1: Run focused tests**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_slack_socket_gateway.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py chatbot/tests/onboarding/test_exporter.py -v`

**Step 2: Run compile verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/agent_orchestrator.py chatbot/scripts/run_onboarding_generation.py chatbot/src/onboarding/slack_bridge.py chatbot/src/onboarding/slack_socket_gateway.py chatbot/src/onboarding/exporter.py`

**Step 3: Record remaining gaps**

- multi-process resume collision handling is still minimal
- long-running in-process wait mode is intentionally not implemented
