# Framework Strategy Onboarding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `Django/Flask/FastAPI + React/Vue` 조합에 대해 backend route wiring, frontend widget mount, tool adapter wiring, validation, export까지 자동화된 framework-aware onboarding pipeline을 구현한다.

**Architecture:** 공통 orchestrator 파이프라인은 유지하고 `BackendIntegrationStrategy`와 `FrontendIntegrationStrategy`를 추가한다. analysis/codebase map은 전략 선택과 wiring target 후보를 산출하고, generator는 strategy별 generated files와 patches를 materialize한다. runtime simulation, evaluator, smoke runner는 새 integration contract를 검증하고 마지막에 runtime diff 기반 export patch를 만든다.

**Tech Stack:** Python, pytest, Django/Flask/FastAPI/React/Vue-aware onboarding pipeline

---

### Task 1: Lock strategy selection and analysis contract in tests

**Files:**
- Modify: `chatbot/tests/onboarding/test_codebase_mapper.py`
- Modify: `chatbot/tests/onboarding/test_patch_planner.py`
- Modify: `chatbot/tests/onboarding/test_llm_role_runner.py`

**Step 1: Write the failing tests**

고정할 contract:
- codebase map이 backend/frontend strategy 후보를 노출한다.
- route wiring 후보, frontend mount 후보, tool registry 후보가 candidate set에 포함된다.
- planner evidence가 strategy-aware capability와 output intent를 포함한다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -v`
- `uv run pytest chatbot/tests/onboarding/test_patch_planner.py -v`
- `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k strategy -v`

Expected: FAIL

**Step 3: Write minimal implementation expectations**

fixture와 assertion으로 `backend_strategy`, `frontend_strategy`, route/mount target shape를 명확히 고정한다.

**Step 4: Run tests again**

같은 명령을 다시 실행한다.
Expected: still FAIL due to missing implementation

### Task 2: Extend codebase mapping for strategy-aware targets

**Files:**
- Modify: `chatbot/src/onboarding/codebase_mapper.py`
- Modify: `chatbot/src/onboarding/site_analyzer.py`
- Modify: `chatbot/src/onboarding/manifest.py`
- Test: `chatbot/tests/onboarding/test_codebase_mapper.py`

**Step 1: Write the failing test**

아래를 검증하는 테스트를 추가한다.
- Django/Flask/FastAPI route target 후보가 감지된다.
- React/Vue mount target 후보가 감지된다.
- analysis 결과에 strategy metadata가 포함된다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k strategy -v`
Expected: FAIL

**Step 3: Write minimal implementation**

`OnboardingIgnoreMatcher`를 재사용하면서 codebase map과 site analysis가 strategy metadata 및 wiring target 후보를 산출하도록 확장한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k strategy -v`
Expected: PASS

### Task 3: Add backend integration strategies and route wiring generation

**Files:**
- Create: `chatbot/src/onboarding/backend_integration.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

고정할 behavior:
- Django strategy가 url wiring patch를 생성한다.
- Flask strategy가 blueprint registration patch를 생성한다.
- FastAPI strategy가 router include patch를 생성한다.
- orchestrator materialization이 backend strategy 산출물을 patch/file 목록에 포함한다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k backend -v`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k backend_strategy -v`

Expected: FAIL

**Step 3: Implement**

strategy interface와 framework별 backend wiring generator를 추가하고, `chat_auth.py`와 route wiring patch를 함께 materialize한다.

**Step 4: Verify**

Run the same commands.
Expected: PASS

### Task 4: Add frontend integration strategies and real widget bootstrap contract

**Files:**
- Create: `chatbot/src/onboarding/frontend_integration.py`
- Modify: `chatbot/src/onboarding/frontend_generator.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_frontend_mount_generator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`

**Step 1: Write the failing tests**

고정할 behavior:
- React strategy가 import + mount patch를 생성한다.
- Vue strategy가 SFC import/usage patch를 생성한다.
- widget artifact가 placeholder 대신 bootstrap config contract를 포함한다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_frontend_mount_generator.py -v`
- `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k frontend -v`

Expected: FAIL

**Step 3: Implement**

React/Vue 전략과 widget bootstrap contract를 추가한다. `/api/chat/auth-token` bootstrap과 runtime config가 artifact에 반영되도록 구현한다.

**Step 4: Verify**

Run the same commands.
Expected: PASS

### Task 5: Add tool registry wiring and adapter integration contract

**Files:**
- Create: `chatbot/src/onboarding/tool_registry_generator.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Test: `chatbot/tests/onboarding/test_product_adapter_generator.py`
- Test: `chatbot/tests/onboarding/test_order_adapter_generator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`

