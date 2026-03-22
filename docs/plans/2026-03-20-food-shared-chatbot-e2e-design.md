# Food Shared Chatbot E2E Design

## Goal

Turn generated `food` runtimes from "auth bootstrap plus placeholder text" into a real chat experience that:

- mounts a real shared chat UI in the host frontend,
- talks to the standalone chatbot server,
- routes tool calls through the existing `site-a` adapter stack,
- keeps conversation state only in browser memory for the current page session.

## Decision

- The standalone chatbot server remains the canonical chat runtime.
- The host site remains responsible only for auth bridging and widget mounting.
- Adapter and tool selection stays code-driven by `site_id`, not prompt-driven by the agent.
- The onboarding agent may discover where to patch a host app, but it must not decide which chatbot source directory or adapter directory to use.
- Refresh resets the conversation. No server-side conversation persistence is added in this pass.

## Why This Split

The user-facing question was whether the agent should be told "connect this directory" on every run. The answer is no.

The stable pieces must live in code:

- `food -> site-a`
- `site-a -> chatbot/src/adapters/site_a/*`
- host auth bootstrap path -> `/api/chat/auth-token`
- shared widget source -> `chatbot/frontend/shared_widget/*`
- shared chat transport -> chatbot server endpoints

The variable pieces can stay agent-discovered:

- which frontend file should mount `SharedChatbotWidget`
- which backend route file should expose `/api/chat/auth-token`
- which existing host files should receive the generated patch

This keeps onboarding reproducible and prevents future runs from regressing back to a placeholder widget.

## Architecture

### Host Site Layer

- The host backend exposes `POST /api/chat/auth-token`.
- That endpoint validates the host login session and returns a bridge token plus `site_id`.
- The host frontend mounts a generated `SharedChatbotWidget` entry component.
- The generated entry component knows how to call the host auth bridge and the shared chatbot server.

### Shared Chatbot Platform

- `chatbot/server_fastapi.py` remains the standalone server entrypoint.
- `chatbot/src/api/v1/endpoints/chat.py` provides the streaming chat transport.
- `chatbot/src/adapters/setup.py` resolves the adapter from `site_id`.
- Existing adapter-backed tools remain the only site-specific execution surface.

### Generator Ownership Model

- The onboarding generator owns the host integration contract.
- A new code-owned shared asset registry should define:
  - site name to `site_id` mapping,
  - shared widget source files,
  - default chat server base URL and path contract,
  - frontend env keys used to override the chat server base URL.
- The agent should only pick integration targets from discovered host files.

## Data Flow

1. User logs into the `food` site.
2. Host widget posts to `/api/chat/auth-token`.
3. Host backend returns `{ authenticated, site_id, access_token, user }`.
4. The widget stores `site_id`, `access_token`, and in-memory `previous_state`.
5. The widget sends the user's message to the standalone chatbot server.
6. The chatbot server resolves `site-a`.
7. The `site-a` adapter calls `food` backend APIs through existing tool adapters.
8. The chatbot server streams normalized text and UI payloads back to the widget.
9. The widget renders text plus tool-driven UI such as product or order lists.
10. A browser refresh clears local state and starts a new conversation.

## Transport Contract

### Host Auth Bootstrap

`POST /api/chat/auth-token`

Response shape:

```json
{
  "authenticated": true,
  "site_id": "site-a",
  "access_token": "bridge-token",
  "user": {
    "id": "7",
    "name": "test1",
    "email": "test1@example.com"
  }
}
```

### Chat Request

The frontend should send chat turns to the standalone chatbot server, not directly to OpenAI.

Preferred route:

- `POST /api/v1/chat/stream`

Payload shape:

```json
{
  "message": "What can I cook with apples?",
  "site_id": "site-a",
  "access_token": "bridge-token",
  "previous_state": {},
  "conversation_id": "uuid-optional"
}
```

### Chat Server Base URL

The generated frontend should resolve the chatbot base URL from:

1. `window.__CHATBOT_API_BASE__`
2. `process.env.REACT_APP_CHATBOT_API_BASE`
3. `process.env.NEXT_PUBLIC_CHATBOT_API_BASE`
4. a code-owned default for local runtime validation

The local default should be aligned with the shared server runbook. Today that means `http://localhost:8100`, not `http://localhost:9000`.

## Tool Routing Contract

- The widget only sends `site_id` and `access_token`.
- The chatbot server is solely responsible for adapter selection.
- No generated host app should import adapter directories directly.
- No agent prompt should be required to say "use `chatbot/src/adapters/site_a`".

This is already mostly present in `chatbot/src/adapters/setup.py`; the missing part is end-to-end wiring from generated frontend to standalone chat transport.

## Runtime Ownership

For local validation and smoke runs, the system must boot three processes when chat is part of the acceptance criteria:

- host backend
- host frontend
- standalone chatbot server

If only backend and frontend are running, the widget can authenticate but cannot actually chat.

## Risks

- The standalone server entrypoint currently exposes `/api/chat` directly, while the shared widget expects `/api/v1/chat/stream` by default.
- The generated frontend widget is currently a placeholder and does not reuse the real shared widget UI.
- Existing runtime validation starts only host services, so chat can still fail even after the UI is wired.
- Tool execution may still silently fall back to the wrong backend if `site_id` or local backend URLs are not injected consistently.

## Success Criteria

- Generated `food` frontends render an input box and streamed chatbot responses instead of a literal `Chatbot` label.
- A logged-in `food` user can send a message and receive an LLM-backed response from the standalone chatbot server.
- The chatbot server resolves `site-a` automatically and executes existing adapter-backed tools without manual prompt instructions.
- Refresh clears the conversation, but the next login can immediately start a new chat.
- Onboarding generation and runtime validation both know how to wire the chatbot server without human directory hints.
