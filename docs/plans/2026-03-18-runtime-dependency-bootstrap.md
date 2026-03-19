# Runtime Dependency Bootstrap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Runtime workspace copies only source artifacts and reconstructs frontend/backend dependencies inside the runtime workspace instead of copying `node_modules` or Python virtual environments.

**Architecture:** Extend runtime workspace preparation so ignored dependency/build directories are excluded during copy. Add explicit runtime bootstrap utilities that detect frontend and backend dependency manifests, create clean runtime environments, and install dependencies in-place for validation. Keep bootstrap results observable through reports so frontend/backend validation can distinguish install/setup failures from application failures.

**Tech Stack:** Python, `shutil.copytree`, `venv`, `pip`, npm/yarn/pnpm, pytest

---

### Task 1: Exclude runtime dependency/build artifacts during workspace copy

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/runtime_runner.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_runtime_runner.py`

**Step 1: Write the failing test**

Add a test that prepares a fake source tree containing:
- `frontend/node_modules/.bin/react-scripts`
- `.venv/bin/python`
- `backend/__pycache__/x.pyc`
- `frontend/build/index.html`
- normal source files

Assert that `prepare_runtime_workspace(...)` copies source files but excludes dependency/build artifacts.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -q`
Expected: FAIL because `prepare_runtime_workspace()` currently copies everything.

**Step 3: Write minimal implementation**

In `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/runtime_runner.py`:
- add a `copytree(..., ignore=...)` rule that excludes:
  - `node_modules`
  - `.venv`
  - `venv`
  - `site-packages`
  - `__pycache__`
  - `build`
  - `dist`
  - `.next`
- keep generated overlay file copying unchanged

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_runtime_runner.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_runner.py chatbot/tests/onboarding/test_runtime_runner.py
git commit -m "test: exclude dependency artifacts from runtime copy"
```

### Task 2: Add runtime backend dependency bootstrap detection

**Files:**
- Create: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/backend_build_runner.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_backend_build_runner.py`

**Step 1: Write the failing test**

Add tests covering backend workspace planning:
- `requirements.txt` -> create venv + `python -m pip install -r requirements.txt`
- `pyproject.toml` only -> create venv + `python -m pip install .`
- no backend manifest -> no bootstrap commands

Assert only command planning behavior first.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_backend_build_runner.py -q`
Expected: FAIL because module does not exist.

**Step 3: Write minimal implementation**

Create `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/backend_build_runner.py` with:
- manifest detection helpers
- plan object describing:
  - `venv_dir`
  - `create_venv_command`
  - `install_command`
  - `source`
- command runner helper similar to frontend build runner

Do not wire it into validators yet.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_backend_build_runner.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/backend_build_runner.py chatbot/tests/onboarding/test_backend_build_runner.py
git commit -m "feat: add backend runtime bootstrap planning"
```

### Task 3: Execute backend bootstrap and report results

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/backend_build_runner.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/backend_evaluator.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_backend_build_runner.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_backend_evaluator.py`

**Step 1: Write the failing test**

Add evaluator-level tests asserting:
- when `requirements.txt` exists, backend evaluation artifact includes backend bootstrap metadata
- install/setup failures are reported separately from source scan results
- when no manifest exists, bootstrap is skipped with a clear reason

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_backend_build_runner.py chatbot/tests/onboarding/test_backend_evaluator.py -q`
Expected: FAIL because evaluator does not report backend bootstrap.

**Step 3: Write minimal implementation**

Update backend evaluator to:
- call backend bootstrap runner when backend dependency manifest exists
- record:
  - `bootstrap_attempted`
  - `bootstrap_source`
  - `venv_path`
  - `create_venv_command`
  - `install_command`
  - `bootstrap_passed`
  - `bootstrap_failure_reason`
- keep source scanning/reporting independent from bootstrap result

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_backend_build_runner.py chatbot/tests/onboarding/test_backend_evaluator.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/backend_build_runner.py chatbot/src/onboarding/backend_evaluator.py chatbot/tests/onboarding/test_backend_build_runner.py chatbot/tests/onboarding/test_backend_evaluator.py
git commit -m "feat: report backend runtime bootstrap results"
```

### Task 4: Tighten frontend runtime install/build behavior around clean workspaces

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/frontend_build_runner.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/frontend_evaluator.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_frontend_build_runner.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_frontend_evaluator.py`

**Step 1: Write the failing test**

Add tests asserting:
- frontend build runner uses clean runtime workspace without preexisting `node_modules`
- when install succeeds and build fails, failure reason is reported as build failure
- when install fails, evaluator reports setup failure distinctly from mount validation failure

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_frontend_build_runner.py chatbot/tests/onboarding/test_frontend_evaluator.py -q`
Expected: FAIL because setup/build failure reporting is currently merged too loosely.

**Step 3: Write minimal implementation**

Update frontend build/evaluator flow to:
- preserve existing install/build command execution
- add explicit failure classification:
  - `install_environment_failed`
  - `build_environment_failed`
- include whether clean dependency bootstrap was used

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_frontend_build_runner.py chatbot/tests/onboarding/test_frontend_evaluator.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/frontend_build_runner.py chatbot/src/onboarding/frontend_evaluator.py chatbot/tests/onboarding/test_frontend_build_runner.py chatbot/tests/onboarding/test_frontend_evaluator.py
git commit -m "feat: classify frontend runtime bootstrap failures"
```

### Task 5: Integrate bootstrap reporting into run diagnostics

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/orchestrator.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/slack_bridge.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_orchestrator.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1: Write the failing test**

Add tests asserting final run artifacts and Slack summaries can distinguish:
- source/contract issue
- runtime dependency setup issue
- runtime build issue

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_slack_bridge.py -q`
Expected: FAIL because runtime bootstrap causes are not surfaced yet.

**Step 3: Write minimal implementation**

Update orchestrator/slack reporting to surface a short runtime setup message when dependency bootstrap fails, without reintroducing noisy detail.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_slack_bridge.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/slack_bridge.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_slack_bridge.py
git commit -m "feat: surface runtime bootstrap failures in reports"
```

### Task 6: Run end-to-end regression for onboarding

**Files:**
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/onboarding`

**Step 1: Run focused regression**

Run:
```bash
uv run pytest chatbot/tests/onboarding/test_runtime_runner.py chatbot/tests/onboarding/test_backend_build_runner.py chatbot/tests/onboarding/test_backend_evaluator.py chatbot/tests/onboarding/test_frontend_build_runner.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_slack_bridge.py -q
```

Expected: PASS

**Step 2: Run full onboarding regression**

Run:
```bash
uv run pytest chatbot/tests/onboarding -q
```

Expected: PASS

**Step 3: Commit**

```bash
git add .
git commit -m "feat: rebuild runtime dependencies in clean workspaces"
```
