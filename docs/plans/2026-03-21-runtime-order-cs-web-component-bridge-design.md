# Runtime Order CS Web Component Bridge Design

## Goal

Turn generated onboarding runtimes into self-contained host applications that:

- mount an embedded order CS chatbot widget inside the host frontend,
- exchange auth through the generated host backend,
- talk to an already-running shared chatbot server over HTTP,
- support only the order CS scope for now:
  - order list,
  - order status,
  - cancel,
  - refund,
  - exchange.

## Decision

- The shared chatbot server remains the canonical chat runtime.
- The shared chatbot UI is extracted into a web component bundle served by the chatbot server.
- Each generated runtime owns only:
  - host-side widget mounting,
  - host-side `/api/chat/auth-token`,
  - host-side order bridge endpoints or order API spec integration needed by the shared server contract.
- The chatbot server is allowed one platform-level refactor, but new onboarded sites must not require site-specific code edits in the chatbot server.
- Order CS is the only required capability in this pass. Product, review, and other flows are out of scope.

## Why This Is Feasible Across Frontend Frameworks

The design does not attempt to regenerate the full chatbot UI natively in each host framework.

Instead:

- `chatbot/frontend` becomes the source of truth for the order CS UI.
- That UI is packaged as a browser-consumable web component bundle such as `widget.js`.
- The host site only loads the script and mounts a custom element.

Because web components are browser primitives, the host application only needs to render HTML and load JavaScript. React, Vue, Next.js, Django templates, or plain HTML can all embed the same widget without reimplementing the UI flow in framework-specific code.

This avoids duplicating:

- widget state management,
- message rendering,
- order CS interaction flows,
- transport logic to the shared chatbot server.

Framework differences are pushed down to host integration only:

- where to mount the widget,
- how to patch the frontend shell,
- how to expose the host auth bridge.

## Architecture

### Shared Chatbot Platform

The shared chatbot server owns:

- the web component bundle,
- the chat transport,
- the bridge-token validation contract,
- the order CS adapter bridge contract.

Its responsibilities are:

- serve the widget bundle,
- receive chat messages from the widget,
- resolve tool execution by `site_id`,
- call host-specific order bridge endpoints through a stable shared contract,
- normalize tool outputs into shared UI payloads.

### Generated Host Runtime

Each generated runtime owns:

- backend auth bridge:
  - `POST /api/chat/auth-token`
- frontend widget mount integration:
  - floating launcher by default,
  - optional page-limited visibility later
- host-side order bridge compatibility surface needed by the shared order CS contract.

The generated runtime must be runnable on its own. If the host backend and frontend are running and the shared chatbot server is already up, the embedded widget should work without any extra manual edits.

### Responsibility Split

The split is intentionally asymmetric.

Shared chatbot server:

- real UI,
- chat orchestration,
- order CS logic,
- stable contract definitions.

Generated runtime:

- host session interpretation,
- host mount point patching,
- host-specific route exposure for auth and order actions.

## Data Flow

1. User opens the generated host site.
2. The host frontend loads the shared widget bundle from the chatbot server.
3. The host frontend mounts the custom element.
4. The user opens the floating launcher.
5. The widget calls the generated host backend `/api/chat/auth-token`.
6. The host backend validates its own session and returns a chatbot bridge token plus `site_id`.
7. The widget stores that token in browser memory.
8. The widget sends chat turns to the shared chatbot server.
9. The shared chatbot server resolves the order CS bridge for `site_id`.
10. Order tools execute through the shared bridge contract.
11. The chatbot server returns normalized order CS payloads.
12. The widget renders the result.

## Auth Bridge Contract

Host backend endpoint:

- `POST /api/chat/auth-token`

Response:

```json
{
  "authenticated": true,
  "site_id": "site-x",
  "access_token": "bridge-token",
  "user": {
    "id": "7",
    "email": "user@example.com",
    "name": "test-user"
  }
}
```

Behavior:

- the token is fetched on first widget open,
- the token is refreshed automatically after expiry,
- the widget does not prefetch tokens on page load.

## Widget Hosting Contract

The widget is hosted by the shared chatbot server and embedded into the generated host frontend.

Host page contract:

```html
<script src="http://chatbot-server/widget.js"></script>
<order-cs-widget></order-cs-widget>
```

The host runtime may also inject configuration by:

- DOM attributes,
- a global bootstrap object,
- environment-backed mount script config.

The first implementation should keep this simple:

- chatbot server base URL,
- host auth bridge URL,
- `site_id` from auth bridge only.

## Order CS Bridge Contract

This pass should stop treating `chatbot/src/adapters/<site>` as the mandatory per-site integration point for new onboarded sites.

Instead, the shared chatbot server should use a stable order bridge contract such as:

- list orders,
- get order status,
- cancel order,
- refund order,
- exchange order.

For already-supported sites, the current adapter-backed implementation can continue to satisfy the contract.

For newly-generated sites, the onboarding runtime should generate the host-side compatibility layer needed so the shared chatbot server can call the same contract over HTTP.

This reduces new-site onboarding from "generate Python adapter code inside chatbot" to "generate host bridge routes plus auth bridge in runtime".

## Existing Overlap And Intended Cleanup

Today there is overlap between:

- generated `order_adapter_client.py` and the current `chatbot/src/adapters/site_*/client.py`,
- generated `chat_auth.py` and the existing shared widget auth bootstrap flow,
- generated frontend widget placeholders and the real shared chatbot UI.

This design resolves the overlap by making the generated runtime responsible only for host integration surfaces, not for owning the real shared UI or duplicating chatbot-side orchestration logic.

## Risks

- The chatbot server will need one-time platform changes to serve the web component bundle and validate bridge tokens.
- CSS isolation and launcher placement may still need minor manual polish per host site.
- Host session formats vary, so generated `/api/chat/auth-token` logic will still need analyzer-guided auth signal detection.
- Some sites may not expose native order exchange APIs; those should degrade to a normalized "manual review required" response rather than breaking the contract.
- Existing adapter code and generated host bridge code may coexist during migration, which increases temporary complexity.

## Success Criteria

- A generated runtime can be started locally and render a floating order CS launcher without manual frontend edits.
- The first widget open triggers `/api/chat/auth-token` on the host runtime.
- The widget can send messages to the already-running shared chatbot server.
- Order list, order status, cancel, refund, and exchange all flow through a stable shared contract.
- A new onboarded site does not require manual `chatbot/src/adapters/<site>` edits to achieve runtime integration.
