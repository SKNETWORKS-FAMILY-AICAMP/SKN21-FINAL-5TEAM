from __future__ import annotations

import json
from typing import Any

from .approval_store import ApprovalStore
from .slack_bridge import InMemorySlackBridge


def handle_interactive_action(
    *,
    payload: dict[str, Any],
    store: ApprovalStore,
    bridge: InMemorySlackBridge | None = None,
) -> dict[str, Any]:
    user_id = str((payload.get("user") or {}).get("id") or "")
    actions = list(payload.get("actions") or [])
    if not actions:
        return {"ok": False, "applied": False, "error": "missing actions"}

    value = parse_action_value(actions[0].get("value") or {})

    run_id = str(value.get("run_id") or "")
    approval_type = str(value.get("approval_type") or "")
    decision = str(value.get("decision") or "")
    if not run_id or not approval_type or not decision:
        return {"ok": False, "applied": False, "error": "invalid action value"}

    current = store.get_decision(run_id=run_id, approval_type=approval_type)
    if current is None:
        store.create_request(run_id=run_id, approval_type=approval_type)
        current = store.get_decision(run_id=run_id, approval_type=approval_type)

    if current is not None and current.get("status") != "pending":
        return {"ok": True, "applied": False}

    store.record_decision(
        run_id=run_id,
        approval_type=approval_type,
        decision=decision,
        actor=user_id,
    )
    if bridge is not None:
        bridge.record_approval_decision(
            run_id=run_id,
            approval_type=approval_type,
            decision=decision,
        )
    return {"ok": True, "applied": True}


def register_socket_mode_handler(
    *,
    client: Any,
    store: ApprovalStore,
    bridge: InMemorySlackBridge | None = None,
    ack,
) -> None:
    def _listener(_socket_client, request: Any) -> None:
        envelope_id = _get_value(request, "envelope_id")
        if envelope_id:
            ack(str(envelope_id))

        payload = _get_value(request, "payload") or {}
        if _get_value(payload, "type") != "block_actions":
            return
        handle_interactive_action(payload=payload, store=store, bridge=bridge)

    client.socket_mode_request_listeners.append(_listener)


def _get_value(container: Any, key: str) -> Any:
    if isinstance(container, dict):
        return container.get(key)
    return getattr(container, key, None)


def parse_action_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}
