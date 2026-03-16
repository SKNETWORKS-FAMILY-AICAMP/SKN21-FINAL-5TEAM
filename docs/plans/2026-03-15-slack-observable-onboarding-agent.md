# Slack-Observable Onboarding Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Slack에서 관찰 가능하고 중요 승인 지점만 사람 개입을 받는 범용 온보딩 agent 골격을 구현한다.

**Architecture:** 기존 overlay-based onboarding MVP 위에 deterministic orchestrator 상태머신과 Slack-observable event layer를 얹는다. 역할별 subagent는 내부적으로 하나의 실행 엔진이 역할 프롬프트를 바꿔 호출하는 구조로 시작하고, 결과는 구조화된 이벤트와 Slack thread 메시지로 노출한다.

**Tech Stack:** Python, Pydantic, existing onboarding modules, pytest

---

### Task 1: Run and Event Schema

**Files:**
- Create: `chatbot/src/onboarding/agent_contracts.py`
- Test: `chatbot/tests/onboarding/test_agent_contracts.py`

**Step 1: Write the failing test**

테스트에 아래를 검증한다.

- `RunState` enum이 설계된 상태값을 포함한다.
- `ApprovalType` enum이 `analysis`, `apply`, `export`를 포함한다.
- `AgentMessage`가 `role`, `claim`, `evidence`, `confidence`, `risk`, `next_action`, `blocking_issue`를 검증한다.
- `RunEvent`가 `event_type`, `run_id`, `state`, `payload`, `created_at`을 가진다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_contracts.py -v`

**Step 3: Write minimal implementation**

Pydantic model과 enum을 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_contracts.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/agent_contracts.py chatbot/tests/onboarding/test_agent_contracts.py
git commit -m "onboarding: add agent event contracts"
```

### Task 2: Slack Bridge Interface

**Files:**
- Create: `chatbot/src/onboarding/slack_bridge.py`
- Test: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing test**

테스트에 아래를 검증한다.

- root message payload 생성
- agent message payload 생성
- approval request payload 생성
- thread key가 `run_id` 단위로 유지됨

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -v`

**Step 3: Write minimal implementation**

실제 Slack API 호출은 아직 넣지 말고, payload builder와 in-memory publisher를 만든다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_slack_bridge.py
git commit -m "onboarding: add slack bridge interface"
```

### Task 3: Deterministic Orchestrator State Machine

**Files:**
- Create: `chatbot/src/onboarding/agent_orchestrator.py`
- Test: `chatbot/tests/onboarding/test_agent_orchestrator.py`

**Step 1: Write the failing test**

테스트에 아래를 검증한다.

- `queued -> analyzing -> planning -> generating`
- `awaiting_apply_approval`
- `applying -> validating`
- 실패 시 `diagnosing`
- retry budget 초과 시 `human_review_required`

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_orchestrator.py -v`

**Step 3: Write minimal implementation**

상태 전이 규칙과 budget 카운터를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_orchestrator.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/agent_orchestrator.py chatbot/tests/onboarding/test_agent_orchestrator.py
git commit -m "onboarding: add orchestrator state machine"
```

### Task 4: Role Runner Skeleton

**Files:**
- Create: `chatbot/src/onboarding/role_runner.py`
- Test: `chatbot/tests/onboarding/test_role_runner.py`

**Step 1: Write the failing test**

테스트에 아래를 검증한다.

- `Analyzer`, `Planner`, `Generator`, `Validator`, `Diagnostician` role dispatch
- 각 role 결과가 `AgentMessage` 형식으로 normalize 됨
- role 결과가 `RunEvent` payload로 감쌀 수 있음

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_role_runner.py -v`

**Step 3: Write minimal implementation**

LLM 호출은 stub 또는 fake responder로 시작하고, 역할별 prompt key만 분리한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_role_runner.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/role_runner.py chatbot/tests/onboarding/test_role_runner.py
git commit -m "onboarding: add role runner skeleton"
```

### Task 5: Approval Gate Handling

**Files:**
- Modify: `chatbot/src/onboarding/agent_orchestrator.py`
- Create: `chatbot/tests/onboarding/test_approval_gates.py`

**Step 1: Write the failing test**

테스트에 아래를 검증한다.

- analysis approval request 생성
- apply approval request 생성
- export approval request 생성
- 승인 전에는 다음 상태로 이동하지 않음
- 승인 후 정상 진행

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_gates.py -v`

**Step 3: Write minimal implementation**

approval event 발행과 승인 입력 처리 메서드를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_gates.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/agent_orchestrator.py chatbot/tests/onboarding/test_approval_gates.py
git commit -m "onboarding: add approval gate handling"
```

### Task 6: Integrate Existing Onboarding Pipeline

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/scripts/run_onboarding_generation.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

테스트에 아래를 검증한다.

- 기존 onboarding generation 결과가 agent orchestrator 이벤트로 감싸짐
- Slack bridge에 root/agent/approval 메시지가 순서대로 쌓임
- approval 없는 단계는 자동 진행

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

**Step 3: Write minimal implementation**

기존 generation flow를 새 orchestrator 상태머신 아래에서 호출한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_agent_integration.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/scripts/run_onboarding_generation.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "onboarding: integrate agent orchestration"
```

### Task 7: Verification

**Files:**
- Modify as needed from earlier tasks

**Step 1: Run focused onboarding tests**

Run:

```bash
uv run pytest --noconftest chatbot/tests/onboarding -q
```

Expected: PASS

**Step 2: Run compile verification**

Run:

```bash
uv run python -m py_compile chatbot/src/onboarding/*.py chatbot/scripts/run_onboarding_generation.py
```

Expected: no output

**Step 3: Record remaining gaps**

문서나 final summary에 아래를 명시한다.

- 실제 Slack API 미연동
- 실제 LLM role prompt 미연동
- approval 입력은 local stub 또는 CLI 수준

**Step 4: Commit**

```bash
git add chatbot/src/onboarding chatbot/tests/onboarding chatbot/scripts/run_onboarding_generation.py
git commit -m "onboarding: add slack-observable agent skeleton"
```
