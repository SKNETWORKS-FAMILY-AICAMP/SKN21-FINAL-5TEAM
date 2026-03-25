# Runtime Order CS Web Component Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make onboarding-generated runtimes mount a shared order CS chatbot web component, fetch host auth through `/api/chat/auth-token`, and communicate with the already-running shared chatbot server through a stable order bridge contract.

**Architecture:** Extract a framework-agnostic order CS widget from `chatbot/frontend`, serve it from the shared chatbot server, and reduce generated runtimes to host integration artifacts only: auth bridge, widget mount patch, and host order bridge compatibility routes. Keep the shared chatbot server site-agnostic after a one-time platform refactor.

**Tech Stack:** FastAPI, existing chatbot frontend stack, onboarding generator pipeline, pytest, host runtime patch generation

---

### Task 1: Lock The Shared Widget Host Contract

**Files:**
- Modify: `chatbot/frontend/shared_widget/index.ts`
- Modify: `chatbot/src/onboarding/shared_chatbot_assets.py`
- Modify: `chatbot/src/onboarding/shared_widget_runtime.py`
- Test: `chatbot/tests/test_site_a_shared_widget_runtime.py`
- Create: `chatbot/tests/test_shared_widget_host_contract.py`

**Step 1: Write the failing test**

Add a test that asserts the shared widget runtime exports a host contract containing:

- chatbot server base URL,
- host auth bootstrap path,
- floating launcher mount behavior.

```python
def test_shared_widget_runtime_exposes_host_bootstrap_contract():
    payload = build_widget_runtime_payload(site="food")
    assert payload["auth_bootstrap_path"] == "/api/chat/auth-token"
    assert payload["mount_mode"] == "floating_launcher"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_host_contract.py -q`

Expected: FAIL because the explicit host contract is not yet standardized.

**Step 3: Write minimal implementation**

