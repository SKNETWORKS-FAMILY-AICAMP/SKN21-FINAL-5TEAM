# Ecommerce Chatbot Full Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the ecommerce chatbot server, model preload lifecycle, upload handling, and rich chatbot UI fully into `chatbot/`, leaving only a host auth bridge and thin mount wrapper inside `ecommerce/`.

**Architecture:** Keep ecommerce as the domain system of record and session issuer, but make the standalone chatbot server the only owner of chat routes, model preload, upload storage, and frontend chatbot UI. Reuse the existing ecommerce `access_token` as the chat token for this refactor so the `site-c` adapter can keep calling ecommerce APIs without rewriting domain auth.

**Tech Stack:** FastAPI, existing LangGraph workflow, site-c adapter stack, Next.js frontend wrapper, pytest, npm build

---

### Task 1: Move Chatbot Runtime Startup And Upload Ownership Into `chatbot/`

**Files:**
- Create: `chatbot/src/runtime/preload.py`
- Create: `chatbot/src/runtime/uploads.py`
- Modify: `chatbot/server_fastapi.py`
- Modify: `chatbot/src/core/config.py`
- Test: `chatbot/tests/test_guardrail_startup.py`
- Test: `chatbot/tests/test_standalone_server_startup.py`

**Step 1: Write the failing test**

Add a startup-focused test that proves the standalone server owns preload and upload configuration.

```python
def test_standalone_server_mounts_chatbot_uploads_and_preload_hooks(monkeypatch):
    calls = []
    monkeypatch.setattr("chatbot.src.runtime.preload.preload_chatbot_runtime", lambda: calls.append("preload"))
    app = build_standalone_app()
    assert "/uploads/chatbot" in {route.path for route in app.routes}
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_standalone_server_startup.py -q`

Expected: FAIL because preload and upload ownership still live in ecommerce.

**Step 3: Write minimal implementation**

- Create `chatbot/src/runtime/preload.py` with one orchestrator function:

```python
def preload_chatbot_runtime() -> None:
    ensure_retrieval_models()
    load_guardrail_model()
    preload_bge_m3()
    preload_kobart()
    preload_clip_resources()
```

- Create `chatbot/src/runtime/uploads.py` with path + public mount helpers:

```python
CHATBOT_UPLOAD_DIR = Path(settings.CHATBOT_UPLOAD_DIR).resolve()
CHATBOT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
```

- Update `chatbot/server_fastapi.py` to:
  - mount `/uploads/chatbot`,
  - call `preload_chatbot_runtime()` during startup,
  - load upload settings from `chatbot/src/core/config.py`.

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_standalone_server_startup.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_guardrail_startup.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/runtime/preload.py chatbot/src/runtime/uploads.py chatbot/server_fastapi.py chatbot/src/core/config.py chatbot/tests/test_standalone_server_startup.py chatbot/tests/test_guardrail_startup.py
git commit -m "feat: move chatbot runtime startup into standalone server"
```

### Task 2: Remove `ecommerce` Auth And Upload Imports From Chat API

**Files:**
- Create: `chatbot/src/auth/site_c_token.py`
- Modify: `chatbot/src/api/v1/endpoints/chat.py`
- Modify: `chatbot/src/graph/nodes/discovery_subagent.py`
- Modify: `chatbot/src/core/config.py`
- Test: `chatbot/tests/auth/test_chat_token.py`
- Test: `chatbot/tests/test_site_c_runtime.py`

**Step 1: Write the failing test**

Add a test that proves the chat endpoint can validate a site-c token without importing ecommerce auth code.

```python
def test_site_c_token_validation_returns_user_claims():
    token = issue_test_site_c_token(user_id=7, email="user@example.com")
    payload = validate_site_c_token(token)
    assert payload["user_id"] == 7
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/auth/test_chat_token.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_c_runtime.py -q`

Expected: FAIL because `chat.py` still imports `ecommerce.backend.app.core.auth` and `CHATBOT_UPLOAD_DIR`.

**Step 3: Write minimal implementation**

- Create `chatbot/src/auth/site_c_token.py`:

```python
def validate_site_c_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.SITE_C_JWT_SECRET, algorithms=[settings.SITE_C_JWT_ALGORITHM])
```

- Replace `Depends(get_current_user)` and `Depends(get_current_user_optional)` in `chat.py` with standalone request helpers that:
  - read `request.access_token` or `Cookie: access_token`,
  - validate the token locally,
  - build a lightweight chat-user payload.

- Replace `CHATBOT_UPLOAD_DIR` imports in `chat.py` and `discovery_subagent.py` with `chatbot/src/runtime/uploads.py`.

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/auth/test_chat_token.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_c_runtime.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/auth/site_c_token.py chatbot/src/api/v1/endpoints/chat.py chatbot/src/graph/nodes/discovery_subagent.py chatbot/src/core/config.py chatbot/tests/auth/test_chat_token.py chatbot/tests/test_site_c_runtime.py
git commit -m "feat: decouple chatbot auth and uploads from ecommerce"
```

