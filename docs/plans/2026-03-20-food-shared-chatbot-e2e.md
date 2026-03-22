# Food Shared Chatbot E2E Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make generated `food` apps mount a real shared chatbot UI, talk to the standalone chatbot server, and route tool execution through the existing `site-a` adapter stack while keeping conversation state only in browser memory.

**Architecture:** Add a code-owned shared chatbot asset registry for onboarding, reuse the standalone FastAPI server as the only chat backend, emit a real host-side widget instead of the placeholder `Chatbot` label, and update runtime validation to boot the chatbot server alongside the generated frontend and backend. The agent continues to discover patch targets, but code owns adapter selection, shared widget source selection, and chat transport configuration.

**Tech Stack:** FastAPI, React, Django auth bridge, existing adapter registry, pytest, onboarding generator pipeline

---

### Task 1: Codify Shared Chatbot Asset And Site Routing Rules

**Files:**
- Create: `chatbot/src/onboarding/shared_chatbot_assets.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/frontend_generator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_integration_contracts.py`

**Step 1: Write the failing test**

Add a generator test that proves `food` resolves to `site-a` and that frontend generation uses a code-owned shared chatbot asset definition instead of a hardcoded placeholder string.

```python
def test_food_widget_generation_uses_shared_chatbot_contract(tmp_path: Path) -> None:
    config = resolve_shared_chatbot_assets(site_name="food")
    assert config.site_id == "site-a"
    assert config.stream_path == "/api/v1/chat/stream"
    assert "shared widget" in config.source_label
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_template_generator.py -k shared_chatbot_contract -q`

Expected: FAIL because onboarding still generates a placeholder widget and does not expose a shared asset registry.

**Step 3: Write minimal implementation**

- Create `shared_chatbot_assets.py` with a small typed registry such as:

```python
SHARED_CHATBOT_SITES = {
    "food": {"site_id": "site-a"},
    "bilyeo": {"site_id": "site-b"},
    "ecommerce": {"site_id": "site-c"},
}
```

- Add shared transport defaults:

```python
DEFAULT_SHARED_CHATBOT_HOST = {
    "auth_bootstrap_path": "/api/chat/auth-token",
    "stream_path": "/api/v1/chat/stream",
    "chatbot_api_base_default": "http://localhost:8100",
}
```

- Make `template_generator.py` and `frontend_generator.py` read from that registry instead of embedding independent constants.

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_template_generator.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_integration_contracts.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/shared_chatbot_assets.py chatbot/src/onboarding/template_generator.py chatbot/src/onboarding/frontend_generator.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_integration_contracts.py
git commit -m "feat: codify shared chatbot asset routing"
```

### Task 2: Expose The Shared Streaming Transport From The Standalone Chatbot Server

**Files:**
- Modify: `chatbot/server_fastapi.py`
- Modify: `chatbot/src/api/v1/endpoints/chat.py`
- Modify: `chatbot/src/core/config.py`
- Test: `chatbot/tests/api/test_onboarding_run_stream.py`
- Test: `chatbot/tests/test_chat_site_routing.py`
- Test: `chatbot/tests/test_shared_widget_transport.py`

**Step 1: Write the failing test**

Add a server test that mounts the standalone app and proves the shared widget default stream path is reachable.

```python
def test_standalone_server_exposes_shared_stream_route(client):
    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "hello", "site_id": "site-a", "access_token": "bridge-token"},
    )
    assert response.status_code != 404
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/api/test_onboarding_run_stream.py -k standalone -q`

Expected: FAIL because `chatbot/server_fastapi.py` does not yet include the shared streaming router.

**Step 3: Write minimal implementation**

- Include the shared chat router in `chatbot/server_fastapi.py`.
- Keep `/api/chat` for backward compatibility, but make `/api/v1/chat/stream` the canonical frontend path.
- Move the default local base URL from `9000` assumptions to `8100` in code-owned config and tests.

```python
from chatbot.src.api.v1.endpoints.chat import router as chat_router

