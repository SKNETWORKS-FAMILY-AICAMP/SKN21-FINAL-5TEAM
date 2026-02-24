from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


MAX_TEXT_LEN = 2000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate_text(text: str, max_len: int = MAX_TEXT_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...(truncated)"


def _serialize_message(msg: BaseMessage) -> Dict[str, Any]:
    role = "system"
    if isinstance(msg, HumanMessage):
        role = "user"
    elif isinstance(msg, AIMessage):
        role = "assistant"
    elif isinstance(msg, ToolMessage):
        role = "tool"

    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    payload: Dict[str, Any] = {
        "type": type(msg).__name__,
        "role": role,
        "content": _truncate_text(content),
    }

    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
        payload["tool_calls"] = msg.tool_calls

    if isinstance(msg, ToolMessage):
        payload["tool_call_id"] = msg.tool_call_id

    return payload


def safe_serialize(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, (str, int, float, bool)):
        if isinstance(data, str):
            return _truncate_text(data)
        return data
    if isinstance(data, BaseMessage):
        return _serialize_message(data)
    if isinstance(data, list):
        return [safe_serialize(item) for item in data]
    if isinstance(data, dict):
        return {str(k): safe_serialize(v) for k, v in data.items()}
    return _truncate_text(str(data))


def summarize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    messages = state.get("messages", []) if isinstance(state, dict) else []
    last_message = messages[-1] if isinstance(messages, list) and messages else None

    summary: Dict[str, Any] = {
        "keys": sorted(list(state.keys())) if isinstance(state, dict) else [],
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "last_message": safe_serialize(last_message) if isinstance(last_message, BaseMessage) else None,
        "task_list_len": len(state.get("task_list", [])) if isinstance(state.get("task_list"), list) else 0,
        "task_results_len": len(state.get("task_results", [])) if isinstance(state.get("task_results"), list) else 0,
        "current_task": safe_serialize(state.get("current_task")),
        "generation": _truncate_text(str(state.get("generation", ""))),
    }

    return summary


def summarize_state_changes(before: Any, after: Any) -> Dict[str, Any]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {
            "before": safe_serialize(before),
            "after": safe_serialize(after),
        }

    changed_keys: List[str] = []
    added_keys: List[str] = []
    removed_keys: List[str] = []

    before_keys = set(before.keys())
    after_keys = set(after.keys())

    for key in sorted(before_keys - after_keys):
        removed_keys.append(key)
    for key in sorted(after_keys - before_keys):
        added_keys.append(key)
    for key in sorted(before_keys & after_keys):
        if safe_serialize(before.get(key)) != safe_serialize(after.get(key)):
            changed_keys.append(key)

    return {
        "added_keys": added_keys,
        "removed_keys": removed_keys,
        "changed_keys": changed_keys,
        "before_summary": summarize_state(before),
        "after_summary": summarize_state(after),
    }


def _extract_usage_from_model_output(output: Any) -> Dict[str, Any]:
    if isinstance(output, AIMessage):
        usage_metadata = getattr(output, "usage_metadata", None)
        response_metadata = getattr(output, "response_metadata", None)
        if isinstance(usage_metadata, dict):
            return usage_metadata
        if isinstance(response_metadata, dict):
            token_usage = response_metadata.get("token_usage")
            if isinstance(token_usage, dict):
                return token_usage
    return {}


class ConversationRunLogger:
    def __init__(
        self,
        conversation_id: str,
        turn_id: str,
        user_id: Optional[int],
        provider: Optional[str],
        model: Optional[str],
        base_dir: Optional[str] = None,
    ):
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self.user_id = user_id
        self.provider = provider
        self.model = model
        self.base_dir = base_dir or os.getenv("CHATBOT_LOG_DIR", "logs/chatbot")

        self.started_at = _now_iso()
        self._run_start = time.perf_counter()
        self._node_starts: Dict[str, float] = {}
        self._model_starts: Dict[str, float] = {}
        self._tool_starts: Dict[str, float] = {}

        self.payload: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "user_id": user_id,
            "provider": provider,
            "model": model,
            "started_at": self.started_at,
            "status": "running",
            "input": {},
            "output": {},
            "metrics": {
                "duration_ms": 0,
                "token_usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            },
            "timeline": {
                "nodes": [],
                "tools": [],
                "models": [],
            },
            "errors": [],
        }

    def set_input(self, user_message: str, input_state: Dict[str, Any]) -> None:
        self.payload["input"] = {
            "user_message": _truncate_text(user_message),
            "state_summary": summarize_state(input_state),
        }

    def log_node_start(self, node_name: str, node_input: Any) -> None:
        key = f"{node_name}:{len(self.payload['timeline']['nodes'])}"
        self._node_starts[key] = time.perf_counter()
        self.payload["timeline"]["nodes"].append(
            {
                "node": node_name,
                "event": "start",
                "at": _now_iso(),
                "input": safe_serialize(node_input),
                "_timer_key": key,
            }
        )

    def log_node_end(self, node_name: str, node_output: Any) -> None:
        end_item = {
            "node": node_name,
            "event": "end",
            "at": _now_iso(),
            "output": safe_serialize(node_output),
            "duration_ms": None,
        }

        for item in reversed(self.payload["timeline"]["nodes"]):
            if item.get("node") == node_name and item.get("event") == "start" and item.get("_timer_key"):
                key = item.get("_timer_key")
                started = self._node_starts.pop(key, None)
                if started is not None:
                    end_item["duration_ms"] = int((time.perf_counter() - started) * 1000)
                break

        self.payload["timeline"]["nodes"].append(end_item)

    def log_model_start(self, model_name: str, model_input: Any) -> None:
        key = f"{model_name}:{len(self.payload['timeline']['models'])}"
        self._model_starts[key] = time.perf_counter()
        self.payload["timeline"]["models"].append(
            {
                "model": model_name,
                "event": "start",
                "at": _now_iso(),
                "input": safe_serialize(model_input),
                "_timer_key": key,
            }
        )

    def log_model_end(self, model_name: str, model_output: Any) -> None:
        usage = _extract_usage_from_model_output(model_output)

        end_item = {
            "model": model_name,
            "event": "end",
            "at": _now_iso(),
            "output": safe_serialize(model_output),
            "usage": usage,
            "duration_ms": None,
        }

        for item in reversed(self.payload["timeline"]["models"]):
            if item.get("model") == model_name and item.get("event") == "start" and item.get("_timer_key"):
                key = item.get("_timer_key")
                started = self._model_starts.pop(key, None)
                if started is not None:
                    end_item["duration_ms"] = int((time.perf_counter() - started) * 1000)
                break

        self._accumulate_usage(usage)
        self.payload["timeline"]["models"].append(end_item)

    def log_tool_start(self, tool_name: str, tool_input: Any) -> None:
        key = f"{tool_name}:{len(self.payload['timeline']['tools'])}"
        self._tool_starts[key] = time.perf_counter()
        self.payload["timeline"]["tools"].append(
            {
                "tool": tool_name,
                "event": "start",
                "at": _now_iso(),
                "input": safe_serialize(tool_input),
                "_timer_key": key,
            }
        )

    def log_tool_end(self, tool_name: str, tool_output: Any) -> None:
        end_item = {
            "tool": tool_name,
            "event": "end",
            "at": _now_iso(),
            "output": safe_serialize(tool_output),
            "duration_ms": None,
        }

        for item in reversed(self.payload["timeline"]["tools"]):
            if item.get("tool") == tool_name and item.get("event") == "start" and item.get("_timer_key"):
                key = item.get("_timer_key")
                started = self._tool_starts.pop(key, None)
                if started is not None:
                    end_item["duration_ms"] = int((time.perf_counter() - started) * 1000)
                break

        self.payload["timeline"]["tools"].append(end_item)

    def log_state_change(self, before_state: Any, after_state: Any) -> None:
        self.payload.setdefault("state_changes", []).append(
            {
                "at": _now_iso(),
                "changes": summarize_state_changes(before_state, after_state),
            }
        )

    def log_error(self, where: str, message: str) -> None:
        self.payload["errors"].append(
            {
                "at": _now_iso(),
                "where": where,
                "message": _truncate_text(message),
            }
        )

    def finalize(self, final_state: Optional[Dict[str, Any]], success: bool, error_message: Optional[str] = None) -> str:
        self.payload["status"] = "success" if success else "error"
        if error_message:
            self.log_error("finalize", error_message)

        self.payload["finished_at"] = _now_iso()
        self.payload["metrics"]["duration_ms"] = int((time.perf_counter() - self._run_start) * 1000)

        if isinstance(final_state, dict):
            self.payload["output"] = {
                "state_summary": summarize_state(final_state),
                "generation": _truncate_text(str(final_state.get("generation", ""))),
            }
            input_state = self.payload.get("input", {}).get("state_summary")
            if isinstance(input_state, dict):
                self.log_state_change({"summary": input_state}, {"summary": summarize_state(final_state)})

        log_path = self._write_jsonl()
        return log_path

    def _accumulate_usage(self, usage: Dict[str, Any]) -> None:
        metrics = self.payload["metrics"]["token_usage"]

        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))

        metrics["input_tokens"] += input_tokens
        metrics["output_tokens"] += output_tokens
        metrics["total_tokens"] += total_tokens

    def _write_jsonl(self) -> str:
        base = Path(self.base_dir)
        base.mkdir(parents=True, exist_ok=True)

        file_path = base / f"{self.conversation_id}.jsonl"
        with file_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self.payload, ensure_ascii=False) + "\n")

        return str(file_path)