### Task 3: Leave Only A Chat Auth Bridge In Ecommerce Backend

**Files:**
- Create: `ecommerce/backend/app/router/chatbot_bridge/router.py`
- Modify: `ecommerce/backend/app/main.py`
- Modify: `ecommerce/backend/app/core/auth.py`
- Test: `ecommerce/backend/tests/test_chatbot_bridge.py`

**Step 1: Write the failing test**

Add a backend test proving ecommerce exposes the auth bridge but no longer mounts chatbot routes directly.

```python
def test_chatbot_bridge_returns_site_c_access_token(client, auth_cookie):
    response = client.post("/api/v1/chat/auth-token", cookies={"access_token": auth_cookie})
    assert response.status_code == 200
    assert response.json()["site_id"] == "site-c"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend/tests/test_chatbot_bridge.py -q`

Expected: FAIL because the bridge does not exist as an isolated router yet.

**Step 3: Write minimal implementation**

- Create `ecommerce/backend/app/router/chatbot_bridge/router.py` with:

```python
@router.post("/auth-token")
def chat_auth_token(request: Request, current_user: User | None = Depends(get_current_user_optional)):
    ...
```

- Update `main.py` to:
  - remove chatbot router include,
  - remove chatbot preload logic,
  - remove chatbot upload static mount,
  - include only the chat bridge router under `/api/v1/chat`.

