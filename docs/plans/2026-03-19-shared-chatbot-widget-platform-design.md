# Shared Chatbot Widget Platform Design

## Goal

Unify the current site-specific chatbot implementations into a single shared chatbot platform rooted in `chatbot/`, while keeping each onboarded site responsible only for auth bridging, adapter mapping, and host-app widget mounting.

## Decision

- `chatbot/` becomes the canonical source for:
  - the real chat server,
  - the shared widget UI,
  - the shared message and tool-rendering contract,
  - site adapter selection and execution.
- Each site keeps only:
  - `chat_auth.py`,
  - `product_adapter_client.py`,
  - `order_adapter_client.py`,
  - `tool_registry.py`,
  - frontend mount integration.
- `ecommerce` is treated as the first consumer and reference source of reusable UI, not as the permanent home of the chatbot UI.

## Architecture

### Shared Platform

- `chatbot/src/api/v1/endpoints/chat.py` and `chatbot/server_fastapi.py` provide the single chat transport.
- `chatbot/src/adapters/` provides site-specific adapter resolution by `site_id`.
- A new shared widget package under `chatbot/` hosts the reusable React chatbot UI and tool renderers.

### Site Integration Layer

- Host sites expose `POST /api/chat/auth-token`.
- Host sites issue a site-scoped bridge token plus normalized user context.
- Host sites mount the shared widget inside the existing app shell without re-owning chat logic.

### Data Flow

1. User opens a host site.
2. Shared widget bootstraps against the host site's `/api/chat/auth-token`.
3. Widget receives `{ authenticated, access_token, site_id, ... }`.
4. Widget sends chat turns to the shared chatbot server.
5. Chatbot server resolves the adapter for `site_id`.
6. Tool calls execute through the adapter-backed registry.
7. Tool results are normalized into shared UI payloads and rendered by the widget.

## Shared Contracts

### Auth Bridge Contract

Host backend contract:

```json
{
  "authenticated": true,
  "access_token": "bridge-token",
  "site_id": "site-a",
  "user": {
    "id": "7",
    "email": "test1@example.com",
    "name": "test1"
  }
}
```

### Chat Request Contract

Widget to chatbot server contract:

```json
{
  "message": "최근 주문 보여줘",
  "conversation_id": "uuid",
  "previous_state": {},
  "site_id": "site-a",
  "access_token": "bridge-token"
}
```

### UI Payload Contract

Shared widget renderers consume normalized payload types such as:

- `text`
- `order_list`
- `product_list`
- `confirmation`
- `review_form`
- `used_sale_form`

These payloads must not expose raw site-specific API responses directly.

## Adapter Responsibilities

The adapter layer must absorb all site-specific differences:

- auth transport differences: cookies, bearer tokens, custom headers
- endpoint path differences
- response shape differences
- action semantic differences such as `cancel`, `refund`, `exchange`

The core chatbot tools must remain unaware of site-specific API quirks.

## UI Extraction Scope

Extract from `ecommerce/frontend/app/chatbot/`:

- `chatbotfab.tsx`
- `OrderListUI.tsx`
- `ProductListUI.tsx`
- `ReviewFormUI.tsx` after the first pass

Do not carry over:

- `next/navigation`
- `next/image`
- ecommerce-only auth context
- ecommerce-only endpoint fetch logic
- ecommerce branding and route assumptions

## Generator Impact

The onboarding generator should stop pretending to generate a full chatbot product per site.

Its new role is to generate only:

- auth bridge,
- adapter clients,
- tool registry,
- widget mount integration.

The real widget implementation should be imported from the shared chatbot platform.

## Risks

- The current chatbot server still contains ecommerce-coupled imports and assumptions.
- The ecommerce chatbot UI has Next.js-specific dependencies that must be removed during extraction.
- Analyzer output is sufficient for route discovery but not sufficient alone for semantic action mapping; adapter correction points will still be needed.
- The auth bridge token format must be tightened before wider production use.

## Success Criteria

- `ecommerce` and `food` both use the same shared widget implementation.
- `ecommerce` and `food` both talk to the same chatbot server contract.
- Site-specific differences are isolated to adapters and auth bridge files.
- Onboarding generation for a new site produces adapter and mount artifacts only, not a bespoke chatbot UI.
