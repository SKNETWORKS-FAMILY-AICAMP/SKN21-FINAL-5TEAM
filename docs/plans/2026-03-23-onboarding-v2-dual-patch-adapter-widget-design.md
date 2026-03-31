# Onboarding V2 Dual-Patch Adapter and Widget Design

## Context

`onboarding_v2` already handles the host-side bootstrap path, frontend mount, runtime-truth validation, and a repair loop. The remaining gap is end-to-end deployment shape: the generated result still assumes too much same-origin behavior and does not yet generate chatbot-side adapter code as a first-class deployment artifact.

The target operating model is:

- Host website and chatbot server are deployed separately.
- The host website owns user session state and exposes `/api/chat/auth-token`.
- The chatbot server owns `widget.js`, chat APIs, generated adapters, and tool execution.
- The onboarding result must therefore produce two deployable patches, not one blended patch.

## Approved Constraints

- Acceptance target for real end-to-end behavior is `food/site-a`.
- Other host projects should benefit from better analyzer/planner/compiler target selection, but they are not required to pass end-to-end in this phase.
- `chatbotServerBaseUrl` is required and must be environment-driven.
- Development default is `http://127.0.0.1:8100`.
- Empty `chatbotServerBaseUrl` is invalid.
- `exchange` must **not** use `show_address_search`.
- `exchange` UI flow is fixed to:
  - `show_order_list`
  - `show_option_list`
  - `confirm_order_action`

## Deployment Model

### Host Patch

The host patch owns:

- host backend auth bootstrap endpoint
- host frontend widget mount/bootstrap contract
- host-side API credential behavior needed by the bootstrap flow

The host patch must not include chatbot adapter or tool execution code.

### Chatbot Patch

The chatbot patch owns:

- generated adapter package under `chatbot/src/adapters/generated/<site_key>/`
- adapter registration in `chatbot/src/adapters/setup.py`
- any chatbot-side bridge logic needed to validate host-issued auth material and call host APIs

### Runtime Validation Workspace

Runtime validation applies both patches into a merged validation environment only for testing. Runtime files are not the deployable output. Exported outputs are always:

- `host-approved.patch`
- `chatbot-approved.patch`

## Widget Serving Contract

The widget bundle is served by the chatbot server, not by the host origin.

### Required Host Contract Fields

The generated host contract must include:

- `chatbotServerBaseUrl`
- `authBootstrapPath`
- `widgetBundlePath`

Behavior:

- `chatbotServerBaseUrl` must be an absolute base URL.
- `widgetBundlePath` defaults to `/widget.js`.
- The loader uses `${chatbotServerBaseUrl}${widgetBundlePath}`.
- If `chatbotServerBaseUrl` is absent or empty, generation or validation must fail.

### Environment Injection Policy

`chatbotServerBaseUrl` is not a single hardcoded constant in source. It is an environment-scoped deployment value.

Accepted forms:

- Vite: `import.meta.env.VITE_CHATBOT_SERVER_BASE_URL`
- CRA: `process.env.REACT_APP_CHATBOT_SERVER_BASE_URL`
- Next.js client: `process.env.NEXT_PUBLIC_CHATBOT_SERVER_BASE_URL`
- server-templated frontend: host template/config variable

Planner/compiler must choose the appropriate placeholder shape based on the host frontend stack. If no safe injection seam is found, planning fails.

## Host Auth Bootstrap Contract

The host bootstrap endpoint must return:

- `authenticated`
- `site_id`
- `access_token`
- `user`

Rules:

- `site_id` must come from a declared source in the host project.
- The planner must not invent a synthetic `site_id`.
- `access_token` must be real auth material that the generated chatbot adapter can validate.
- Validation must require `site_id` and `user.id`, not just `access_token`.

For this phase, `/api/chat/auth-token` remains host-owned because the host server is the authority on host session state.

## Generated Adapter Architecture

Generated adapters reuse the existing adapter stack rather than inventing a parallel bridge model.

