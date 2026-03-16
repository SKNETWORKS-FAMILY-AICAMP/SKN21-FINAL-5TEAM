# Site-C Adapter And Guardrail Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make ecommerce `site-c` the only supported adapter-backed chatbot site, preserve auth context for site-c order actions, and fix guardrail preload so the classifier is loaded on each backend worker startup.

**Architecture:** Keep the existing graph and adapter structure, but tighten runtime policy to a single supported site and centralize ecommerce backend URL resolution. Fix guardrail at backend startup by making preload worker-local and idempotent instead of reload-session-global.

**Tech Stack:** FastAPI, LangGraph, LangChain tools, httpx, pytest, pydantic-settings

---

### Task 1: Lock runtime support to ecommerce site-c

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/adapters/setup.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/tools/adapter_order_tools.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/tests/chatbot/test_site_adapter_selection.py`

**Step 1: Write the failing test**

```python
def test_get_site_adapter_rejects_non_site_c():
    with pytest.raises(AdapterError):
        _get_site_adapter("site-a")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/chatbot/test_site_adapter_selection.py -v`
Expected: FAIL because non-`site-c` inputs still fallback instead of failing.

**Step 3: Write minimal implementation**

```python
def _get_site_adapter(site_id: str | None):
    effective_site_id = (site_id or "site-c").strip()
    if effective_site_id != "site-c":
        raise AdapterError("NOT_SUPPORTED", "현재 이 챗봇은 ecommerce(site-c)만 지원합니다.")
    return get_adapter("site-c")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/chatbot/test_site_adapter_selection.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/adapters/setup.py chatbot/src/tools/adapter_order_tools.py tests/chatbot/test_site_adapter_selection.py
git commit -m "chatbot: site-c 전용 어댑터로 고정"
```

### Task 2: Resolve ecommerce backend URL safely for local and Docker

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/adapters/setup.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/tests/chatbot/test_adapter_setup.py`

**Step 1: Write the failing test**

```python
def test_setup_adapters_uses_localhost_fallback_outside_docker(monkeypatch):
    monkeypatch.delenv("BACKEND_API_URL", raising=False)
    assert resolve_ecommerce_backend_url() == "http://localhost:8000"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/chatbot/test_adapter_setup.py -v`
Expected: FAIL because setup currently falls back to `http://ecommerce-backend:8000`.

**Step 3: Write minimal implementation**

```python
def resolve_ecommerce_backend_url() -> str:
    explicit = os.environ.get("BACKEND_API_URL")
    if explicit:
        return explicit.rstrip("/")
    if os.path.exists("/.dockerenv"):
        return "http://ecommerce-backend:8000"
    return "http://localhost:8000"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/chatbot/test_adapter_setup.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/adapters/setup.py tests/chatbot/test_adapter_setup.py
git commit -m "chatbot: ecommerce 어댑터 URL 해석 고정"
```

### Task 3: Persist access token into graph state

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/api/v1/endpoints/chat.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/graph/state.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/tests/chatbot/test_chat_state_builder.py`

**Step 1: Write the failing test**

```python
def test_build_current_state_includes_access_token():
    state = _build_current_state(...)
    assert state["user_info"]["access_token"] == "token-123"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/chatbot/test_chat_state_builder.py -v`
Expected: FAIL because `access_token` is not currently stored in `user_info`.

**Step 3: Write minimal implementation**

```python
"user_info": {
    "id": current_user.id,
    "name": current_user.name,
    "email": current_user.email,
    "site_id": request.site_id,
    "access_token": request.cookies.get("access_token"),
},
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/chatbot/test_chat_state_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/api/v1/endpoints/chat.py chatbot/src/graph/state.py tests/chatbot/test_chat_state_builder.py
git commit -m "chatbot: site-c 인증 토큰 상태 전달"
```

### Task 4: Improve unsupported-site error messaging in order tools

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/tools/adapter_order_tools.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/tests/chatbot/test_adapter_order_tools.py`

**Step 1: Write the failing test**

```python
def test_refund_returns_clear_error_for_unsupported_site():
    result = register_return_via_adapter(site_id="site-a", user_id=1, order_id="ORD-1")
    assert "site-c" in result["error"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/chatbot/test_adapter_order_tools.py -v`
Expected: FAIL because the current path falls back or returns an indirect error.

**Step 3: Write minimal implementation**

```python
except AdapterError as e:
    return {"error": e.message}
```

Applied at the boundary where unsupported site selection occurs so user-facing tool output is explicit and actionable.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/chatbot/test_adapter_order_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/tools/adapter_order_tools.py tests/chatbot/test_adapter_order_tools.py
git commit -m "chatbot: 미지원 사이트 에러 메시지 명확화"
```

### Task 5: Fix guardrail preload to run per worker startup

**Files:**
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend/app/main.py`
- Modify: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/graph/nodes/guardrail.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/tests/ecommerce/test_guardrail_preload.py`

**Step 1: Write the failing test**

```python
def test_guardrail_loader_called_on_worker_startup(monkeypatch):
    called = {"value": 0}
    monkeypatch.setattr(main_module, "load_guardrail_model", lambda: called.__setitem__("value", called["value"] + 1))
    # invoke startup helper
    assert called["value"] == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ecommerce/test_guardrail_preload.py -v`
Expected: FAIL because the current marker-file logic can skip preload.

**Step 3: Write minimal implementation**

```python
step_t0 = time.perf_counter()
load_guardrail_model()
logging.info(...)
```

Either remove the temp-marker gate entirely for guardrail or split startup so guardrail always preloads per worker while heavier optional models can keep separate optimization.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ecommerce/test_guardrail_preload.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add ecommerce/backend/app/main.py chatbot/src/graph/nodes/guardrail.py tests/ecommerce/test_guardrail_preload.py
git commit -m "backend: 가드레일 워커 시작 로드 보장"
```

### Task 6: Verify refund path end-to-end with targeted tests

**Files:**
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/tests/chatbot/test_adapter_order_tools.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/tests/chatbot/test_chat_state_builder.py`
- Test: `/Users/junseok/Projects/SKN21-FINAL-5TEAM/tests/ecommerce/test_guardrail_preload.py`

**Step 1: Run focused test set**

Run: `uv run pytest tests/chatbot/test_site_adapter_selection.py tests/chatbot/test_adapter_setup.py tests/chatbot/test_chat_state_builder.py tests/chatbot/test_adapter_order_tools.py tests/ecommerce/test_guardrail_preload.py -v`
Expected: PASS

**Step 2: Run a broader regression slice**

Run: `uv run pytest tests/chatbot -v`
Expected: PASS or clearly identified unrelated failures.

**Step 3: Manual verification**

Run backend and frontend locally, then reproduce:
- open ecommerce site
- open chatbot
- request refund
- select order
- confirm refund

Expected:
- no DNS resolution error
- adapter requests target local ecommerce backend
- guardrail warning does not appear on a normal fresh startup/reload unless model loading truly fails

**Step 4: Commit final verification changes if needed**

```bash
git add .
git commit -m "chatbot: ecommerce site-c 주문 플로우 안정화"
```
