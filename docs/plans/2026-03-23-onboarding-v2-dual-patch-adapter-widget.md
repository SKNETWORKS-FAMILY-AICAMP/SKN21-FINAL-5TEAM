# Onboarding V2 Dual-Patch Adapter Widget Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend `onboarding_v2` so it generates separate host/chatbot deployable patches, requires environment-driven `chatbotServerBaseUrl`, creates chatbot-side generated adapters, and validates widget order action flows for `food/site-a`.

**Architecture:** Keep the current V2 spine, but split planning, compile, apply, export, and validation into explicit host and chatbot targets. Use the host patch for bootstrap/mount concerns, the chatbot patch for generated adapters and registration, and a merged runtime workspace only for execution validation. Preserve the existing stage/event/artifact model so repair can keep operating on stage rewinds later.

**Tech Stack:** Python, Pydantic, existing `onboarding_v2` engine/storage, shared widget TypeScript runtime, adapter architecture under `chatbot/src/adapters`, pytest.

---

### Task 1: Make `chatbotServerBaseUrl` required and environment-driven

**Files:**
- Modify: `chatbot/scripts/run_onboarding_generation.py`
- Modify: `chatbot/src/onboarding_v2/planning/planner.py`
- Modify: `chatbot/src/onboarding_v2/compile/strategies/frontend/react_mount.py`
- Modify: `chatbot/src/onboarding/shared_chatbot_assets.py`
- Modify: `chatbot/frontend/shared_widget/web-component.tsx`
- Modify: `chatbot/frontend/shared_widget/index.ts`
- Test: `chatbot/tests/onboarding_v2/test_engine_entry.py`
- Test: `chatbot/tests/test_shared_widget_host_contract.py`

**Step 1: Write the failing tests**

```python
def test_v2_engine_requires_chatbot_server_base_url_for_dual_patch_runs():
    with pytest.raises(ValueError, match="chatbot_server_base_url"):
        run_onboarding_generation_v2(..., chatbot_server_base_url="")
```

```python
def test_default_shared_widget_host_contract_is_not_empty_for_generated_payload():
    payload = build_host_contract_payload("https://chat.example.com", "/widget.js", "/api/chat/auth-token")
    assert payload["chatbotServerBaseUrl"] == "https://chat.example.com"
```

**Step 2: Run tests to verify they fail**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_engine_entry.py -q
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/test_shared_widget_host_contract.py -q
```

Expected:
- FAIL because V2 does not yet require `chatbot_server_base_url`
- FAIL because the shared widget/default contract still tolerates empty same-origin base URLs

**Step 3: Write minimal implementation**

Implement:
- CLI parsing for `--chatbot-server-base-url`
- V2 engine/planner validation that the value is present
- framework-aware contract generation that emits an env/config-backed expression
- no empty-string fallback in generated host contract payloads

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/tests/test_shared_widget_host_contract.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/scripts/run_onboarding_generation.py chatbot/src/onboarding_v2/planning/planner.py chatbot/src/onboarding_v2/compile/strategies/frontend/react_mount.py chatbot/src/onboarding/shared_chatbot_assets.py chatbot/frontend/shared_widget/web-component.tsx chatbot/frontend/shared_widget/index.ts chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/tests/test_shared_widget_host_contract.py
git commit -m "feat: require chatbot server base url in v2"
```

### Task 2: Split V2 planning into host and chatbot targets

**Files:**
- Modify: `chatbot/src/onboarding_v2/models/planning.py`
- Modify: `chatbot/src/onboarding_v2/models/compile.py`
- Modify: `chatbot/src/onboarding_v2/planning/planner.py`
- Modify: `chatbot/src/onboarding_v2/models/common.py`
- Test: `chatbot/tests/onboarding_v2/test_models.py`
- Test: `chatbot/tests/onboarding_v2/test_planner.py`

**Step 1: Write the failing tests**

```python
def test_integration_plan_splits_host_and_chatbot_targets():
    plan = build_integration_plan(snapshot, chatbot_server_base_url="https://chat.example.com")
    assert plan.host_backend.strategy == "django_project_urlconf_import_view"
    assert plan.host_frontend.mount_strategy == "react_app_shell_outside_routes"
    assert plan.chatbot_bridge.site_key == "site_a"
```

```python
def test_edit_program_model_exposes_host_and_chatbot_programs():
    program = EditProgram(host_program=HostEditProgram(...), chatbot_program=ChatbotEditProgram(...))
    assert program.host_program is not None
    assert program.chatbot_program is not None
```

