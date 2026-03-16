# Context-Aware Patch Generation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 원본 사이트를 수정하지 않고 로컬 코드 문맥 기반의 patch proposal artifact를 `generated/<site>/<run-id>/` 아래에 생성한다.

**Architecture:** 기존 템플릿 산출 전 단계에 read-only codebase mapping과 patch planning artifact를 추가한다. 첫 단계에서는 실제 unified diff를 완성하기보다, 원본 파일 근거와 변경 의도를 담은 patch proposal JSON 및 supporting file draft를 생성해 기존 runtime/export 흐름과 병행한다.

**Tech Stack:** Python, pytest, existing onboarding orchestrator, generated/runtime artifact pipeline

---

### Task 1: Add codebase mapping artifact

**Files:**
- Create: `chatbot/src/onboarding/codebase_mapper.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

- assert onboarding run writes a `reports/codebase-map.json`
- assert map references real source files and candidate edit targets

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

**Step 3: Write minimal implementation**

- build a read-only codebase mapper from local source files
- save mapping artifact under generated reports

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

### Task 2: Add patch proposal artifact

**Files:**
- Create: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/role_runner.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

- assert onboarding run writes `reports/patch-proposal.json`
- assert proposal contains target files, reasons, and intended edits derived from source evidence

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

**Step 3: Write minimal implementation**

- create patch planner artifact from codebase map + analysis
- expose planner/generator context fields for target files and patch intents

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

### Task 3: Surface proposal through CLI and Slack

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/scripts/run_onboarding_generation.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing test**

- assert CLI result returns `patch_proposal_path`
- assert Slack agent/planning messages summarize target files or patch intents

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py chatbot/tests/onboarding/test_slack_bridge.py -v`

**Step 3: Write minimal implementation**

- include artifact path in run result
- surface proposal summary in Slack-visible messages without changing approval semantics

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py chatbot/tests/onboarding/test_slack_bridge.py -v`

### Task 4: Verify focused slice

**Files:**
- Modify as needed from earlier tasks

**Step 1: Run focused tests**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_slack_socket_gateway.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py chatbot/tests/onboarding/test_exporter.py -v`

**Step 2: Run compile verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/codebase_mapper.py chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/role_runner.py chatbot/scripts/run_onboarding_generation.py chatbot/src/onboarding/slack_bridge.py`

**Step 3: Record remaining gaps**

- real unified diff generation against arbitrary files is still pending
- planner quality still depends on shallow heuristics until richer source graphing is added
- runtime apply still uses template-era overlay assumptions for some artifact classes
