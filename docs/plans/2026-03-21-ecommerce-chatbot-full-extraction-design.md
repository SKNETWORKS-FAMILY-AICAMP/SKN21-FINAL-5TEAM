# Ecommerce Chatbot Full Extraction Design

## Goal

Extract the ecommerce chatbot runtime out of `ecommerce/` and make `chatbot/` the canonical owner of:

- the standalone FastAPI server,
- model preload and runtime lifecycle,
- upload storage and static serving,
- chat API endpoints and streaming transport,
- rich frontend chatbot UI for ecommerce.

After the extraction:

- `ecommerce/backend` keeps only domain APIs plus a lightweight chat auth bridge.
- `ecommerce/frontend` keeps only a thin mount wrapper.
- `chatbot/` owns the real server and real UI.

## Current Coupling Map

Today the system is only partially separated.

- [`ecommerce/backend/app/main.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend/app/main.py)
  - includes the chatbot router directly,
  - preloads retrieval, guardrail, embedding, summary, and CLIP models,
  - mounts chatbot upload static files,
  - carries chatbot-only session middleware responsibility.
- [`chatbot/src/api/v1/endpoints/chat.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/api/v1/endpoints/chat.py)
  - imports `ecommerce` auth dependencies,
  - imports `ecommerce` `User`,
  - imports `ecommerce` upload directory.
- [`chatbot/src/graph/nodes/discovery_subagent.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/graph/nodes/discovery_subagent.py)
  - imports the ecommerce upload directory directly.
- [`ecommerce/frontend/app/chatbot/chatbotfab.tsx`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/frontend/app/chatbot/chatbotfab.tsx)
  - owns the full ecommerce chat UI contract,
  - handles model selection, image upload, review drafting, used-sale form, and streaming orchestration,
  - is only partially backed by the shared widget package.

This means the current `chatbot` server can boot separately, but the product is still operationally and structurally anchored to `ecommerce/`.

## Decision

Use a `Full Extraction` design with a thin compatibility wrapper.

- `chatbot/` becomes the only owner of chatbot runtime behavior.
- `ecommerce/backend` keeps:
  - login/session issuance,
  - domain APIs for products, orders, shipping, reviews, and user data,
  - a lightweight `chat auth bridge` endpoint.
- `ecommerce/frontend` keeps:
  - layout-level mount integration,
  - host-specific API base configuration,
  - no business logic for chatbot UI rendering.

## Auth Strategy Decision

For this extraction pass, the chatbot server will validate the ecommerce `access_token` locally instead of importing ecommerce auth code or forcing a new bridge-token protocol.

Why this choice:

- The `site-c` adapter already needs the ecommerce `access_token` cookie value to call ecommerce APIs.
- Reusing the existing signed token avoids rewriting all ecommerce domain auth at the same time.
- It removes direct `ecommerce` imports from `chatbot` while keeping ecommerce behavior intact.

The bridge endpoint should therefore return:

```json
{
  "authenticated": true,
  "site_id": "site-c",
  "access_token": "<existing ecommerce access_token cookie value>",
  "user": {
    "id": "123",
    "email": "user@example.com",
    "name": "User"
  }
}
```

The standalone chatbot server will validate this token using shared environment configuration, not by importing [`ecommerce/backend/app/core/auth.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend/app/core/auth.py).

Longer term, a dedicated short-lived bridge token would be cleaner, but it is not required to complete the extraction safely.

## Target Architecture

### Ecommerce Backend

Responsibilities:

- issue and validate ecommerce login session cookies,
- expose product, order, shipping, review, and user APIs,
- expose a chat auth bridge endpoint,
- remain ignorant of chatbot models and chatbot server internals.

Removed responsibilities:

- chatbot router registration,
- model preload,
- chatbot upload storage ownership,
- direct chat streaming endpoint ownership.

### Standalone Chatbot Server

Responsibilities:

- own FastAPI app lifecycle,
- preload retrieval, guardrail, embedding, summary, and CLIP models at startup,
- expose `/api/v1/chat/*` routes,
- expose upload, feedback, and review-draft routes,
- persist conversation logs,
- validate ecommerce access tokens locally,
- resolve adapters by `site_id`,
- call ecommerce APIs through the `site-c` adapter.

### Ecommerce Frontend

Responsibilities:

- mount a shared chatbot component,
- supply host config such as:
  - auth bootstrap path,
  - chatbot API base,
  - default model selector preferences if desired.