**Step 2: Run tests to verify they fail**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_models.py chatbot/tests/onboarding_v2/test_planner.py -q
```

Expected:
- FAIL because current plan/program models are still single-target

**Step 3: Write minimal implementation**

Add:
- `HostBackendPlan`
- `HostFrontendPlan`
- `ChatbotBridgePlan`
- `HostEditProgram`
- `ChatbotEditProgram`

Update planner so `food/site-a` planning yields:
- host bootstrap + mount targets
- chatbot bridge targets including discovered auth/product/order/action seams

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_models.py chatbot/tests/onboarding_v2/test_planner.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding_v2/models/planning.py chatbot/src/onboarding_v2/models/compile.py chatbot/src/onboarding_v2/planning/planner.py chatbot/src/onboarding_v2/models/common.py chatbot/tests/onboarding_v2/test_models.py chatbot/tests/onboarding_v2/test_planner.py
git commit -m "feat: split v2 plans into host and chatbot targets"
```

### Task 3: Compile and apply separate host/chatbot edit programs

**Files:**
- Modify: `chatbot/src/onboarding_v2/compile/compiler.py`
- Modify: `chatbot/src/onboarding_v2/compile/registry.py`
- Modify: `chatbot/src/onboarding_v2/compile/strategies/backend/django.py`
- Modify: `chatbot/src/onboarding_v2/compile/strategies/frontend/react_mount.py`
- Create: `chatbot/src/onboarding_v2/compile/strategies/chatbot/generated_adapter.py`
- Modify: `chatbot/src/onboarding_v2/apply/executor.py`
- Test: `chatbot/tests/onboarding_v2/test_compiler.py`
- Test: `chatbot/tests/onboarding_v2/test_apply_executor.py`

**Step 1: Write the failing tests**

```python
def test_compiler_emits_separate_host_and_chatbot_programs():
    program = compile_plan(plan, snapshot)
    assert program.host_program.backend_wiring_bundles
    assert program.chatbot_program.generated_files
```

```python
def test_apply_executor_materializes_host_and_chatbot_outputs():
    result = apply_edit_program(program, source_root, runtime_root)
    assert result.host_workspace is not None
    assert result.chatbot_workspace is not None
```

**Step 2: Run tests to verify they fail**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_apply_executor.py -q
```

Expected:
- FAIL because compile/apply still assume one blended program

**Step 3: Write minimal implementation**

Implement:
- host compiler output for bootstrap + mount edits
- chatbot compiler output for generated adapter package + `chatbot/src/adapters/setup.py` registration patch
- apply executor that writes host edits to the host workspace and chatbot edits to the chatbot workspace before composing the combined validation runtime

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_apply_executor.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding_v2/compile/compiler.py chatbot/src/onboarding_v2/compile/registry.py chatbot/src/onboarding_v2/compile/strategies/backend/django.py chatbot/src/onboarding_v2/compile/strategies/frontend/react_mount.py chatbot/src/onboarding_v2/compile/strategies/chatbot/generated_adapter.py chatbot/src/onboarding_v2/apply/executor.py chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_apply_executor.py
git commit -m "feat: compile separate host and chatbot edit programs"
```

### Task 4: Generate chatbot-side adapters and registration patches

**Files:**
- Modify: `chatbot/src/adapters/schema.py`
- Modify: `chatbot/src/adapters/setup.py`
- Create: `chatbot/src/onboarding_v2/compile/strategies/chatbot/generated_adapter.py`
- Test: `chatbot/tests/test_adapter_registry_tool_contract.py`
- Test: `chatbot/tests/test_exchange_tool_routing.py`
- Test: `chatbot/tests/onboarding_v2/test_compiler.py`

**Step 1: Write the failing tests**

```python
def test_generated_adapter_matches_existing_adapter_interface():
    package = render_generated_adapter_package(site_key="site_a", ...)
    assert "class GeneratedSiteAdapter(BaseEcommerceSupportAdapter)" in package["adapter.py"]
    assert "async def validate_auth" in package["adapter.py"]
```

```python
def test_exchange_adapter_input_supports_option_selection_without_address():
    payload = SubmitOrderActionInput(
        orderId="O-1",
        actionType="exchange",
        newOptionId="OPT-2",
        approved=True,
    )
    assert payload.newOptionId == "OPT-2"
```