app.include_router(chat_router, prefix=f"{settings.API_V1_STR}/chat")
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/api/test_onboarding_run_stream.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_chat_site_routing.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_shared_widget_transport.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/server_fastapi.py chatbot/src/api/v1/endpoints/chat.py chatbot/src/core/config.py chatbot/tests/api/test_onboarding_run_stream.py chatbot/tests/test_chat_site_routing.py chatbot/tests/test_shared_widget_transport.py
git commit -m "feat: expose shared streaming transport on standalone server"
```

### Task 3: Replace The Generated Placeholder Widget With A Real Hosted Chat UI

**Files:**
- Create: `chatbot/src/onboarding/shared_widget_runtime.py`
- Modify: `chatbot/src/onboarding/frontend_generator.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`
- Test: `chatbot/tests/test_site_a_shared_widget_runtime.py`

**Step 1: Write the failing test**

Add a frontend generation test that asserts the generated widget contains an input, a send button, and a call to the shared stream path instead of returning a literal `Chatbot` node.

```python
def test_generated_shared_widget_contains_real_chat_ui(tmp_path: Path) -> None:
    artifact = generate_frontend_widget_artifact(run_root=tmp_path)
    content = Path(artifact["path"]).read_text(encoding="utf-8")
    assert "placeholder" not in content.lower()
    assert "input" in content
    assert "/api/v1/chat/stream" in content
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_template_generator.py -k real_chat_ui -q`

Expected: FAIL because generated `SharedChatbotWidget.jsx` still renders only status text plus `Chatbot`.

**Step 3: Write minimal implementation**

- Create `shared_widget_runtime.py` as the code-owned source for a generated, framework-safe React widget.
- The generated widget should:
  - bootstrap against `/api/chat/auth-token`,
  - keep `messages`, `conversationState`, and `isSending` in React state,
  - post to the shared chatbot server stream endpoint,
  - render bot and user messages,
  - reset naturally on browser refresh.

```jsx
const [messages, setMessages] = useState([]);
const [conversationState, setConversationState] = useState(null);
const [input, setInput] = useState("");
```

- Keep imports local to the generated host app. Do not require `@shared-chatbot/*` alias support inside generated runtimes.

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_template_generator.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_frontend_evaluator.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_a_shared_widget_runtime.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/shared_widget_runtime.py chatbot/src/onboarding/frontend_generator.py chatbot/src/onboarding/orchestrator.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/test_site_a_shared_widget_runtime.py
git commit -m "feat: generate real hosted chat widget"
```

### Task 4: Lock Tool Routing To Site-A Adapter Selection Instead Of Prompt Hints

**Files:**
- Modify: `chatbot/src/adapters/setup.py`
- Modify: `chatbot/src/tools/adapter_order_tools.py`
- Modify: `chatbot/src/tools/service_tools.py`
- Test: `chatbot/tests/test_adapter_registry_tool_contract.py`
- Test: `chatbot/tests/test_food_adapter_order_tools.py`
- Test: `chatbot/tests/test_chat_site_routing.py`

**Step 1: Write the failing test**

Add a test proving a `site-a` chat turn with a bridge token routes through adapter-backed tools without any host-side adapter import.

```python
def test_site_a_chat_turn_uses_food_adapter(monkeypatch, client):
    seen = {}
    monkeypatch.setattr("chatbot.src.adapters.setup.get_adapter", lambda site_id: seen.setdefault("site_id", site_id) or FakeAdapter())
    response = client.post("/api/chat", json={"message": "recent orders", "site_id": "site-a", "access_token": "token"})
    assert response.status_code == 200
    assert seen["site_id"] == "site-a"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_chat_site_routing.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_adapter_registry_tool_contract.py -q`

Expected: FAIL because the current path is not fully locked to the code-owned site mapping contract.

**Step 3: Write minimal implementation**

- Make `site_id` the single input to adapter resolution.
- Ensure access token propagation flows from chat request into adapter-backed tool calls.
- Keep all host app code free of direct imports from `chatbot/src/adapters/site_a`.

```python
resolved_adapter = resolve_site_adapter(req.site_id)
user_info["access_token"] = req.access_token
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_chat_site_routing.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_adapter_registry_tool_contract.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_food_adapter_order_tools.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/adapters/setup.py chatbot/src/tools/adapter_order_tools.py chatbot/src/tools/service_tools.py chatbot/tests/test_adapter_registry_tool_contract.py chatbot/tests/test_food_adapter_order_tools.py chatbot/tests/test_chat_site_routing.py
git commit -m "feat: lock food chat turns to site-a adapter routing"
```

### Task 5: Boot The Standalone Chatbot Server During Runtime Validation

**Files:**
- Modify: `chatbot/src/onboarding/runtime_runner.py`
- Modify: `chatbot/src/onboarding/runtime_completion_runner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `.env.example`
- Modify: `chatbot/FASTAPI_SERVER_RUNBOOK.md`
- Test: `chatbot/tests/onboarding/test_runtime_runner.py`
- Test: `chatbot/tests/onboarding/test_runtime_completion_runner.py`

**Step 1: Write the failing test**

Add a runtime test proving the validation pipeline launches a third process for the chatbot server and injects the chat base URL into the host frontend environment.

```python
def test_runtime_validation_launches_chatbot_server(tmp_path: Path):
    result = run_runtime_validation(...)
    assert "chatbot" in result.processes
    assert result.frontend_env["REACT_APP_CHATBOT_API_BASE"] == "http://127.0.0.1:8100"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_runtime_runner.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_runtime_completion_runner.py -k chatbot -q`

Expected: FAIL because runtime validation currently starts only backend and frontend.

**Step 3: Write minimal implementation**

- Add a chatbot server launch step using `uv run uvicorn chatbot.server_fastapi:app --host 127.0.0.1 --port 8100`.
- Probe `GET /health` before declaring chat ready.
- Inject `REACT_APP_CHATBOT_API_BASE=http://127.0.0.1:8100` into generated frontend runtime.
- Document required local env variables without embedding real secrets.

```python
chatbot_env["FOOD_API_URL"] = "http://127.0.0.1:8000"
frontend_env["REACT_APP_CHATBOT_API_BASE"] = "http://127.0.0.1:8100"
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_runtime_runner.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_runtime_completion_runner.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_runner.py chatbot/src/onboarding/runtime_completion_runner.py chatbot/src/onboarding/orchestrator.py .env.example chatbot/FASTAPI_SERVER_RUNBOOK.md chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_runtime_completion_runner.py
git commit -m "feat: launch chatbot server during runtime validation"
```

### Task 6: Add End-To-End Food Chat Verification And Regression Coverage

**Files:**
- Modify: `chatbot/tests/test_site_a_shared_widget_runtime.py`
- Modify: `chatbot/tests/test_shared_widget_transport.py`
- Modify: `chatbot/tests/onboarding/test_smoke_runner.py`
- Modify: `chatbot/tests/onboarding/test_generator_golden_fixtures.py`
- Create: `chatbot/tests/onboarding/test_food_chatbot_contract.py`

**Step 1: Write the failing test**

Add an end-to-end regression that proves a generated `food` runtime can:

- authenticate the widget,
- send a real chat request to the standalone server,
- receive a bot response,
- clear state on refresh by starting with an empty message list.

```python
def test_food_chat_contract_round_trip():
    payload = run_food_shared_widget_runtime(...)
    assert payload["authenticated"] is True
    assert payload["chat_request"]["site_id"] == "site-a"
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["role"] == "bot"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_a_shared_widget_runtime.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_smoke_runner.py -k food_chat -q`

Expected: FAIL because the current runtime never reaches an actual chat round trip.

**Step 3: Write minimal implementation**

- Extend runtime tests from auth bootstrap only to message send and response render.
- Add a smoke-plan assertion for chatbot availability when shared chat is enabled.
- Update golden fixture expectations so generated frontend artifacts include real chat UI instead of placeholder text.

```python
assert "Chatbot" not in widget_markup
assert "input" in widget_markup.lower()
assert "site-a" in outbound_payload["site_id"]
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_a_shared_widget_runtime.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_shared_widget_transport.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_smoke_runner.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_generator_golden_fixtures.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_food_chatbot_contract.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/test_shared_widget_transport.py chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_food_chatbot_contract.py
git commit -m "test: cover food shared chatbot end-to-end flow"
```

## Manual Verification Checklist

After the test suite passes, verify the real local flow:

1. Start the standalone chatbot server with local env set for `OPENAI_API_KEY` and `FOOD_API_URL`.
2. Start the generated `food` backend and frontend.
3. Log into the host app.
4. Confirm the bottom-left widget shows an input box, not the literal text `Chatbot`.
5. Send a message such as `What can I make with apples?`
6. Confirm the network path is:
   - frontend -> `/api/chat/auth-token`
   - frontend -> `http://127.0.0.1:8100/api/v1/chat/stream`
   - chatbot server -> `food` adapter-backed backend calls
7. Refresh the page and confirm the conversation resets.