Removed responsibilities:

- rich chatbot orchestration,
- direct streaming transport assembly,
- upload request orchestration details,
- specialized chatbot UI ownership.

### Shared Frontend Package

`chatbot/frontend/shared_widget` becomes the home for:

- `ChatbotWidget.tsx`,
- ecommerce-rich wrapper UI,
- `OrderListUI`,
- `ProductListUI`,
- `ReviewFormUI`,
- `UsedSaleFormUI`,
- chatbot-specific CSS modules.

The ecommerce app should only render a thin wrapper component that imports from this shared package.

## Data Flow

1. User logs into ecommerce.
2. Browser calls ecommerce chat auth bridge.
3. Ecommerce backend returns `{ authenticated, site_id, access_token, user }`.
4. Frontend passes `site_id` and `access_token` to the standalone chatbot server.
5. Chatbot server validates the token locally from shared JWT config.
6. Chatbot server resolves `site-c` via adapter setup.
7. `site-c` adapter forwards ecommerce API requests using the same `access_token` as upstream cookie auth.
8. Chatbot server streams text and UI payloads back to the frontend.
9. Uploads go to chatbot-owned storage and are served by chatbot-owned static routes.

## API Contracts

### Host Auth Bridge

Keep a host-configurable bootstrap path. For ecommerce, preserve the current host-facing contract for compatibility.

Preferred bridge route:

- `POST /api/v1/chat/auth-token`

Optional compatibility alias:

- `POST /api/chat/auth-token`

### Standalone Chatbot Routes

Canonical routes remain under the standalone server:

- `POST /api/v1/chat/stream`
- `POST /api/v1/chat`
- `POST /api/v1/chat/upload-image`
- `POST /api/v1/chat/feedback`
- `POST /api/v1/chat/review-draft`

### Upload Contract

Uploads must no longer depend on [`ecommerce/backend/app/uploads.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend/app/uploads.py).

The standalone server should own:

- upload directory path configuration,
- static file mounting,
- public URL generation for uploaded chatbot images.

## Migration Boundaries

### What Moves To `chatbot/`

- startup preload logic currently in [`ecommerce/backend/app/main.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend/app/main.py),
- upload directory ownership currently in [`ecommerce/backend/app/uploads.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/backend/app/uploads.py),
- ecommerce auth validation logic currently imported by [`chatbot/src/api/v1/endpoints/chat.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/api/v1/endpoints/chat.py),
- rich frontend components currently in [`ecommerce/frontend/app/chatbot`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/frontend/app/chatbot).

### What Stays In `ecommerce/`

- domain data models and DB access,
- domain routers and CRUD operations,
- host session cookie issuance,
- chat auth bridge endpoint,
- thin frontend mount wrapper.

## Risks

### Auth Drift

If the standalone server and ecommerce backend disagree on token validation rules, chat login will silently fail or produce user mismatch errors.

Mitigation:

- move JWT validation inputs into shared environment config,
- test both valid and invalid token flows without importing ecommerce auth code.

### Upload URL Drift

If upload paths move but UI code still assumes ecommerce static URLs, image-driven flows will break.

Mitigation:

- centralize upload path and public base URL generation inside `chatbot/`,
- test the upload endpoint and returned URL shape.

### Frontend Regression

`chatbotfab.tsx` contains a lot of ecommerce-specific logic. A direct one-shot rewrite is high risk.

Mitigation:

- move components into `chatbot/frontend/shared_widget`,
- keep a thin ecommerce wrapper that can preserve mount points and local env wiring,
- verify with `npm run build` before removing local copies.

### Hidden Ecommerce Imports

The server may still appear “independent” while importing ecommerce internals at runtime.

Mitigation:

- explicitly search for `from ecommerce...` imports in `chatbot/src`,
- treat remaining imports as extraction blockers.

## Success Criteria

- `ecommerce/backend/app/main.py` no longer mounts chatbot routes or preloads chatbot models.
- `chatbot/server_fastapi.py` can start and serve the full ecommerce chatbot experience independently.
- `chatbot/src/api/v1/endpoints/chat.py` no longer imports ecommerce auth or upload modules.
- `ecommerce/frontend/app/chatbot/chatbotfab.tsx` becomes a thin host wrapper over shared chatbot UI.
- Upload, review-draft, feedback, and streaming chat all work against the standalone chatbot server.
- `site-c` adapter-backed order and product flows still work against ecommerce APIs after extraction.