**Step 2: Run tests to verify they fail**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/test_adapter_registry_tool_contract.py chatbot/tests/test_exchange_tool_routing.py chatbot/tests/onboarding_v2/test_compiler.py -q
```

Expected:
- FAIL because generated adapters are missing
- FAIL because adapter action schema does not yet carry the option-selection contract needed for exchange

**Step 3: Write minimal implementation**

Implement:
- generated adapter package templates
- adapter registration patch in `chatbot/src/adapters/setup.py`
- schema support for `newOptionId` and final approval semantics
- no pickup-address contract in the generated exchange path

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/test_adapter_registry_tool_contract.py chatbot/tests/test_exchange_tool_routing.py chatbot/tests/onboarding_v2/test_compiler.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/adapters/schema.py chatbot/src/adapters/setup.py chatbot/src/onboarding_v2/compile/strategies/chatbot/generated_adapter.py chatbot/tests/test_adapter_registry_tool_contract.py chatbot/tests/test_exchange_tool_routing.py chatbot/tests/onboarding_v2/test_compiler.py
git commit -m "feat: generate chatbot adapter packages for v2 onboarding"
```

### Task 5: Tighten host bootstrap contract and validation artifacts

**Files:**
- Modify: `chatbot/src/onboarding_v2/validation/runner.py`
- Modify: `chatbot/src/onboarding_v2/validation/signatures.py`
- Modify: `chatbot/src/onboarding_v2/models/validation.py`
- Modify: `chatbot/src/onboarding_v2/compile/strategies/backend/django.py`
- Test: `chatbot/tests/onboarding_v2/test_validation_runner.py`
- Test: `chatbot/tests/onboarding_v2/test_food_vertical_slice.py`

**Step 1: Write the failing tests**

```python
def test_host_bootstrap_validation_requires_site_id_and_user_id():
    result = validate_host_bootstrap({"authenticated": True, "access_token": "x"})
    assert result.passed is False
```

```python
def test_food_bootstrap_payload_contains_site_id_user_and_access_token():
    payload = render_chat_auth_payload(...)
    assert payload["site_id"] == "site-a"
    assert payload["user"]["id"]
```

**Step 2: Run tests to verify they fail**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_food_vertical_slice.py -q
```

Expected:
- FAIL because validation still allows weaker bootstrap payloads

**Step 3: Write minimal implementation**

Implement:
- stricter bootstrap contract in generated host bridge
- validation checks for `site_id`, `access_token`, and `user.id`
- dedicated validation artifacts for `host_auth_bootstrap` and `chatbot_adapter_auth`

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_food_vertical_slice.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding_v2/validation/runner.py chatbot/src/onboarding_v2/validation/signatures.py chatbot/src/onboarding_v2/models/validation.py chatbot/src/onboarding_v2/compile/strategies/backend/django.py chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_food_vertical_slice.py
git commit -m "feat: require full host bootstrap contract in v2"
```

### Task 6: Unify order action UI contract for cancel, refund, and exchange

**Files:**
- Modify: `chatbot/src/tools/adapter_order_tools.py`
- Modify: `chatbot/src/tools/order_tools.py`
- Modify: `chatbot/frontend/shared_widget/chatbotfab.tsx`
- Modify: `chatbot/frontend/shared_widget/ChatbotWidget.tsx`
- Test: `chatbot/tests/test_food_adapter_order_tools.py`
- Test: `chatbot/tests/test_site_a_shared_widget_runtime.py`
- Test: `chatbot/tests/test_shared_widget_transport.py`

**Step 1: Write the failing tests**

```python
def test_refund_uses_confirm_order_action_ui_instead_of_window_confirm():
    state = begin_refund_without_order_selection(...)
    assert state.ui_action["type"] == "show_order_list"
```

```python
def test_exchange_requests_option_selection_but_not_address_search():
    steps = run_exchange_interrupt_flow(...)
    assert [step["type"] for step in steps] == [
        "show_order_list",
        "show_option_list",
        "confirm_order_action",
    ]
```

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/codex-pycache uv run pytest chatbot/tests/test_food_adapter_order_tools.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/test_shared_widget_transport.py -q
```

Expected:
- FAIL because refund still uses non-canonical confirmation behavior
- FAIL because exchange flow does not yet consistently emit the approved canonical UI sequence

**Step 3: Write minimal implementation**

Implement:
- tool-side canonical flows
- widget-side resume handling for order selection, option selection, and final approval
- no address-search branch in exchange

**Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/codex-pycache uv run pytest chatbot/tests/test_food_adapter_order_tools.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/test_shared_widget_transport.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/tools/adapter_order_tools.py chatbot/src/tools/order_tools.py chatbot/frontend/shared_widget/chatbotfab.tsx chatbot/frontend/shared_widget/ChatbotWidget.tsx chatbot/tests/test_food_adapter_order_tools.py chatbot/tests/test_site_a_shared_widget_runtime.py chatbot/tests/test_shared_widget_transport.py
git commit -m "feat: unify widget order action ui contracts"
```

### Task 7: Add dual-patch export and widget order E2E validation

