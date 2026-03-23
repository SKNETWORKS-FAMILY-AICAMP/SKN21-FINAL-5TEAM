# Slack Socket Approval Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Slack Socket Mode와 버튼 승인 흐름을 onboarding orchestrator의 approval gate에 실제로 연결한다.

**Architecture:** Slack 수신은 별도 gateway 프로세스로 분리하고, orchestrator와는 file-based approval store로 연결한다. Slack bridge는 interactive button payload를 만들고, gateway는 action payload를 받아 decision을 기록하며, orchestrator는 polling으로 결정을 consume한다.

**Tech Stack:** Python, pytest, JSON file store, Slack SDK Socket Mode/Web API wrapper, existing onboarding orchestrator

---

### Task 1: Create Approval Store

**Files:**
- Create: `chatbot/src/onboarding/approval_store.py`
- Create: `chatbot/tests/onboarding/test_approval_store.py`

**Step 1: Write the failing test**

```python
def test_approval_store_records_and_consumes_decision(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)
    store.create_request(run_id="food-run-001", approval_type="apply")
    store.record_decision(
        run_id="food-run-001",
        approval_type="apply",
        decision="approve",
        actor="U123",
    )

    decision = store.get_decision(run_id="food-run-001", approval_type="apply")

    assert decision["status"] == "approved"
    assert decision["actor"] == "U123"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_store.py -v`
Expected: FAIL because `ApprovalStore` does not exist

**Step 3: Write minimal implementation**

- `ApprovalStore` 구현
- `create_request`, `record_decision`, `get_decision`, `consume_decision`
- JSON 파일 저장
- `request_id = f"{run_id}:{approval_type}"` 사용

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_store.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/approval_store.py chatbot/tests/onboarding/test_approval_store.py
git commit -m "onboarding: add approval store for slack decisions"
```

### Task 2: Add Slack Button Payload Builder

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing test**

```python
def test_slack_bridge_builds_button_actions_for_approval_request():
    payload = bridge.post_approval_request(...)
    actions = payload["message"]["actions"]

    assert actions[0]["text"] == "Approve"
    assert actions[0]["value"]["decision"] == "approve"
    assert actions[1]["value"]["decision"] == "reject"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -v`
Expected: FAIL because approval payload has no button actions

**Step 3: Write minimal implementation**

- approval request payload에 `actions` 추가
- 각 action value에 `run_id`, `approval_type`, `decision`, `request_id` 포함
- in-memory bridge도 같은 구조 유지

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_slack_bridge.py
git commit -m "onboarding: add slack approval button payloads"
```

### Task 3: Create Slack Socket Gateway Action Handler

**Files:**
- Create: `chatbot/src/onboarding/slack_socket_gateway.py`
- Create: `chatbot/tests/onboarding/test_slack_socket_gateway.py`

**Step 1: Write the failing test**

```python
def test_gateway_records_button_click_decision(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)
    store.create_request(run_id="food-run-001", approval_type="apply")

    handle_action(
        payload={
            "user": {"id": "U123"},
            "actions": [
                {"value": {"run_id": "food-run-001", "approval_type": "apply", "decision": "approve"}}
            ],
        },
        store=store,
    )

    decision = store.get_decision(run_id="food-run-001", approval_type="apply")
    assert decision["status"] == "approved"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_socket_gateway.py -v`
Expected: FAIL because action handler module does not exist

**Step 3: Write minimal implementation**

- action payload parser 구현
- approve/reject 기록
- pending이 아닌 상태에서는 no-op
- simple ack payload 반환

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_socket_gateway.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/slack_socket_gateway.py chatbot/tests/onboarding/test_slack_socket_gateway.py
git commit -m "onboarding: add slack socket action handler"
```

### Task 4: Poll Approval Store From Orchestrator

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/agent_orchestrator.py`
- Modify: `chatbot/tests/onboarding/test_approval_gates.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

```python
def test_orchestrator_applies_store_decision_for_apply_gate(tmp_path: Path):
    store = ApprovalStore(root=tmp_path)
    store.create_request(run_id="food-run-001", approval_type="apply")
    store.record_decision(
        run_id="food-run-001",
        approval_type="apply",
        decision="approve",
        actor="U123",
    )

    result = run_onboarding_generation(..., approval_store=store)

    assert result["current_state"] in {"applying", "completed"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_gates.py chatbot/tests/onboarding/test_agent_integration.py -v`
Expected: FAIL because orchestrator cannot read approval store

**Step 3: Write minimal implementation**

- orchestrator 인자로 `approval_store` 추가
- gate 진입 시 store에 pending request 생성
- explicit CLI approval가 없으면 store decision 조회
- consume 후 상태 반영

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_gates.py chatbot/tests/onboarding/test_agent_integration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/agent_orchestrator.py chatbot/tests/onboarding/test_approval_gates.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "onboarding: wire approval store into orchestrator"
```

### Task 5: Add Socket Gateway Runner CLI

**Files:**
- Create: `chatbot/scripts/run_slack_socket_gateway.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`

**Step 1: Write the failing test**

```python
def test_gateway_cli_parser_accepts_socket_mode_env_flags():
    parser = build_parser()
    args = parser.parse_args(["--channel", "#onboarding-runs", "--approval-store-root", "generated/approvals"])
    assert args.channel == "#onboarding-runs"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: FAIL because gateway CLI does not exist

**Step 3: Write minimal implementation**

- `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` env 사용
- `--channel`, `--approval-store-root` 지원
- action handler loop 진입점 추가

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/scripts/run_slack_socket_gateway.py chatbot/tests/onboarding/test_cli_runner.py
git commit -m "onboarding: add slack socket gateway cli"
```

### Task 6: Verify End-to-End Slack Approval Path

**Files:**
- Modify as needed from earlier tasks

**Step 1: Run focused tests**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_store.py chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_slack_socket_gateway.py chatbot/tests/onboarding/test_approval_gates.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: PASS

**Step 2: Run compile verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/*.py chatbot/scripts/run_onboarding_generation.py chatbot/scripts/run_slack_socket_gateway.py`
Expected: no output

**Step 3: Record remaining gaps**

남은 갭:

- 실제 Slack app 설치와 권한 설정 문서화 필요
- 장기 polling 대신 event-driven approval wake-up 없음
- 분산 환경용 락/transaction 없음

**Step 4: Commit**

```bash
git add chatbot/src/onboarding chatbot/tests/onboarding chatbot/scripts/run_slack_socket_gateway.py
git commit -m "onboarding: add slack socket approval flow"
```
