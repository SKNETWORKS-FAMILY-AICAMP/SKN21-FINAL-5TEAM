# Chatbot Runtime Import Preflight Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent generated V2 chatbot workspaces from importing DB-bound `ecommerce.backend` modules, fail fast at compile time when invalid import graphs are generated, and leave RepairAgent to handle only residual failures.

**Architecture:** Split adapter-only order flows from legacy DB-coupled order flows, then add a deterministic compile preflight that scans for banned imports and verifies `server_fastapi` can load inside the generated chatbot workspace. Feed those failures into existing V2 failure/repair handling as compile-stage defects instead of late validation surprises.

**Tech Stack:** Python, pytest, V2 onboarding engine/compiler/validation stack, FastAPI import smoke, ripgrep-style import scanning logic.

---

### Task 1: Define the banned-import preflight contract

**Files:**
- Create: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_compile_preflight.py`
- Create: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding_v2/compile/preflight.py`

**Step 1: Write the failing test**

Add tests that define a compile preflight API:

```python
from pathlib import Path

from chatbot.src.onboarding_v2.compile.preflight import run_chatbot_compile_preflight


def test_preflight_fails_on_banned_import(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    tools = workspace / "src" / "tools"
    tools.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text("from src.tools.order_tools import x\napp = object()\n")
    (tools / "order_tools.py").write_text("from ecommerce.backend.app.database import SessionLocal\n")

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is False
    assert result.failure_code == "banned_import_detected"
    assert "ecommerce.backend" in result.failure_summary


def test_preflight_fails_when_server_fastapi_import_breaks(tmp_path: Path):
    workspace = tmp_path / "chatbot"
    workspace.mkdir(parents=True)
    (workspace / "server_fastapi.py").write_text("raise ModuleNotFoundError('boom')\n")

    result = run_chatbot_compile_preflight(workspace)

    assert result.passed is False
    assert result.failure_code == "chatbot_runtime_import_failed"
```

**Step 2: Run test to verify it fails**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_compile_preflight.py -q
```

Expected: FAIL because `preflight.py` and `run_chatbot_compile_preflight` do not exist.

**Step 3: Write minimal implementation**

Create `preflight.py` with:

- `CompilePreflightResult` dataclass or Pydantic model
- `run_chatbot_compile_preflight(chatbot_workspace: Path) -> CompilePreflightResult`
- banned patterns:
  - `ecommerce.backend`
  - `SessionLocal`
- import smoke:
  - `sys.executable -c "import server_fastapi as module; assert getattr(module, 'app', None) is not None"`
- normalized fields:
  - `passed`
  - `failure_code`
  - `failure_summary`
  - `related_files`
  - `details`

**Step 4: Run test to verify it passes**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_compile_preflight.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding_v2/test_compile_preflight.py chatbot/src/onboarding_v2/compile/preflight.py
git commit -m "feat: add chatbot compile preflight"
```

### Task 2: Separate adapter-only order helpers from DB-bound order tools

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/tools/adapter_order_tools.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/tools/order_tools.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/graph/nodes/order_flow.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_food_adapter_order_tools.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_compile_preflight.py`

**Step 1: Write the failing test**

Add a regression test proving adapter-only imports do not require `order_tools.py`:

```python
import importlib
import sys


def test_adapter_order_tools_imports_without_order_tools_db_dependencies(monkeypatch):
    sys.modules.pop("chatbot.src.tools.adapter_order_tools", None)
    sys.modules.pop("chatbot.src.tools.order_tools", None)

    module = importlib.import_module("chatbot.src.tools.adapter_order_tools")

    assert hasattr(module, "register_exchange_via_adapter")
```

Also extend compile preflight expectations so a generated workspace with adapter-only code passes without `ecommerce.backend`.

**Step 2: Run test to verify it fails**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/test_food_adapter_order_tools.py -q
```

Expected: FAIL because `adapter_order_tools.py` still imports DB-bound helpers from `order_tools.py`.

**Step 3: Write minimal implementation**

Refactor to:

- move shared, adapter-safe prompt/UI helper logic into `adapter_order_tools.py`
- stop importing DB-bound functions from `order_tools.py` for adapter paths
- keep `order_tools.py` only for legacy DB-backed flows
- update `order_flow.py` imports so adapter mode never touches DB-only symbols

Avoid touching business logic beyond what is needed to isolate imports.

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/test_food_adapter_order_tools.py chatbot/tests/onboarding_v2/test_compile_preflight.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/tools/adapter_order_tools.py chatbot/src/tools/order_tools.py chatbot/src/graph/nodes/order_flow.py chatbot/tests/test_food_adapter_order_tools.py chatbot/tests/onboarding_v2/test_compile_preflight.py
git commit -m "refactor: isolate adapter order flow imports"
```

### Task 3: Run compile preflight inside the V2 engine

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding_v2/engine.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding_v2/compile/compiler.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding_v2/models/compile.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_engine_entry.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_compiler.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_compile_preflight.py`

**Step 1: Write the failing test**

Add an engine/compile test like:

```python
def test_engine_marks_compile_failed_when_chatbot_preflight_fails(...):
    result = run_onboarding_generation_v2(...)
    assert result["status"] == "failed_human_review"
    assert result["latest_compile_artifact"]["artifact_type"] == "compile-preflight"
```

And a compiler test proving preflight failures are surfaced as compile-stage failures, not validation failures.