**Files:**
- Modify: `chatbot/src/onboarding_v2/export/replay.py`
- Modify: `chatbot/src/onboarding_v2/validation/runner.py`
- Modify: `chatbot/src/onboarding_v2/engine.py`
- Modify: `chatbot/src/onboarding_v2/storage/view_projector.py`
- Test: `chatbot/tests/onboarding_v2/test_export_replay.py`
- Test: `chatbot/tests/onboarding_v2/test_validation_runner.py`
- Test: `chatbot/tests/onboarding_v2/test_food_vertical_slice.py`

**Step 1: Write the failing tests**

```python
def test_export_stage_emits_host_and_chatbot_patches():
    bundle = export_and_replay(...)
    assert bundle.host_patch_ref.path.endswith("host-approved.patch")
    assert bundle.chatbot_patch_ref.path.endswith("chatbot-approved.patch")
```

```python
def test_food_widget_order_e2e_validates_cancel_refund_and_exchange_interrupts():
    bundle = validate_runtime(...)
    assert bundle.checks["widget_order_e2e"].passed is True
```

**Step 2: Run tests to verify they fail**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_export_replay.py chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_food_vertical_slice.py -q
```

Expected:
- FAIL because export still emits one blended patch
- FAIL because widget order E2E is not yet a required gate for the accepted flows

**Step 3: Write minimal implementation**

Implement:
- dual patch export
- validation artifact/check names:
  - `host_auth_bootstrap`
  - `chatbot_adapter_auth`
  - `widget_order_e2e`
- engine/view projection updates so final artifacts and summaries point to both deployable patches

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_export_replay.py chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_food_vertical_slice.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding_v2/export/replay.py chatbot/src/onboarding_v2/validation/runner.py chatbot/src/onboarding_v2/engine.py chatbot/src/onboarding_v2/storage/view_projector.py chatbot/tests/onboarding_v2/test_export_replay.py chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_food_vertical_slice.py
git commit -m "feat: validate and export dual patch widget flows"
```

### Task 8: Run the full regression and acceptance suite

**Files:**
- Test only:
  - `chatbot/tests/onboarding/test_cli_runner.py`
  - `chatbot/tests/onboarding_v2/test_models.py`
  - `chatbot/tests/onboarding_v2/test_planner.py`
  - `chatbot/tests/onboarding_v2/test_compiler.py`
  - `chatbot/tests/onboarding_v2/test_apply_executor.py`
  - `chatbot/tests/onboarding_v2/test_export_replay.py`
  - `chatbot/tests/onboarding_v2/test_validation_runner.py`
  - `chatbot/tests/onboarding_v2/test_food_vertical_slice.py`
  - `chatbot/tests/test_shared_widget_host_contract.py`
  - `chatbot/tests/test_food_adapter_order_tools.py`
  - `chatbot/tests/test_site_a_shared_widget_runtime.py`

**Step 1: Run the focused regression suite**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest \
  chatbot/tests/onboarding/test_cli_runner.py \
  chatbot/tests/onboarding_v2/test_models.py \
  chatbot/tests/onboarding_v2/test_planner.py \
  chatbot/tests/onboarding_v2/test_compiler.py \
  chatbot/tests/onboarding_v2/test_apply_executor.py \
  chatbot/tests/onboarding_v2/test_export_replay.py \
  chatbot/tests/onboarding_v2/test_validation_runner.py \
  chatbot/tests/onboarding_v2/test_food_vertical_slice.py \
  chatbot/tests/test_shared_widget_host_contract.py \
  chatbot/tests/test_food_adapter_order_tools.py \
  chatbot/tests/test_site_a_shared_widget_runtime.py -q
```

Expected: PASS

**Step 2: Run one real `food` V2 CLI acceptance**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy \
OPENAI_API_KEY=... \
/Users/junseok/Projects/SKN21-FINAL-5TEAM/.venv/bin/python \
-m chatbot.scripts.run_onboarding_generation \
  --site food \
  --source-root food \
  --generated-root generated-v2 \
  --runtime-root runtime-v2 \
  --run-id food-v2-dual-patch-acceptance \
  --engine v2 \
  --chatbot-server-base-url http://127.0.0.1:8100 \
  --llm-provider openai \
  --llm-model gpt-5.2 \
  --smoke-email test1@example.com \
  --smoke-password password123
```

Expected:
- final status `exported`
- `host-approved.patch` generated
- `chatbot-approved.patch` generated
- widget bootstrap and order UI validation pass

**Step 3: Commit final verification note**

```bash
git status --short
```

If clean except expected outputs:

```bash
git commit --allow-empty -m "chore: verify dual patch onboarding flow"
```