Generated files:

- `chatbot/src/adapters/generated/<site_key>/client.py`
- `chatbot/src/adapters/generated/<site_key>/auth.py`
- `chatbot/src/adapters/generated/<site_key>/mappers.py`
- `chatbot/src/adapters/generated/<site_key>/adapter.py`
- `chatbot/src/adapters/generated/<site_key>/__init__.py`

Responsibilities:

- `client.py`
  - call host product/order/auth endpoints chosen by planner
- `auth.py`
  - adapt `access_token` into the host auth shape
- `mappers.py`
  - normalize host responses into adapter schema
- `adapter.py`
  - implement the existing adapter interface used by tool code

Supported adapter behaviors in this phase:

- `validate_auth`
- `search_products`
- `get_order_status`
- `get_delivery_tracking`
- `submit_order_action`

`search_knowledge` remains out of scope.

## Target Discovery Strategy

Analyzer output remains seam-oriented rather than file-oriented.

Required backend seam candidates:

- auth/session validation endpoint
- current-user endpoint
- product list/search endpoint
- order list/detail endpoint
- order action endpoint
- `site_id` config source

Required frontend seam candidates:

- app shell
- mount target
- existing API client
- config/env injection point for `chatbotServerBaseUrl`

Planner selects from these seams using confidence-ranked candidates. If a required seam cannot be found with enough confidence, planning fails instead of synthesizing a brittle guess.

## Tool and UI Action Contract

Tool logic decides which UI to request. Generated adapters execute host API calls only after required arguments are fully collected.

### Canonical Action Flows

- `cancel`
  - required args: `order_id`, `approved`
  - UI flow: `show_order_list -> confirm_order_action`

- `refund`
  - required args: `order_id`, `approved`
  - UI flow: `show_order_list -> confirm_order_action`
  - `window.confirm(...)` is not an acceptable final implementation for this phase

- `exchange`
  - required args: `order_id`, `new_option_id`, `approved`
  - UI flow: `show_order_list -> show_option_list -> confirm_order_action`
  - `show_address_search` is explicitly excluded

Rules:

- tools do not call host APIs while required args are missing
- tools emit canonical widget actions first
- widget returns `resume_payload`
- generated adapter is called only after the final required arg set is complete

## Validation Gate

Validation must go beyond API smoke and cover widget protocol behavior.

### Required Validation Checks

- `host_auth_bootstrap`
  - validates bootstrap response contract
- `chatbot_adapter_auth`
  - validates chatbot adapter can authenticate host-issued auth material
- `widget_order_e2e`
  - validates widget stream path and interrupt/resume behavior for order actions

### Phase Acceptance Scope

Acceptance target is `food/site-a` with:

- external `widget.js` loading via chatbot server
- valid host bootstrap contract
- generated chatbot adapter registration
- end-to-end `cancel`
- end-to-end `refund`
- `exchange` flow through:
  - `show_order_list`
  - `show_option_list`
  - `confirm_order_action`

## Logging and Export Impact

The existing V2 event/artifact model remains the source of truth.

New or renamed artifacts must make deployment targets explicit:

- compile stage:
  - `host-edit-program`
  - `chatbot-edit-program`
- validation stage:
  - `host-auth-bootstrap`
  - `chatbot-adapter-auth`
  - `widget-order-e2e`
- export stage:
  - `host-approved.patch`
  - `chatbot-approved.patch`

Repair remains stage-based, but failure artifacts must include enough target detail to distinguish:

- host integration defect
- chatbot adapter defect
- widget contract defect

## Recommended Implementation Order

1. Make `chatbotServerBaseUrl` required and environment-driven.
2. Split V2 planning/compile/export into host and chatbot targets.
3. Generate and register chatbot-side adapters from discovered seams.
4. Tighten host bootstrap contract to require `site_id`, `access_token`, and `user`.
5. Unify tool-side `cancel/refund/exchange` UI contracts.
6. Add widget order E2E validation for the accepted flows.
