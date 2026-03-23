# Shared Chatbot Capability Gating Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep `ecommerce` on the full shared chatbot UX while making onboarded sites consume an order-CS-only shared widget by default.

**Architecture:** Introduce capability-driven renderer gating and stable message identities in the shared widget, then split wrappers so `ecommerce` explicitly opts into the full capability set while onboarding-generated wrappers default to order customer-service flows only. Preserve the current shared transport contract and narrow generated frontend artifacts to a thin shared-widget wrapper.

**Tech Stack:** React, TypeScript, FastAPI, pytest, onboarding generator pipeline

---

### Task 1: Add Capability-Gated Shared Widget Rendering

**Files:**
- Modify: `chatbot/frontend/shared_widget/ChatbotWidget.tsx`
- Modify: `chatbot/frontend/shared_widget/ProductListUI.tsx`
- Test: `chatbot/tests/test_shared_widget_rendering.py`

**Step 1: Write the failing test**

Extend the shared widget rendering test so the onboarding-safe profile does not expose live purchase controls.

```python
def test_shared_widget_order_cs_profile_hides_purchase_controls():
    payload = render_widget_with_capabilities(["orders_view", "orders_cancel"])
    assert "장바구니" not in payload["markup"]
    assert "바로 구매" not in payload["markup"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_rendering.py -k order_cs -q`

Expected: FAIL because the default shared product-list path still renders purchase controls.

**Step 3: Write minimal implementation**

- Add a capability prop to `ChatbotWidget`.
- Gate `renderProductList`, `renderFallback`, and default renderer behavior based on capability presence.
- In onboarding-safe mode, render product lists informationally only or suppress them when the payload would otherwise expose dead controls.
- Keep `ecommerce` behavior unchanged unless it explicitly opts into the reduced capability set.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_rendering.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget/ChatbotWidget.tsx chatbot/frontend/shared_widget/ProductListUI.tsx chatbot/tests/test_shared_widget_rendering.py
git commit -m "feat: gate shared widget renderers by capability"
```

### Task 2: Replace WeakMap Keys With Stable Message Identity

**Files:**
- Modify: `chatbot/frontend/shared_widget/ChatbotWidget.tsx`
- Test: `chatbot/tests/test_shared_widget_rendering.py`

**Step 1: Write the failing test**

Add a behavioral test that rerenders the same logical messages as cloned objects and verifies child-local UI state persists.

```python
def test_shared_widget_preserves_child_state_across_cloned_message_rerenders():
    result = render_and_rerender_shared_widget_with_cloned_messages()
    assert result["selection_preserved"] is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_rendering.py -k cloned_message -q`

Expected: FAIL because the current fallback key strategy remounts rows on immutable rerender.

**Step 3: Write minimal implementation**

- Accept explicit `message_id` when present.
- Add a deterministic fallback fingerprint based on stable message fields rather than object identity.
- Remove WeakMap/counter-based fallback as the primary key mechanism.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_rendering.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget/ChatbotWidget.tsx chatbot/tests/test_shared_widget_rendering.py
git commit -m "fix: use stable message identities in shared widget"
```

### Task 3: Make Ecommerce Opt Into Full Capabilities

**Files:**
- Modify: `ecommerce/frontend/app/chatbot/chatbotfab.tsx`
- Modify: `ecommerce/frontend/app/chatbot/ProductListUI.tsx`
- Test: `chatbot/tests/test_shared_widget_transport.py`

**Step 1: Write the failing test**

Add a transport/runtime regression asserting the ecommerce wrapper passes the full capability set and still renders product controls.

```python
def test_ecommerce_wrapper_enables_full_shared_widget_capabilities():
    payload = render_ecommerce_wrapper()
    assert payload["capabilities"] == "full"
    assert "장바구니" in payload["markup"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_transport.py -k ecommerce_wrapper -q`

Expected: FAIL because the wrapper does not yet explicitly declare the full capability profile.

**Step 3: Write minimal implementation**

- Pass the full capability set from `chatbotfab.tsx`.
- Preserve the current product purchase, review, and special UI behaviors in ecommerce.
- Keep the shared transport wiring unchanged.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_transport.py chatbot/tests/test_shared_widget_rendering.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add ecommerce/frontend/app/chatbot/chatbotfab.tsx ecommerce/frontend/app/chatbot/ProductListUI.tsx chatbot/tests/test_shared_widget_transport.py chatbot/tests/test_shared_widget_rendering.py
git commit -m "feat: enable full shared widget capabilities for ecommerce"
```

### Task 4: Make Onboarding Frontend Artifacts Order-CS Only By Default

**Files:**
- Modify: `chatbot/src/onboarding/frontend_generator.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_generator_golden_fixtures.py`

**Step 1: Write the failing test**

Add a generator regression asserting the default generated wrapper includes only order-CS capabilities.

```python
def test_generated_frontend_wrapper_defaults_to_order_cs_capabilities():
    content = generate_frontend_widget_artifact(run_root).read_text()
    assert "orders_view" in content
    assert "products_purchase" not in content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k order_cs_capabilities -q`

Expected: FAIL because generated wrappers do not yet declare restricted capabilities.

**Step 3: Write minimal implementation**

- Emit a thin shared-widget wrapper that passes:
  - `authBootstrapPath`
  - `chatbotApiBase`
  - order-CS capability defaults
- Keep the wrapper site-local, but stop generating a pseudo-product UI for onboarding sites.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_generator_golden_fixtures.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/frontend_generator.py chatbot/src/onboarding/template_generator.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_generator_golden_fixtures.py
git commit -m "feat: default generated widget wrappers to order cs capabilities"
```

### Task 5: Verify Runtime Split Between Ecommerce And Onboarded Sites

**Files:**
- Modify: `chatbot/tests/test_site_c_runtime.py`
- Modify: `chatbot/tests/test_site_a_shared_widget_runtime.py`
- Modify: `chatbot/tests/test_guardrail_startup.py`

**Step 1: Write the failing test**

Add runtime assertions that:
- `site-c` still renders full-capability affordances,
- `site-a` renders order-CS payloads without unsupported controls.

```python
def test_site_a_runtime_uses_order_cs_shared_widget_profile():
    payload = run_site_a_widget_flow()
    assert payload["authenticated"] is True
    assert "바로 구매" not in payload["markup"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_site_c_runtime.py chatbot/tests/test_site_a_shared_widget_runtime.py -q`

Expected: FAIL until runtime wrappers and shared widget defaults are aligned.

**Step 3: Write minimal implementation**

- Adjust runtime wrappers or normalized payload handling until:
  - `site-c` preserves full UX behavior,
  - `site-a` stays restricted to order-CS.
- Keep guardrail and startup coverage intact.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_site_c_runtime.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/test_guardrail_startup.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/tests/test_site_c_runtime.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/test_guardrail_startup.py
git commit -m "test: verify shared widget capability split across runtimes"
```

## Final Verification Sweep

Run:

```bash
uv run pytest chatbot/tests/test_shared_widget_rendering.py chatbot/tests/test_shared_widget_transport.py chatbot/tests/test_site_c_runtime.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_generator_golden_fixtures.py -q
uv run python -m py_compile chatbot/src/api/v1/endpoints/chat.py chatbot/server_fastapi.py chatbot/src/adapters/setup.py chatbot/src/onboarding/*.py
```

Expected:

- pytest reports all green
- `py_compile` exits 0
