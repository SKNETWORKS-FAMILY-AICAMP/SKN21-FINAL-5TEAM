from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any


_MARKER = "__RUNTIME_VALIDATION_JSON__"


def _emit(payload: dict[str, Any]) -> None:
    print(f"{_MARKER}{json.dumps(payload, ensure_ascii=False)}")


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _load_payload(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    args = parser.parse_args(argv)
    request = _load_payload(args.payload)

    try:
        from src.onboarding_v2.models.analysis import AnalysisSnapshot
        from src.onboarding_v2.models.planning import IntegrationPlan
        from src.onboarding_v2.models.validation import (
            BackendRuntimePlan,
            BackendRuntimePrepResult,
            WidgetOrderE2EResult,
        )
        from src.onboarding_v2.validation import runner

        action = str(request.get("action") or "").strip()
        runtime_plan = BackendRuntimePlan.model_validate(request["runtime_plan"])
        plan = IntegrationPlan.model_validate(request["plan"])
        payload = dict(request.get("payload") or {})
        chatbot_runtime_workspace = Path(
            str(request.get("chatbot_runtime_workspace") or Path.cwd())
        ).resolve()

        if action == "chatbot_runtime_boot":
            result = runner._validate_chatbot_runtime_boot_inprocess(
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                plan=plan,
            )
            events = []
        elif action == "adapter_auth":
            result = runner._validate_chatbot_adapter_auth_inprocess(
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                bootstrap_result=dict(payload.get("bootstrap_result") or {}),
                plan=plan,
            )
            events: list[dict[str, Any]] = []
        elif action == "widget_bundle_fetch":
            result = runner._validate_widget_bundle_fetch_inprocess(
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                plan=plan,
            )
            events = []
        elif action == "widget_order_e2e":
            result = runner._validate_widget_order_e2e_inprocess(
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                bootstrap_result=dict(payload.get("bootstrap_result") or {}),
                adapter_auth_result=dict(payload.get("adapter_auth_result") or {}),
                plan=plan,
            )
            events = []
        elif action == "conversation_runtime":
            recorded_events: list[dict[str, Any]] = []
            snapshot = AnalysisSnapshot.model_validate(payload["snapshot"])
            prep_result = BackendRuntimePrepResult.model_validate(payload["prep_result"])
            widget_order_e2e_result_payload = payload.get("widget_order_e2e_result")
            widget_order_e2e_result = (
                WidgetOrderE2EResult.model_validate(widget_order_e2e_result_payload)
                if widget_order_e2e_result_payload is not None
                else None
            )
            result = runner._validate_conversation_runtime_inprocess(
                run_root=Path(str(payload["run_root"])),
                chatbot_runtime_workspace=chatbot_runtime_workspace,
                runtime_plan=runtime_plan,
                snapshot=snapshot,
                plan=plan,
                prep_result=prep_result,
                bootstrap_result=dict(payload.get("bootstrap_result") or {}),
                adapter_auth_result=dict(payload.get("adapter_auth_result") or {}),
                widget_order_e2e_result=widget_order_e2e_result,
                onboarding_credentials=dict(payload.get("onboarding_credentials") or {}),
                event_callback=recorded_events.append,
                live_logs_root=payload.get("live_logs_root"),
            )
            events = recorded_events
        else:
            raise ValueError(f"unsupported runtime validation action: {action}")

        _emit({"ok": True, "result": _to_jsonable(result), "events": _to_jsonable(events)})
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