**Step 1: Write the failing tests**

고정할 behavior:
- product/order adapter가 공통 method contract를 가진다.
- tool registry artifact가 capabilities에 따라 enabled tools를 구성한다.
- orchestrator가 registry artifact를 generated files에 포함한다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_product_adapter_generator.py -v`
- `uv run pytest chatbot/tests/onboarding/test_order_adapter_generator.py -v`
- `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k registry -v`

Expected: FAIL

**Step 3: Implement**

adapter와 tool registry를 공통 contract로 연결하고 strategy metadata에 맞춰 backend wiring과 연동한다.

**Step 4: Verify**

Run the same commands.
Expected: PASS

### Task 6: Make evaluators framework-aware

**Files:**
- Modify: `chatbot/src/onboarding/backend_evaluator.py`
- Modify: `chatbot/src/onboarding/frontend_evaluator.py`
- Test: `chatbot/tests/onboarding/test_backend_evaluator.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`

**Step 1: Write the failing tests**

고정할 behavior:
- backend evaluator가 route wiring artifact와 auth contract를 검증한다.
- frontend evaluator가 widget bootstrap/import/usage contract를 검증한다.
- unsupported or missing strategy는 hard fallback으로 분류된다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_backend_evaluator.py -v`
- `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py -v`

Expected: FAIL

**Step 3: Implement**

framework-aware evaluator checks를 추가하고, artifact provenance와 failure reason을 명확히 남긴다.

**Step 4: Verify**

Run the same commands.
Expected: PASS

### Task 7: Upgrade smoke generation and runner with strategy-aware auth propagation

**Files:**
- Modify: `chatbot/src/onboarding/overlay_generator.py`
- Modify: `chatbot/src/onboarding/smoke_contract.py`
- Modify: `chatbot/src/onboarding/smoke_runner.py`
- Test: `chatbot/tests/onboarding/test_overlay_generator.py`
- Test: `chatbot/tests/onboarding/test_smoke_runner.py`

**Step 1: Write the failing tests**

고정할 behavior:
- smoke plan이 strategy-aware login/chat/product/order probe를 생성한다.
- cookie/header propagation 규칙이 backend strategy metadata를 따른다.
- request/response summary와 exported context가 artifact에 남는다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_overlay_generator.py -k smoke -v`
- `uv run pytest chatbot/tests/onboarding/test_smoke_runner.py -v`

Expected: FAIL

**Step 3: Implement**

strategy metadata를 활용해 smoke probe를 생성하고, runner가 auth propagation과 result artifact를 처리하도록 확장한다.

**Step 4: Verify**

Run the same commands.
Expected: PASS

### Task 8: Wire the full strategy pipeline through orchestrator and export

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/exporter.py`
- Modify: `chatbot/src/onboarding/runtime_runner.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`
- Test: `chatbot/tests/onboarding/test_runtime_runner.py`
- Test: `chatbot/tests/onboarding/test_exporter.py`

**Step 1: Write the failing tests**

고정할 behavior:
- orchestrator가 strategy outputs를 generation/apply/validation/export 단계 전체에 전달한다.
- runtime simulation이 새 strategy patches/files를 반영한다.
- export metadata가 strategy provenance와 changed files를 보존한다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -v`
- `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -v`
- `uv run pytest chatbot/tests/onboarding/test_exporter.py -v`

Expected: FAIL

**Step 3: Implement**

strategy-aware generation과 validation wiring을 orchestrator에 연결하고 export metadata를 확장한다.

**Step 4: Verify**

Run the same commands.
Expected: PASS

### Task 9: Run focused regression slice

**Step 1: Run**

`uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_frontend_mount_generator.py chatbot/tests/onboarding/test_backend_evaluator.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_overlay_generator.py chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_exporter.py -q`

Expected: PASS

**Step 2: Run broader onboarding regression**

`uv run pytest chatbot/tests/onboarding -q`

Expected: PASS or a short list of unrelated pre-existing failures documented before further changes
