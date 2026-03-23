# Shared Chatbot Widget Platform Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn `chatbot/` into the canonical shared chatbot server and widget platform, and reduce onboarded sites to auth bridge, adapter, registry, and mount integration only.

**Architecture:** Extract reusable chatbot UI from `ecommerce` into a shared React widget under `chatbot/`, route all chat traffic through the shared chatbot server, and resolve site-specific behavior through adapter-backed registries keyed by `site_id`. Update onboarding generation so it mounts the shared widget instead of generating a bespoke chatbot UI per site.

**Tech Stack:** FastAPI, React, existing `chatbot/src/adapters`, onboarding generator pipeline, pytest

---

### Task 1: Lock The Chat Server To An Explicit Site-Aware Contract

**Files:**
- Modify: `chatbot/src/api/v1/endpoints/chat.py`
- Modify: `chatbot/server_fastapi.py`
- Modify: `chatbot/src/adapters/setup.py`
- Test: `chatbot/tests/test_site_c_adapter_resolution.py`
- Test: `chatbot/tests/api/test_onboarding_run_stream.py`
- Create: `chatbot/tests/test_chat_site_routing.py`

**Step 1: Write the failing test**

Add a test that sends a chat request with `site_id="site-a"` and verifies the server resolves the site adapter before tool execution.

```python
def test_chat_request_routes_to_site_adapter(client, monkeypatch):
    captured = {}
    monkeypatch.setattr("chatbot.src.adapters.setup.get_adapter", lambda site_id: captured.setdefault("site_id", site_id) or FakeAdapter())
    response = client.post("/api/chat", json={"message": "주문 보여줘", "site_id": "site-a", "access_token": "t"})
    assert response.status_code == 200
    assert captured["site_id"] == "site-a"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_chat_site_routing.py -q`

Expected: FAIL because `/api/chat` does not yet accept or route `site_id`.

**Step 3: Write minimal implementation**

- Extend the chat request schema to include `site_id` and bridge-token auth fields.
- Thread `site_id` into graph input and adapter lookup.
- Centralize adapter resolution so the server, not the host site, decides which adapter-backed registry is active.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_chat_site_routing.py chatbot/tests/test_site_c_adapter_resolution.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/api/v1/endpoints/chat.py chatbot/server_fastapi.py chatbot/src/adapters/setup.py chatbot/tests/test_chat_site_routing.py chatbot/tests/test_site_c_adapter_resolution.py
git commit -m "feat: route shared chat requests by site id"
```

### Task 2: Extract The Shared Widget From Ecommerce UI

**Files:**
- Create: `chatbot/frontend/shared_widget/ChatbotWidget.tsx`
- Create: `chatbot/frontend/shared_widget/OrderListUI.tsx`
- Create: `chatbot/frontend/shared_widget/ProductListUI.tsx`
- Create: `chatbot/frontend/shared_widget/chatbot-widget.module.css`
- Modify: `ecommerce/frontend/app/chatbot/chatbotfab.tsx`
- Modify: `ecommerce/frontend/app/chatbot/OrderListUI.tsx`
- Modify: `ecommerce/frontend/app/chatbot/ProductListUI.tsx`
- Test: `chatbot/tests/test_shared_widget_rendering.py`

**Step 1: Write the failing test**

Add a rendering test that mounts the extracted shared widget with `text`, `order_list`, and `product_list` payloads and checks that the correct renderer appears.

```tsx
it("renders normalized order and product payloads", () => {
  render(<ChatbotWidget messages={[orderMessage, productMessage]} />);
  expect(screen.getByText("최근 주문 목록입니다.")).toBeInTheDocument();
  expect(screen.getByText("추천 상품")).toBeInTheDocument();
});
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_rendering.py -q`

Expected: FAIL because the shared widget does not exist yet.

**Step 3: Write minimal implementation**

- Copy the reusable UI flow from `ecommerce/frontend/app/chatbot/chatbotfab.tsx`.
- Remove Next.js-specific dependencies.
- Move order/product renderer logic into shared React components under `chatbot/frontend/shared_widget/`.
- Keep the extracted widget transport-agnostic; it should accept normalized payloads and callbacks, not call ecommerce APIs directly.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_rendering.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget ecommerce/frontend/app/chatbot chatbot/tests/test_shared_widget_rendering.py
git commit -m "feat: extract shared chatbot widget from ecommerce ui"
```

### Task 3: Replace Ecommerce-Only Fetch Logic With Shared Widget Transport

**Files:**
- Modify: `chatbot/frontend/shared_widget/ChatbotWidget.tsx`
- Modify: `chatbot/src/api/v1/endpoints/chat.py`
- Modify: `ecommerce/frontend/app/chatbot/chatbotfab.tsx`
- Test: `chatbot/tests/test_shared_widget_rendering.py`
- Create: `chatbot/tests/test_shared_widget_transport.py`

**Step 1: Write the failing test**

Add a widget transport test proving the shared widget:
- bootstraps with the host auth endpoint,
- sends the resulting `site_id` and `access_token` to the shared chat API,
- renders a normalized server payload.

```tsx
it("bootstraps auth then sends chat requests to the shared server", async () => {
  mockFetchSequence([...]);
  render(<ChatbotWidget host={{ authBootstrapPath: "/api/chat/auth-token", chatbotApiBase: "http://localhost:9000" }} />);
  await user.type(screen.getByRole("textbox"), "주문 보여줘");
  await user.click(screen.getByRole("button", { name: "전송" }));
  expect(fetch).toHaveBeenCalledWith("http://localhost:9000/api/chat", expect.objectContaining({...}));
});
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_transport.py -q`

