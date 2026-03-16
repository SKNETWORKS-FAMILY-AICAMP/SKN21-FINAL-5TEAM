# Site-C Adapter And Guardrail Design

**Scope:** Stabilize ecommerce chatbot integration so only `site-c` is supported for order CS flows, and fix guardrail preload so the classifier is available after reloads.

## Goals

- Make ecommerce the only supported adapter-backed site for chatbot order CS flows.
- Ensure refund/cancel/shipping flows use the ecommerce backend URL consistently in local and Docker environments.
- Preserve authentication context through chat state so site-c adapter requests carry the ecommerce session token.
- Prevent guardrail from silently staying unloaded after a uvicorn reload worker restart.

## Non-Goals

- Implement Food or Bilyeo adapter support.
- Redesign the multi-site adapter abstraction.
- Change unrelated discovery, review, or retrieval behavior.

## Current Problems

### 1. Site-C order actions fail in local runs

`refund` reaches the adapter path after order selection. The site-c client builds a backend URL from `BACKEND_API_URL`, but adapter setup falls back to `http://ecommerce-backend:8000` when the env var is missing. That host only resolves inside Docker, so local runs fail with DNS resolution errors.

### 2. Authentication context is incomplete

The chat request state stores `id`, `name`, `email`, and `site_id`, but does not persist `access_token`. The site-c adapter builds auth headers from `access_token` or `sessionRef`, so order APIs can lose the ecommerce login context even when `site_id` is correct.

### 3. Unsupported sites are still structurally active

The codebase still treats `site-a` and `site-b` as normal runtime candidates. That makes fallbacks ambiguous and hides the fact that only ecommerce should be live.

### 4. Guardrail preload is tied to reload session, not worker process

The FastAPI lifespan uses a temp-file marker to skip heavy-model preload after the first worker in a `uvicorn --reload` session. Guardrail state is held in process memory, so when a later worker starts and preload is skipped, `_GUARDRAIL_PIPELINE` remains `None` and requests log the "모델 미로드" warning.

## Recommended Approach

Keep the adapter architecture, but narrow runtime support to a single first-class site:

- `site-c` remains the ecommerce adapter.
- `site-a` and `site-b` become explicitly unsupported for chatbot order CS execution.
- site-c configuration becomes environment-aware and predictable.
- guardrail preload becomes worker-local and idempotent instead of reload-session-global.

This is lower risk than introducing a new ecommerce-only service path, and it preserves the current graph/tool structure.

## Design

### A. Site Support Policy

- Treat `site-c` as the only supported adapter site for the current chatbot deployment.
- Reject `site-a` and `site-b` at adapter selection time with a clear `NOT_SUPPORTED` style error instead of fallback routing.
- Remove misleading comments that imply cross-mapped site IDs or inactive fallbacks.

### B. Backend URL Resolution

- Resolve ecommerce backend URL in one place for adapter setup.
- Prefer explicit env vars first.
- Use `http://localhost:8000` as the local-safe fallback.
- Use Docker hostnames only when the process is actually running inside Docker.

This keeps local development and Docker compose behavior aligned without requiring ad hoc env edits every time.

### C. Chat Auth Context Propagation

- Extend `user_info` state to include ecommerce `access_token`.
- Ensure chat endpoint extracts the token from the request cookies before building graph state.
- Continue passing `site_id` and `access_token` through `order_flow` into adapter order tools.

This makes site-c adapter requests match the authenticated ecommerce browser session.

### D. Adapter Behavior

- Keep `site_c/client.py` and `site_c/adapter.py` as the ecommerce-specific integration layer.
- Make `_get_site_adapter()` strict: only `site-c` succeeds.
- Return direct, operator-friendly errors when the caller uses any other `site_id`.

This is preferable to fallback-to-ecommerce behavior because it surfaces integration mistakes immediately.

### E. Guardrail Preload Fix

- Remove the reload-session temp-marker gate for guardrail, or narrow it so guardrail still loads once per worker process.
- Keep `load_guardrail_model()` idempotent; it already safely returns if the pipeline is loaded.
- Improve startup logging to distinguish:
  - preload skipped intentionally
  - preload attempted and succeeded
  - preload attempted and failed

The simplest correct behavior is to always call `load_guardrail_model()` during worker startup and rely on the in-process singleton to avoid duplicate loads within that process.

## Error Handling

- Site mismatch: return a clear message that this chatbot currently supports ecommerce (`site-c`) only.
- Missing backend URL: fail with a configuration-oriented message only if all fallback resolution paths fail.
- Missing token: allow current auth checks to reject with explicit upstream auth/forbidden errors rather than DNS-like transport failures.
- Guardrail load failure: keep fail-open request handling, but log the real startup exception clearly.

## Testing Strategy

- Add focused tests for adapter site selection and backend URL resolution.
- Add a test that chat state includes `access_token` and preserves `site_id=site-c`.
- Add a startup-level or unit-level test for guardrail preload policy so the loader is invoked on each worker startup path.
- Run targeted pytest coverage around adapter tools and chat endpoint state construction.

## Risks

- Existing dormant `site-a/site-b` callers may now fail fast instead of silently falling back.
- Startup time may increase slightly if guardrail is always loaded per worker process.
- Tests may need lightweight mocking around model preload to avoid expensive runtime work.

## Acceptance Criteria

- Refund flow in ecommerce no longer fails with `nodename nor servname provided`.
- Chatbot order CS requests use `site-c` plus valid auth context end-to-end.
- Unsupported sites produce explicit errors rather than ambiguous behavior.
- Guardrail no longer logs the unloaded warning after normal backend reload/startup unless model loading actually fails.