- Keep existing ecommerce auth/session issuance untouched.

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend/tests/test_chatbot_bridge.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add ecommerce/backend/app/router/chatbot_bridge/router.py ecommerce/backend/app/main.py ecommerce/backend/app/core/auth.py ecommerce/backend/tests/test_chatbot_bridge.py
git commit -m "refactor: leave only chatbot auth bridge in ecommerce backend"
```

### Task 4: Extract The Rich Ecommerce Chat UI Into `chatbot/frontend/shared_widget`

**Files:**
- Create: `chatbot/frontend/shared_widget/EcommerceChatbotFab.tsx`
- Create: `chatbot/frontend/shared_widget/ReviewFormUI.tsx`
- Create: `chatbot/frontend/shared_widget/UsedSaleFormUI.tsx`
- Create: `chatbot/frontend/shared_widget/chatbot-fab.module.css`
- Create: `chatbot/frontend/shared_widget/review-form.module.css`
- Create: `chatbot/frontend/shared_widget/used-sale-form.module.css`
- Modify: `chatbot/frontend/shared_widget/ChatbotWidget.tsx`
- Modify: `chatbot/frontend/shared_widget/OrderListUI.tsx`
- Modify: `chatbot/frontend/shared_widget/ProductListUI.tsx`
- Test: `chatbot/tests/test_shared_widget_rendering.py`
- Test: `chatbot/tests/test_shared_widget_transport.py`

**Step 1: Write the failing test**

Add a rendering test that proves the shared widget package can render the ecommerce-rich wrapper without importing local ecommerce files.

```python
def test_ecommerce_chatbot_fab_uses_shared_components():
    source = Path("chatbot/frontend/shared_widget/EcommerceChatbotFab.tsx").read_text()
    assert "ReviewFormUI" in source
    assert "UsedSaleFormUI" in source
    assert "@shared-chatbot" not in source
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_shared_widget_rendering.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_shared_widget_transport.py -q`

Expected: FAIL because the rich wrapper still lives in `ecommerce/frontend/app/chatbot`.

**Step 3: Write minimal implementation**

- Move the orchestration and UI logic from `ecommerce/frontend/app/chatbot/chatbotfab.tsx` into `chatbot/frontend/shared_widget/EcommerceChatbotFab.tsx`.
- Move `ReviewFormUI.tsx` and `UsedSaleFormUI.tsx` into the shared widget package.
- Normalize imports so the shared package only uses local relative paths.
- Keep host-specific values configurable through props:

```tsx
type EcommerceChatbotFabProps = {
  authBootstrapPath: string;
  chatbotApiBase: string;
  defaultModels?: ModelOption[];
}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_shared_widget_rendering.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_shared_widget_transport.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/frontend/shared_widget/EcommerceChatbotFab.tsx chatbot/frontend/shared_widget/ReviewFormUI.tsx chatbot/frontend/shared_widget/UsedSaleFormUI.tsx chatbot/frontend/shared_widget/chatbot-fab.module.css chatbot/frontend/shared_widget/review-form.module.css chatbot/frontend/shared_widget/used-sale-form.module.css chatbot/frontend/shared_widget/ChatbotWidget.tsx chatbot/frontend/shared_widget/OrderListUI.tsx chatbot/frontend/shared_widget/ProductListUI.tsx chatbot/tests/test_shared_widget_rendering.py chatbot/tests/test_shared_widget_transport.py
git commit -m "feat: extract ecommerce chatbot ui into shared widget package"
```

### Task 5: Replace Ecommerce Frontend Chatbot With A Thin Wrapper

**Files:**
- Modify: `ecommerce/frontend/app/chatbot/chatbotfab.tsx`
- Modify: `ecommerce/frontend/app/chatbot/OrderListUI.tsx`
- Modify: `ecommerce/frontend/app/chatbot/ProductListUI.tsx`
- Modify: `ecommerce/frontend/tsconfig.json`
- Verify: `ecommerce/frontend/package.json`

**Step 1: Write the failing test**

Add a thin-wrapper assertion or build expectation that the ecommerce chatbot entry imports the shared package instead of owning orchestration logic.

```tsx
// expected shape
import EcommerceChatbotFab from "@shared-chatbot/EcommerceChatbotFab";
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/frontend && npm run build`

Expected: PASS currently, but the wrapper is still thick and duplicates shared logic.

**Step 3: Write minimal implementation**

- Replace local `chatbotfab.tsx` contents with a host config wrapper:

```tsx
export default function ChatbotFabWrapper() {
  return (
    <EcommerceChatbotFab
      authBootstrapPath={`${API_BASE_URL || ""}/api/v1/chat/auth-token`}
      chatbotApiBase={API_BASE_URL || ""}
    />
  );
}
```

- Convert local `OrderListUI.tsx` and `ProductListUI.tsx` to thin re-exports or remove their callers.

**Step 4: Run test to verify it passes**

Run: `cd /Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/frontend && npm run build`

Expected: PASS with shared UI imports only.

**Step 5: Commit**

```bash
git add ecommerce/frontend/app/chatbot/chatbotfab.tsx ecommerce/frontend/app/chatbot/OrderListUI.tsx ecommerce/frontend/app/chatbot/ProductListUI.tsx ecommerce/frontend/tsconfig.json
git commit -m "refactor: replace ecommerce chatbot ui with thin shared wrapper"
```

### Task 6: Keep Site-C Adapter And Runtime Validation Working After Extraction

**Files:**
- Modify: `chatbot/src/adapters/site_c/auth.py`
- Modify: `chatbot/src/adapters/site_c/client.py`
- Modify: `chatbot/tests/test_site_c_adapter_resolution.py`
- Modify: `chatbot/tests/test_site_c_runtime.py`
- Modify: `chatbot/FASTAPI_SERVER_RUNBOOK.md`
- Modify: `.env.example`

**Step 1: Write the failing test**

Add or extend adapter tests so site-c still validates auth and forwards the upstream token correctly after auth decoupling.

```python
def test_site_c_auth_headers_forward_access_token_cookie():
    ctx = AuthenticatedContext(siteId="site-c", accessToken="jwt-token", userId="7")
    headers = build_site_c_auth_headers(ctx)
    assert headers["Cookie"] == "access_token=jwt-token"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_c_adapter_resolution.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_c_runtime.py -q`

Expected: FAIL if any auth or runtime assumptions still depend on ecommerce imports.

**Step 3: Write minimal implementation**

- Keep `site-c` upstream transport cookie-based for this refactor.
- Make runtime config explicit:

```python
SITE_C_JWT_SECRET: str
SITE_C_JWT_ALGORITHM: str = "HS256"
BACKEND_API_URL: str = "http://localhost:8000"
CHATBOT_UPLOAD_DIR: str = "chatbot/.runtime/uploads"
```

- Update runbook and env example so the standalone server can be started without relying on ecommerce server internals.

**Step 4: Run test to verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/kaggle-agent-pycache uv run pytest /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_c_adapter_resolution.py /Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_site_c_runtime.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/adapters/site_c/auth.py chatbot/src/adapters/site_c/client.py chatbot/tests/test_site_c_adapter_resolution.py chatbot/tests/test_site_c_runtime.py chatbot/FASTAPI_SERVER_RUNBOOK.md .env.example
git commit -m "chore: stabilize site-c adapter runtime after extraction"
```

### Task 7: Run End-To-End Verification Against Ecommerce

**Files:**
- Verify only; no new code unless failures reveal gaps.

**Step 1: Start the standalone chatbot server**

Run:

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM
uv run uvicorn chatbot.server_fastapi:app --host 127.0.0.1 --port 8100
```

Expected: `/health` returns `200`.

**Step 2: Start ecommerce backend and frontend**

Run:

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend && uv run uvicorn ecommerce.backend.app.main:app --host 127.0.0.1 --port 8000
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/frontend && npm run dev
```

Expected: backend and frontend both boot without chatbot preload or router include errors.

**Step 3: Verify the auth bridge**

Run:

```bash
curl -i -X POST http://127.0.0.1:8000/api/v1/chat/auth-token
```

Expected: unauthenticated payload when logged out, authenticated payload after login session is present.

**Step 4: Verify the main user flows manually**

Check:

- login,
- open chatbot UI,
- send one normal question,
- request recent orders,
- trigger product list UI,
- upload image,
- request review draft,
- submit feedback.

Expected: all flows complete against the standalone chatbot server while ecommerce remains the domain backend.

**Step 5: Commit**

```bash
git add .
git commit -m "test: verify ecommerce chatbot full extraction end to end"
```
