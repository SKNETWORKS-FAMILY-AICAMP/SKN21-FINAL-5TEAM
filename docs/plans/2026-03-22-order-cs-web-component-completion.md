# Order CS Web Component Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `order_cs`용 shared widget를 실제 브라우저 실행 가능한 web component로 완성하고, 챗봇 서버의 `widget.js` 서빙 및 onboarding attach/runtime 검증까지 닫는다.

**Architecture:** 기존 `chatbot/frontend/shared_widget` React UI와 interrupt/actionUI 흐름은 유지하고, 새 web component wrapper가 이를 custom element 내부에서 실행한다. 챗봇 서버는 빌드된 `widget.js` artifact를 서빙하고, onboarding은 완성된 위젯을 host runtime에 부착하는 역할만 수행한다.

**Tech Stack:** React, TypeScript, custom elements, Shadow DOM, FastAPI, existing LangGraph interrupt/resume flow, pytest

---

### Task 1: Freeze The Widget Host Contract

**Files:**
- Modify: `chatbot/frontend/shared_widget/index.ts`
- Modify: `chatbot/src/onboarding/shared_chatbot_assets.py`
- Modify: `chatbot/src/onboarding/shared_widget_runtime.py`
- Test: `chatbot/tests/test_shared_widget_host_contract.py`

**Step 1: Write the failing test**

Add tests for:

- default host contract keys and values
- attribute override precedence contract expectations
- Python/TypeScript contract field alignment

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_host_contract.py -q`
Expected: FAIL for missing or mismatched contract fields

**Step 3: Write minimal implementation**

- Normalize contract field names
- Ensure Python and TypeScript expose the same contract fields
- Keep defaults for:
  - `chatbotServerBaseUrl`
  - `authBootstrapPath`
  - `widgetBundlePath`
  - `widgetElementTag`
  - `mountMode`

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_host_contract.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget/index.ts chatbot/src/onboarding/shared_chatbot_assets.py chatbot/src/onboarding/shared_widget_runtime.py chatbot/tests/test_shared_widget_host_contract.py
git commit -m "feat: standardize shared widget host contract"
```

### Task 2: Create The Web Component Wrapper

**Files:**
- Create: `chatbot/frontend/shared_widget/web-component.tsx`
- Modify: `chatbot/frontend/shared_widget/widget-entry.ts`
- Test: `chatbot/tests/test_shared_widget_launcher.py`

**Step 1: Write the failing test**

Add tests for:

- `order-cs-widget` custom element registration
- element mount/unmount behavior
- host contract resolution from global config
- attribute override taking precedence over global config

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_launcher.py -q`
Expected: FAIL because custom element is not registered yet

**Step 3: Write minimal implementation**

- Implement `OrderCsWidgetElement extends HTMLElement`
- Attach Shadow DOM by default
- Read config from global contract plus attribute override
- Mount the existing React widget tree inside the element
- Export/register from `widget-entry.ts`

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_launcher.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget/web-component.tsx chatbot/frontend/shared_widget/widget-entry.ts chatbot/tests/test_shared_widget_launcher.py
git commit -m "feat: wrap shared widget as custom element"
```

### Task 3: Reuse Existing Interrupt ActionUI In The Widget Runtime

**Files:**
- Modify: `chatbot/frontend/shared_widget/ChatbotWidget.tsx`
- Modify: `chatbot/frontend/shared_widget/chatbotfab.tsx`
- Test: `chatbot/tests/test_shared_widget_transport.py`

**Step 1: Write the failing test**

Add tests for:

- `ui_payload` to `order_list` message normalization
- `ui_action_required` to confirmation/actionUI rendering
- structured `resume_payload` transmission for:
  - order selection
  - confirmation
  - option selection

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_shared_widget_transport.py -q`
Expected: FAIL for missing or mismatched actionUI/resume behavior

**Step 3: Write minimal implementation**

- Keep current interrupt contract intact
- Ensure widget runtime uses existing:
  - `ui_action_required`
  - `awaiting_interrupt`
  - `interrupts`
  - `ui_payload`
- Keep structured `resume_payload`
- Keep confirmation step for `cancel/refund/exchange`

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_shared_widget_transport.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget/ChatbotWidget.tsx chatbot/frontend/shared_widget/chatbotfab.tsx chatbot/tests/test_shared_widget_transport.py
git commit -m "feat: preserve interrupt action ui in widget runtime"
```

### Task 4: Build A Real Browser Widget Bundle

**Files:**
- Modify: `chatbot/frontend/shared_widget/package.json`
- Create or modify build config under `chatbot/frontend/shared_widget/`
- Create: `chatbot/frontend/shared_widget/dist/.gitkeep` if needed
- Test: `chatbot/tests/api/test_widget_bundle_route.py`

**Step 1: Write the failing test**

Add a test asserting the server expects a built artifact path instead of raw source.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/api/test_widget_bundle_route.py -q`
Expected: FAIL because current route points at raw `widget-entry.ts`

**Step 3: Write minimal implementation**

- Define a build command that emits `dist/widget.js`
- Ensure the browser bundle includes custom element registration
- Keep output path stable

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/api/test_widget_bundle_route.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget/package.json chatbot/frontend/shared_widget chatbot/tests/api/test_widget_bundle_route.py
git commit -m "feat: build browser widget bundle artifact"
```

### Task 5: Serve The Built Widget From The Chatbot Server