- Add a minimal shared host config shape.
- Keep `site_id` out of static mount config and source it only from auth bootstrap.
- Set the default mount mode to floating launcher.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_host_contract.py chatbot/tests/test_site_a_shared_widget_runtime.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget/index.ts chatbot/src/onboarding/shared_chatbot_assets.py chatbot/src/onboarding/shared_widget_runtime.py chatbot/tests/test_shared_widget_host_contract.py chatbot/tests/test_site_a_shared_widget_runtime.py
git commit -m "feat: define shared widget host contract"
```

### Task 2: Serve The Web Component Bundle From The Chatbot Server

**Files:**
- Modify: `chatbot/server_fastapi.py`
- Modify: `chatbot/src/api/v1/endpoints/chat.py`
- Create: `chatbot/frontend/shared_widget/widget-entry.ts`
- Create: `chatbot/tests/api/test_widget_bundle_route.py`

**Step 1: Write the failing test**

Add a server test that requests the widget bundle route and verifies it returns JavaScript with a stable content type.

```python
def test_widget_bundle_route_is_served(client):
    response = client.get("/widget.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/api/test_widget_bundle_route.py -q`

Expected: FAIL because the chatbot server does not yet expose the widget bundle.

**Step 3: Write minimal implementation**

- Add a static route for the built widget bundle.
- Keep the route stable and framework-agnostic.
- Avoid host-site-specific path logic.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/api/test_widget_bundle_route.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/server_fastapi.py chatbot/src/api/v1/endpoints/chat.py chatbot/frontend/shared_widget/widget-entry.ts chatbot/tests/api/test_widget_bundle_route.py
git commit -m "feat: serve shared widget bundle from chatbot server"
```

### Task 3: Standardize The Host Auth Bootstrap Flow

**Files:**
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/backend_integration.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

Add a generator test that verifies generated runtimes expose `POST /api/chat/auth-token` returning:

- `authenticated`,
- `site_id`,
- `access_token`,
- `user`.

```python
def test_generated_chat_auth_bridge_returns_site_scoped_bootstrap_contract(tmp_path):
    payload = render_generated_chat_auth(tmp_path, site="food")
    assert "site_id" in payload
    assert "access_token" in payload
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k chat_auth -q`

Expected: FAIL because the full runtime bootstrap contract is not yet guaranteed.

**Step 3: Write minimal implementation**

- Normalize generated chat auth payload fields.
- Keep the token fetch on first widget open only.
- Keep host session parsing local to the generated runtime.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k chat_auth -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/template_generator.py chatbot/src/onboarding/backend_integration.py chatbot/src/onboarding/orchestrator.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "feat: standardize generated auth bootstrap contract"
```

### Task 4: Extract Order CS UI Into A Real Web Component Runtime

**Files:**
- Modify: `chatbot/frontend/shared_widget/chatbotfab.tsx`
- Modify: `chatbot/frontend/shared_widget/index.ts`
- Modify: `chatbot/frontend/shared_widget/OrderListUI.tsx`
- Create: `chatbot/tests/test_shared_widget_transport.py`
- Create: `chatbot/tests/test_shared_widget_launcher.py`

**Step 1: Write the failing test**

Add a widget test that mounts the component as a floating launcher, opens it, fetches auth from the host, and then sends a chat turn to the shared server transport.

```tsx
it("bootstraps auth on first open and sends chat turns to the shared server", async () => {
  renderHostPageWithWidget();
  await user.click(screen.getByRole("button", { name: /chat/i }));
  expect(fetch).toHaveBeenCalledWith("/api/chat/auth-token", expect.anything());
});
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_transport.py -q`

Expected: FAIL because the current runtime is not yet wired as a real floating web component flow.

**Step 3: Write minimal implementation**

- Implement a floating launcher shell.
- Fetch auth on first open, not on page load.
- Send only the normalized shared chat request payload.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_transport.py chatbot/tests/test_shared_widget_launcher.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget chatbot/tests/test_shared_widget_transport.py chatbot/tests/test_shared_widget_launcher.py
git commit -m "feat: wire floating order cs widget runtime"
```

### Task 5: Define A Stable Shared Order CS Bridge Contract

**Files:**
- Modify: `chatbot/src/tools/adapter_order_tools.py`
- Modify: `chatbot/src/tools/order_tools.py`
- Modify: `chatbot/src/tools/service_tools.py`
- Modify: `chatbot/src/adapters/setup.py`
- Create: `chatbot/tests/test_order_cs_bridge_contract.py`

**Step 1: Write the failing test**

Add a test that verifies the shared order CS contract exposes normalized operations for:

- list orders,
- get order status,
- cancel,
- refund,
- exchange.

```python
def test_order_cs_bridge_contract_is_normalized():
    registry = build_order_cs_bridge(site_id="site-a")
    assert {"list_orders", "get_order_status", "cancel", "refund", "exchange"} <= set(registry)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_order_cs_bridge_contract.py -q`

Expected: FAIL because the bridge contract is not yet explicitly standardized around the runtime-host flow.

**Step 3: Write minimal implementation**

- Normalize operation names and return shapes.
- Keep already-supported sites working through existing adapters.
- Prepare the contract so new runtimes can satisfy it over HTTP without adding new chatbot-side site modules.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_order_cs_bridge_contract.py chatbot/tests/test_food_adapter_order_tools.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/tools/adapter_order_tools.py chatbot/src/tools/order_tools.py chatbot/src/tools/service_tools.py chatbot/src/adapters/setup.py chatbot/tests/test_order_cs_bridge_contract.py chatbot/tests/test_food_adapter_order_tools.py
git commit -m "feat: define shared order cs bridge contract"
```

### Task 6: Generate Host Runtime Mount Patches That Embed The Shared Widget

**Files:**
- Modify: `chatbot/src/onboarding/frontend_generator.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/overlay_generator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing test**

Add a generator test that verifies the generated frontend patch:

- loads the shared widget bundle,
- mounts a floating launcher,
- uses host auth bootstrap config.

```python
def test_generated_mount_patch_embeds_shared_widget_bundle(tmp_path):
    patch = generate_mount_patch(tmp_path)
    assert "widget.js" in patch.read_text()
    assert "order-cs-widget" in patch.read_text()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k mount -q`

Expected: FAIL because the mount patch is still oriented around placeholder widget generation.

**Step 3: Write minimal implementation**

- Replace placeholder widget mounts with shared widget script + custom element mounting.
- Keep framework-specific logic limited to insertion points.
- Default to global floating launcher visibility.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k mount -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/frontend_generator.py chatbot/src/onboarding/template_generator.py chatbot/src/onboarding/overlay_generator.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: generate shared widget runtime mounts"
```

### Task 7: Generate Host Runtime Order Bridge Compatibility For New Sites

**Files:**
- Modify: `chatbot/src/onboarding/tool_registry_generator.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/site_analyzer.py`
- Modify: `chatbot/src/onboarding/codebase_mapper.py`
- Test: `chatbot/tests/onboarding/test_site_analyzer.py`
- Test: `chatbot/tests/onboarding/test_codebase_mapper.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`

**Step 1: Write the failing test**

Add a generator test that verifies a generated runtime includes host-side compatibility outputs for the shared order CS bridge rather than only chatbot-side Python stubs.

```python
def test_generated_runtime_contains_order_bridge_compatibility_outputs(tmp_path):
    manifest = generate_runtime(tmp_path)
    assert "order_bridge" in manifest["generated_files"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k order -q`

Expected: FAIL because current generation focuses on Python adapter client stubs only.

**Step 3: Write minimal implementation**

- Update analyzer and mapper outputs to identify host order bridge targets.
- Generate host runtime compatibility surfaces for list/status/cancel/refund/exchange.
- Keep the generation limited to runtime-owned files and patches.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_site_analyzer.py chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_template_generator.py -k order -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/tool_registry_generator.py chatbot/src/onboarding/template_generator.py chatbot/src/onboarding/site_analyzer.py chatbot/src/onboarding/codebase_mapper.py chatbot/tests/onboarding/test_site_analyzer.py chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_template_generator.py
git commit -m "feat: generate host order bridge compatibility outputs"
```

### Task 8: Prove End-To-End Runtime Integration Works Without Manual Host Edits

**Files:**
- Modify: `chatbot/src/onboarding/runtime_completion_runner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/smoke_runner.py`
- Test: `chatbot/tests/onboarding/test_runtime_completion_runner.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`
- Test: `chatbot/tests/api/test_onboarding_run_stream.py`

**Step 1: Write the failing test**

Add an end-to-end runtime test that boots:

- generated host backend,
- generated host frontend,
- shared chatbot server,

and verifies that:

- the floating launcher appears,
- auth bootstrap succeeds on first open,
- an order CS turn reaches the shared server.

```python
def test_generated_runtime_order_cs_widget_reaches_shared_server(tmp_path):
    result = run_runtime_e2e(tmp_path)
    assert result["launcher_visible"] is True
    assert result["auth_bootstrap_passed"] is True
    assert result["chat_stream_passed"] is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py -k shared_server -q`

Expected: FAIL because runtime validation does not yet assert the full host-to-chatbot flow.

**Step 3: Write minimal implementation**

- Update runtime completion to account for the already-running shared chatbot server.
- Extend smoke validation to cover first-open auth bootstrap.
- Keep the test focused on runtime integration, not full business semantics.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_agent_integration.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_completion_runner.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/smoke_runner.py chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/api/test_onboarding_run_stream.py
git commit -m "feat: validate generated runtime order cs integration"
```