**Step 2: Run test to verify it fails**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_compile_preflight.py -q
```

Expected: FAIL because compile preflight is not part of engine flow yet.

**Step 3: Write minimal implementation**

Implement:

- new compile artifact type: `compile-preflight`
- engine sequence:
  - compile edit programs
  - apply to runtime workspace
  - run chatbot compile preflight on `workspace/chatbot`
  - if failed:
    - synthesize compile failure
    - enter repair from `failed_stage="compile"`
    - do not wait for validation to discover the same issue
- include preflight artifact refs in compile-related state

Keep the existing validation `chatbot_runtime_boot` check as a final safety net.

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_compile_preflight.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding_v2/engine.py chatbot/src/onboarding_v2/compile/compiler.py chatbot/src/onboarding_v2/models/compile.py chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_compile_preflight.py
git commit -m "feat: fail compile on chatbot import preflight"
```

### Task 4: Make repair decisions target compile/import graph defects explicitly

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding_v2/repair/diagnosis.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding_v2/repair/synthesis.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_repair.py`

**Step 1: Write the failing test**

Add tests that feed a compile preflight failure bundle into repair and assert:

```python
def test_repair_prefers_compile_for_banned_import_failure(...):
    decision = diagnose_failure(...)
    assert decision.rewind_to == "compile"
    assert decision.stop is False
```

Also add a synthesis test asserting compile preflight failures include:
- `related_files`
- `server_fastapi.py`
- offending adapter/tool file paths

**Step 2: Run test to verify it fails**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_repair.py -q
```

Expected: FAIL because repair prompts and synthesis do not mention compile-preflight defects yet.

**Step 3: Write minimal implementation**

Update repair flow to:

- include compile-preflight payload in failure synthesis
- mention banned import / runtime import graph failures explicitly in the repair prompt
- bias LLM toward `compile` rewind for import-graph defects
- keep repeated-signature stop rule unchanged

Do not add new broad tools yet.

**Step 4: Run test to verify it passes**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_repair.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/src/onboarding_v2/repair/diagnosis.py chatbot/src/onboarding_v2/repair/synthesis.py chatbot/tests/onboarding_v2/test_repair.py
git commit -m "feat: teach repair about compile import failures"
```

### Task 5: Verify V2 `food` run no longer reaches the old `ecommerce.backend` failure

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_food_vertical_slice.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_validation_runner.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding_v2/test_engine_entry.py`

**Step 1: Write the failing test**

Add an end-to-end regression test that simulates a generated chatbot workspace and asserts:

- compile preflight passes
- validation `chatbot_runtime_boot` passes
- no failure signature contains `ecommerce_backend`

If a full end-to-end run is too expensive for unit tests, add a focused fixture-based test covering the compile/apply/preflight/validation sequence.

**Step 2: Run test to verify it fails**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_food_vertical_slice.py chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_engine_entry.py -q
```

Expected: FAIL until the import graph is fixed.

**Step 3: Write minimal implementation**

Adjust any remaining generated adapter/setup wiring so the `food` chatbot workspace:

- loads without `ecommerce.backend`
- still supports order status, cancel, refund, and exchange UI flows
- preserves the current host/chatbot dual-patch architecture

**Step 4: Run tests to verify they pass**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_compile_preflight.py chatbot/tests/onboarding_v2/test_repair.py chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/tests/onboarding_v2/test_food_vertical_slice.py chatbot/tests/test_food_adapter_order_tools.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding_v2/test_food_vertical_slice.py chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/tests/onboarding_v2/test_compile_preflight.py chatbot/tests/test_food_adapter_order_tools.py
git commit -m "test: cover chatbot import-safe V2 runtime"
```

### Task 6: Run full verification and inspect one real V2 run

**Files:**
- No code changes expected
- Verify artifacts under: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated-v2/food`

**Step 1: Run the focused regression suite**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run pytest chatbot/tests/onboarding_v2/test_compile_preflight.py chatbot/tests/onboarding_v2/test_compiler.py chatbot/tests/onboarding_v2/test_repair.py chatbot/tests/onboarding_v2/test_validation_runner.py chatbot/tests/onboarding_v2/test_engine_entry.py chatbot/tests/onboarding_v2/test_food_vertical_slice.py chatbot/tests/test_food_adapter_order_tools.py -q
```

Expected: PASS.

**Step 2: Run one real V2 generation**

Run:

```bash
QDRANT_URL=http://dummy QDRANT_API_KEY=dummy uv run python -m chatbot.scripts.run_onboarding_generation \
  --site food \
  --source-root food \
  --generated-root generated-v2 \
  --runtime-root runtime-v2 \
  --run-id food-v2-import-preflight-001 \
  --engine v2 \
  --chatbot-server-base-url http://127.0.0.1:8100 \
  --llm-model gpt-5.2
```

Expected:
- no `chatbot_runtime_boot ... ecommerce.backend` failure
- if host prep fails due network, compile artifacts should still show import-safe chatbot output

**Step 3: Inspect artifacts**

Inspect:

- `/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated-v2/food/food-v2-import-preflight-001/artifacts/03-compile`
- `/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated-v2/food/food-v2-import-preflight-001/artifacts/05-validation`
- `/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated-v2/food/food-v2-import-preflight-001/views/run-summary.json`

Confirm:
- compile preflight artifact exists
- no banned import failure
- repair is not looping on the old signature

**Step 4: Commit**

```bash
git add .
git commit -m "feat: harden v2 chatbot runtime import safety"
```
