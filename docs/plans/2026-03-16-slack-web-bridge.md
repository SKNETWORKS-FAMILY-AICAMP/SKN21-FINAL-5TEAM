# Slack Web Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** onboarding run이 실행되면 실제 Slack 채널/thread에 root, agent, approval 메시지를 바로 발행한다.

**Architecture:** `InMemorySlackBridge` 인터페이스를 유지한 채 `SlackWebBridge` 구현체를 추가한다. 이 bridge는 `chat.postMessage`로 root message를 발행하고, 반환된 `thread_ts`를 저장해 이후 agent/approval 메시지를 같은 thread로 보낸다. Socket Mode gateway는 approval decision이 기록되면 같은 thread에 decision message를 추가로 남긴다.

**Tech Stack:** Python, slack-sdk WebClient, pytest, existing onboarding orchestrator

---

### Task 1: Add Slack Web Bridge

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing test**

```python
def test_slack_web_bridge_stores_thread_ts_from_root_message():
    client = FakeWebClient(ts="1710000000.100")
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)

    bridge.post_run_root(...)
    bridge.post_agent_message(...)

    assert client.calls[1]["thread_ts"] == "1710000000.100"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -v`
Expected: FAIL because `SlackWebBridge` does not exist

**Step 3: Write minimal implementation**

- `SlackWebBridge` 추가
- `post_run_root()`에서 root `ts` 저장
- agent/approval/decision 메시지를 `thread_ts`로 발행

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_slack_bridge.py
git commit -m "onboarding: add slack web bridge"
```

### Task 2: Format Real Slack Button Blocks

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing test**

```python
def test_slack_web_bridge_posts_block_kit_approval_message():
    payload = bridge.post_approval_request(...)
    blocks = client.calls[-1]["blocks"]

    assert blocks[-1]["type"] == "actions"
    assert blocks[-1]["elements"][0]["text"]["text"] == "Approve"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -v`
Expected: FAIL because current payload is internal shape only

**Step 3: Write minimal implementation**

- Slack Web API용 `text` + `blocks` payload 생성
- internal payload contract은 유지
- buttons는 `button` element 형태로 발행

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_slack_bridge.py
git commit -m "onboarding: format slack approval buttons as block kit"
```

### Task 3: Wire Slack Web Bridge Into Onboarding Runner

**Files:**
- Modify: `chatbot/scripts/run_onboarding_generation.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`

**Step 1: Write the failing test**

```python
def test_cli_can_build_slack_web_bridge_from_env():
    bridge = build_slack_bridge_from_env(channel="#onboarding-runs", web_client=fake_client)
    assert isinstance(bridge, SlackWebBridge)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: FAIL because generation CLI cannot create a real slack bridge

**Step 3: Write minimal implementation**

- generation CLI에 `--slack-channel` 추가
- env에서 `SLACK_BOT_TOKEN` 읽어 `SlackWebBridge` 생성
- 없으면 기존 동작 유지

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/scripts/run_onboarding_generation.py chatbot/tests/onboarding/test_cli_runner.py
git commit -m "onboarding: wire slack web bridge into generation cli"
```

### Task 4: Post Decision Messages From Gateway

**Files:**
- Modify: `chatbot/src/onboarding/slack_socket_gateway.py`
- Modify: `chatbot/scripts/run_slack_socket_gateway.py`
- Modify: `chatbot/tests/onboarding/test_slack_socket_gateway.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`

**Step 1: Write the failing test**

```python
def test_gateway_posts_decision_message_when_bridge_present():
    handle_interactive_action(..., store=store, bridge=bridge)
    assert client.calls[-1]["text"].startswith("Approval decision recorded")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_socket_gateway.py chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: FAIL because gateway only updates store

**Step 3: Write minimal implementation**

- `handle_interactive_action()`에 optional bridge 추가
- decision recorded 메시지 발행
- gateway runner가 env에서 `SLACK_BOT_TOKEN` 읽어 bridge 생성 가능하게 추가

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_socket_gateway.py chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/slack_socket_gateway.py chatbot/scripts/run_slack_socket_gateway.py chatbot/tests/onboarding/test_slack_socket_gateway.py chatbot/tests/onboarding/test_cli_runner.py
git commit -m "onboarding: post slack decision messages from gateway"
```

### Task 5: Add Runtime Logs

**Files:**
- Modify: `chatbot/scripts/run_slack_socket_gateway.py`
- Modify: `chatbot/tests/onboarding/test_cli_runner.py`

**Step 1: Write the failing test**

```python
def test_run_gateway_logs_connection_lifecycle(capsys):
    run_gateway(..., connect=False, logger=fake_logger)
    assert "gateway started" in fake_logger.messages[0]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: FAIL because gateway emits no logs

**Step 3: Write minimal implementation**

- startup/connect/action log 추가
- stdout logger 기본값 사용

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/scripts/run_slack_socket_gateway.py chatbot/tests/onboarding/test_cli_runner.py
git commit -m "onboarding: add slack gateway runtime logs"
```

### Task 6: Verify Direct Slack Publishing Path

**Files:**
- Modify as needed from earlier tasks

**Step 1: Run focused tests**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_slack_socket_gateway.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_cli_runner.py -v`
Expected: PASS

**Step 2: Run compile verification**

Run: `uv run python -m py_compile chatbot/src/onboarding/slack_bridge.py chatbot/src/onboarding/slack_socket_gateway.py chatbot/src/onboarding/orchestrator.py chatbot/scripts/run_onboarding_generation.py chatbot/scripts/run_slack_socket_gateway.py`
Expected: no output

**Step 3: Record remaining gaps**

남은 갭:

- 실제 channel 초대 여부/권한 누락 시 runtime error handling 강화 필요
- thread mapping persistence는 메모리 중심이라 프로세스 재시작 시 제한 있음
- message update/edit는 아직 미지원

**Step 4: Commit**

```bash
git add chatbot/src/onboarding chatbot/tests/onboarding chatbot/scripts/run_onboarding_generation.py chatbot/scripts/run_slack_socket_gateway.py
git commit -m "onboarding: publish live slack thread messages"
```