Expected: FAIL because the shared widget still contains site-specific transport assumptions.

**Step 3: Write minimal implementation**

- Introduce a host config shape for the shared widget.
- Use host config only for auth bootstrap.
- Use chatbot server config only for actual chat requests.
- Remove direct ecommerce endpoint fetches from the widget runtime path.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_transport.py chatbot/tests/test_shared_widget_rendering.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget chatbot/src/api/v1/endpoints/chat.py ecommerce/frontend/app/chatbot/chatbotfab.tsx chatbot/tests/test_shared_widget_transport.py chatbot/tests/test_shared_widget_rendering.py
git commit -m "feat: add shared widget transport contract"
```

### Task 4: Make Adapter-Backed Tool Registries The Only Site-Specific Backend Surface

**Files:**
- Modify: `chatbot/src/tools/adapter_order_tools.py`
- Modify: `chatbot/src/tools/order_tools.py`
- Modify: `chatbot/src/tools/service_tools.py`
- Modify: `chatbot/src/adapters/setup.py`
- Test: `chatbot/tests/test_food_adapter_order_tools.py`
- Create: `chatbot/tests/test_adapter_registry_tool_contract.py`

**Step 1: Write the failing test**

Add a test proving the same tool contract can be executed against `site-a` and `site-c` adapters and returns the same normalized schema fields.

```python
def test_order_tool_contract_is_site_normalized():
    result = execute_order_list_tool(site_id="site-a", auth=ctx)
    assert "orders" in result
    assert "ui_payload" in result
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_adapter_registry_tool_contract.py -q`

Expected: FAIL because existing tools still assume ecommerce-specific behavior or imports.

**Step 3: Write minimal implementation**

- Route tool execution through adapter-resolved registries.
- Keep tool input and output contracts stable across sites.
- Push all endpoint and response-shape branching down into site adapters.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_adapter_registry_tool_contract.py chatbot/tests/test_food_adapter_order_tools.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/tools chatbot/src/adapters/setup.py chatbot/tests/test_adapter_registry_tool_contract.py chatbot/tests/test_food_adapter_order_tools.py
git commit -m "feat: normalize tool execution through site adapters"
```

### Task 5: Re-scope Onboarding Generation To Shared Widget Consumption

**Files:**
- Modify: `chatbot/src/onboarding/frontend_generator.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/tool_registry_generator.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_generator_golden_fixtures.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing test**

Add a generator regression test proving onboarding output now references the shared widget integration contract instead of generating a bespoke site-local chatbot implementation.

```python
def test_generator_emits_shared_widget_mount_contract():
    artifact = generate_frontend_widget_artifact(run_root)
    assert "shared widget" in artifact["path"] or "SharedChatbotWidget" in Path(artifact["path"]).read_text()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k shared_widget -q`

Expected: FAIL because the generator still thinks it owns the full widget implementation.

**Step 3: Write minimal implementation**

- Narrow onboarding output to auth bridge, adapter clients, tool registry, and mount wiring.
- Keep the host widget surface thin and aligned with the extracted shared widget contract.
- Preserve existing framework-aware mount safety checks.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_orchestrator.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: re-scope onboarding output to shared widget integration"
```

### Task 6: End-To-End Verification On Ecommerce And Food

**Files:**
- Modify: `chatbot/tests/test_site_c_runtime.py`
- Create: `chatbot/tests/test_site_a_shared_widget_runtime.py`
- Modify: `chatbot/tests/test_guardrail_startup.py`

**Step 1: Write the failing test**

Add a runtime integration test proving both `site-c` and `site-a` can:
- bootstrap auth,
- call the shared chat server,
- render normalized order/product payloads.

```python
def test_site_a_shared_widget_runtime_flow():
    payload = run_site_a_widget_flow(...)
    assert payload["authenticated"] is True
    assert payload["ui_payload"]["type"] in {"order_list", "product_list", "text"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_site_c_runtime.py chatbot/tests/test_site_a_shared_widget_runtime.py -q`

Expected: FAIL until both sites consume the same shared flow.

**Step 3: Write minimal implementation**

- Wire `ecommerce` to the shared widget.
- Validate `food` generated integration against the same contract.
- Fix any remaining auth bridge or payload normalization mismatches.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_site_c_runtime.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/test_guardrail_startup.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/tests/test_site_c_runtime.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/test_guardrail_startup.py
git commit -m "test: verify shared widget runtime across ecommerce and food"
```

## Final Verification Sweep

Run:

```bash
uv run pytest chatbot/tests/test_chat_site_routing.py chatbot/tests/test_shared_widget_rendering.py chatbot/tests/test_shared_widget_transport.py chatbot/tests/test_adapter_registry_tool_contract.py chatbot/tests/test_food_adapter_order_tools.py chatbot/tests/test_site_c_runtime.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_orchestrator.py -q
uv run python -m py_compile chatbot/src/api/v1/endpoints/chat.py chatbot/server_fastapi.py chatbot/src/adapters/setup.py chatbot/src/onboarding/*.py
```

Expected:

- pytest reports all green
- `py_compile` exits 0