**Files:**
- Modify: `chatbot/src/api/v1/endpoints/chat.py`
- Modify: `chatbot/server_fastapi.py`
- Test: `chatbot/tests/api/test_widget_bundle_route.py`

**Step 1: Write the failing test**

Add/extend tests for:

- `/widget.js` returns the built artifact
- route returns 404 if artifact does not exist

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/api/test_widget_bundle_route.py -q`
Expected: FAIL with old raw-source behavior

**Step 3: Write minimal implementation**

- Point `WIDGET_BUNDLE_PATH` to `dist/widget.js`
- Keep route contract `/widget.js`
- Return explicit failure when artifact is missing

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/api/test_widget_bundle_route.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/api/v1/endpoints/chat.py chatbot/server_fastapi.py chatbot/tests/api/test_widget_bundle_route.py
git commit -m "feat: serve built widget bundle from chatbot server"
```

### Task 6: Reframe Onboarding As Widget Attachment Only

**Files:**
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/overlay_generator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_patch_planner.py`
- Test: `chatbot/tests/onboarding/test_overlay_generator.py`

**Step 1: Write the failing test**

Add tests for:

- `frontend_patch` meaning “attach existing widget”
- generated patch injects:
  - global host contract
  - widget bundle script loader
  - `<order-cs-widget>`
- no widget source generation inside generated runtime

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_overlay_generator.py -q`
Expected: FAIL against old intermediate generation assumptions

**Step 3: Write minimal implementation**

- Keep mount policy as all-pages floating launcher
- Treat widget implementation as external server-provided artifact
- Generate only attach/bootstrap/auth-token bridge outputs

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_overlay_generator.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/template_generator.py chatbot/src/onboarding/patch_planner.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/overlay_generator.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_overlay_generator.py
git commit -m "feat: make onboarding attach shared widget runtime"
```

### Task 7: Tighten Frontend Evaluator And Runtime Completion Checks

**Files:**
- Modify: `chatbot/src/onboarding/frontend_evaluator.py`
- Modify: `chatbot/src/onboarding/runtime_completion_runner.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`
- Test: `chatbot/tests/onboarding/test_runtime_completion_runner.py`

**Step 1: Write the failing test**

Add tests for:

- host contract presence
- bundle bootstrap presence
- `<order-cs-widget>` presence
- generated `/api/chat/auth-token` bridge presence
- no false positive from raw helper artifacts

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_completion_runner.py -q`
Expected: FAIL under old validation rules

**Step 3: Write minimal implementation**

- Validate attach/runtime contract instead of local widget source
- Keep `widget_exists == false` as fail-fast
- Ensure runtime completion checks launcher visibility and stream/bootstrap contract

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_completion_runner.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/frontend_evaluator.py chatbot/src/onboarding/runtime_completion_runner.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_completion_runner.py
git commit -m "feat: validate widget attach runtime contract"
```

### Task 8: Tighten Smoke Coverage Around Widget Bootstrap

**Files:**
- Modify: `chatbot/src/onboarding/smoke_contract.py`
- Modify: `chatbot/src/onboarding/smoke_runner.py`
- Test: `chatbot/tests/onboarding/test_smoke_runner.py`

**Step 1: Write the failing test**

Add tests for:

- unauthenticated `/api/chat/auth-token` -> 401
- authenticated `/api/chat/auth-token` -> 200 with `authenticated=true`
- `access_token` non-empty
- recovery payload extra fields ignored safely

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -q`
Expected: FAIL before implementation

**Step 3: Write minimal implementation**

- Keep smoke contract strict
- Normalize recovery payload safely
- Include widget bootstrap/auth bridge checks in smoke flow

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/smoke_contract.py chatbot/src/onboarding/smoke_runner.py chatbot/tests/onboarding/test_smoke_runner.py
git commit -m "feat: verify widget bootstrap smoke contract"
```

### Task 9: Run Focused End-To-End Verification

**Files:**
- Modify only if small fix is required after verification

**Step 1: Build the widget bundle**

Run the shared widget build command defined in `chatbot/frontend/shared_widget/package.json`.
Expected: built `dist/widget.js`

**Step 2: Run focused test suites**

Run:

```bash
uv run pytest chatbot/tests/test_shared_widget_host_contract.py chatbot/tests/test_shared_widget_launcher.py chatbot/tests/test_shared_widget_transport.py chatbot/tests/api/test_widget_bundle_route.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_overlay_generator.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_runtime_completion_runner.py chatbot/tests/onboarding/test_smoke_runner.py -q
```

Expected: PASS

**Step 3: Run a real food onboarding generation**

Run:

```bash
export CHATBOT_BRIDGE_SECRET=dev-bridge-secret
uv run python chatbot/scripts/run_onboarding_generation.py --site food --source-root food --generated-root generated --runtime-root runtime --run-id food-run-widget-e2e --use-llm-roles --generate-llm-patch-draft --approval analysis=approve --approval apply=approve --approval export=approve --llm-model gpt-5.2
```

Expected:

- no planner allowlist crash
- no malformed patch salvage crash
- no smoke recovery payload validation crash
- generated runtime reaches real widget/bootstrap validation

**Step 4: Inspect output artifacts**

Check:

- `generated/food/food-run-widget-e2e/reports/frontend-evaluation.json`
- `generated/food/food-run-widget-e2e/reports/smoke-summary.json`
- `generated/food/food-run-widget-e2e/reports/patch-comparison.json`

**Step 5: Commit**

```bash
git add .
git commit -m "feat: complete order cs web component widget pipeline"
```

