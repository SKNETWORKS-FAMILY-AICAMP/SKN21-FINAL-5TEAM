from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from .debug_logging import append_generation_log, append_llm_usage, write_llm_debug_artifact
from .framework_strategies import seam_target_rejection_reason
from .patch_planner import EditDraftPayload, EditOperationPayload, build_llm_patch_factory
from .workspace_editor import SUPPORTED_EDIT_OPERATIONS, apply_direct_edit_operations


def _normalize_evidence_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized[str(key)] = _normalize_evidence_value(item)
        return normalized
    if isinstance(value, (list, tuple, set)):
        return [_normalize_evidence_value(item) for item in value]
    return repr(value)


def attempt_llm_runtime_repair(
    *,
    run_root: Path,
    runtime_workspace: Path,
    failure_signature: str,
    evidence_payload: dict[str, Any],
    attempt_id: str,
    llm_factory: Callable[[], Any] | None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    report_root = run_root / "reports"
    report_root.mkdir(parents=True, exist_ok=True)

    if llm_factory is None:
        return {
            "attempt_id": attempt_id,
            "applied": False,
            "source": "hard_fallback",
            "failure_reason": "llm_runtime_repair_unavailable",
            "edit_path": None,
            "patch_path": None,
            "debug_path": None,
            "target_files": [],
            "applied_edits": [],
        }

    normalized_evidence = _normalize_evidence_value(evidence_payload)
    candidate_files = _build_candidate_file_list(
        runtime_workspace=runtime_workspace,
        evidence_payload=normalized_evidence,
    )
    prompt_payload = {
        "runtime_workspace": str(runtime_workspace),
        "failure_signature": failure_signature,
        "candidate_files": candidate_files,
        "file_samples": _read_file_samples(runtime_workspace=runtime_workspace, candidate_files=candidate_files),
        "evidence": normalized_evidence,
    }

    edit_path = report_root / f"runtime-repair-{attempt_id}.json"
    raw_response = ""
    normalized_response = ""
    debug_path: Path | None = None
    source = "hard_fallback"
    failure_reason = "llm_exception"
    guardrail_rejection_reason: str | None = None
    applied_edits: list[dict[str, str]] = []
    parsed_payload: Any = None

    try:
        llm = llm_factory()
        response = llm.invoke(
            [
                SystemMessage(content=_runtime_repair_system_prompt()),
                HumanMessage(content=json.dumps(prompt_payload, ensure_ascii=False, indent=2)),
            ]
        )
        raw_response = str(response.content)
        append_llm_usage(
            report_root=report_root,
            component="llm_runtime_repair",
            provider=provider,
            model=model or getattr(llm, "model_name", None),
            usage={},
        )
        normalized_response = _normalize_patch_response(raw_response)
        if not normalized_response.strip():
            failure_reason = "invalid_llm_response"
        else:
            parsed_payload = json.loads(normalized_response)
            payload = EditDraftPayload.model_validate(parsed_payload)
            failure_reason, guardrail_rejection_reason = _validate_edit_operations(
                operations=payload.operations,
                candidate_files=candidate_files,
            )
            if failure_reason is None:
                edit_path.write_text(
                    json.dumps(
                        {
                            "operations": [item.model_dump(mode="json") for item in payload.operations],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                try:
                    apply_result = apply_direct_edit_operations(
                        workspace_root=runtime_workspace,
                        operations=[item.model_dump(mode="json") for item in payload.operations],
                    )
                except Exception:
                    failure_reason = "edit_apply_failed"
                else:
                    applied_edits = list(apply_result.get("applied_edits") or [])
                    source = "llm"
                    failure_reason = None
    except json.JSONDecodeError:
        failure_reason = "invalid_llm_response"
    except ValidationError:
        failure_reason = "edit_payload_invalid"
    except Exception:
        failure_reason = "llm_exception"

    debug_payload = {
        "status": "applied" if failure_reason is None else "hard_fallback",
        "source": source,
        "failure_reason": failure_reason,
        "guardrail_rejection_reason": guardrail_rejection_reason,
        "failure_signature": failure_signature,
        "raw_response": raw_response,
        "normalized_response": normalized_response,
        "parsed_payload": parsed_payload,
        "candidate_files": candidate_files,
        "target_files": [item["path"] for item in applied_edits],
        "applied_edits": applied_edits,
        "edit_path": str(edit_path) if edit_path.exists() else None,
    }
    debug_path = write_llm_debug_artifact(
        report_root=report_root,
        name=f"runtime-repair-{attempt_id}",
        payload=debug_payload,
    )
    append_generation_log(
        report_root=report_root,
        level="INFO" if failure_reason is None else "WARN",
        component="runtime_llm_repair",
        event="llm_runtime_repair_applied" if failure_reason is None else "llm_runtime_repair_failed",
        message="llm runtime repair applied" if failure_reason is None else "llm runtime repair failed",
        details={
            "failure_signature": failure_signature,
            "source": source,
            "edit_path": str(edit_path) if edit_path.exists() else None,
            "debug_path": str(debug_path),
            "failure_reason": failure_reason,
            "guardrail_rejection_reason": guardrail_rejection_reason,
            "target_files": debug_payload["target_files"],
            "applied_edits": applied_edits,
        },
    )
    return {
        "attempt_id": attempt_id,
        "applied": failure_reason is None,
        "source": source,
        "failure_reason": failure_reason,
        "guardrail_rejection_reason": guardrail_rejection_reason,
        "edit_path": str(edit_path) if edit_path.exists() else None,
        "patch_path": None,
        "debug_path": str(debug_path),
        "target_files": debug_payload["target_files"],
        "applied_edits": applied_edits,
    }


def build_runtime_repair_factory(
    *,
    enabled: bool,
    llm_factory: Callable[[], Any] | None,
    provider: str,
    model: str,
) -> Callable[[], Any] | None:
    if llm_factory is not None:
        return llm_factory
    if not enabled:
        return None
    return build_llm_patch_factory(provider=provider, model=model)


def _runtime_repair_system_prompt() -> str:
    return (
        "You are a runtime repair edit generator.\n"
        "Return only JSON with key `operations`.\n"
        "Each operation must include `path`, `operation`, and only the fields required for that operation.\n"
        "Allowed operations: replace_text, insert_after, insert_before, append_text.\n"
        "Only edit files from the provided candidate_files list.\n"
        "Do not wrap the response in markdown fences.\n"
        "If no safe edit can be produced, return an empty string.\n"
    )


def _normalize_patch_response(raw_response: str) -> str:
    content = raw_response.strip()
    if content.startswith("*** Begin Patch"):
        return ""
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", content)
        content = re.sub(r"\n```$", "", content)
    return content.strip()


def _build_candidate_file_list(*, runtime_workspace: Path, evidence_payload: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    candidate_set: set[str] = set()
    text_blobs: list[str] = []
    normalized_evidence = _normalize_evidence_value(evidence_payload)
    for value in normalized_evidence.values():
        if isinstance(value, str):
            text_blobs.append(value)
        elif isinstance(value, dict):
            text_blobs.append(json.dumps(value, ensure_ascii=False))
        elif isinstance(value, list):
            text_blobs.append(json.dumps(value, ensure_ascii=False))

    def _add_candidate(relative_path: str) -> None:
        normalized = relative_path.strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized.startswith("/"):
            return
        if ".." in Path(normalized).parts:
            return
        if normalized in candidate_set:
            return
        if (runtime_workspace / normalized).exists():
            candidates.append(normalized)
            candidate_set.add(normalized)

    for blob in text_blobs:
        normalized_blob = blob.replace(str(runtime_workspace) + "/", "")
        for match in re.findall(r"([A-Za-z0-9_./-]+\.(?:jsx|tsx|ts|js|py))", normalized_blob):
            _add_candidate(match)
        for import_match in re.findall(r"from\s+([A-Za-z0-9_.]+)\s+import", blob):
            module_path = import_match.replace(".", "/") + ".py"
            _add_candidate(module_path)
        for import_match in re.findall(r"import\s+([A-Za-z0-9_.]+)", blob):
            module_path = import_match.replace(".", "/") + ".py"
            _add_candidate(module_path)
        if "backend_readiness_failed" in blob or "ModuleNotFoundError" in blob:
            for path in [
                "backend/manage.py",
                "backend/foodshop/urls.py",
                "backend/chat_auth.py",
                "backend/users/views.py",
            ]:
                _add_candidate(path)
        if "frontend_readiness_failed" in blob or "Module not found" in blob or "Can't resolve" in blob:
            for path in [
                "frontend/src/App.js",
                "frontend/src/App.jsx",
                "frontend/src/chatbot/SharedChatbotWidget.jsx",
                "frontend/src/chatbot/ChatbotWidget.jsx",
            ]:
                _add_candidate(path)
        if any(marker in blob for marker in ["chatbot_mount_missing", "chatbot_status_not_rendered", "auth_bootstrap", "routes child violation"]):
            for path in [
                "frontend/src/App.js",
                "frontend/src/App.jsx",
                "frontend/src/main.jsx",
                "frontend/src/main.js",
            ]:
                _add_candidate(path)
    if candidates:
        return candidates[:10]
    fallback_candidates = [
        path.relative_to(runtime_workspace).as_posix()
        for path in runtime_workspace.rglob("*")
        if path.is_file() and path.suffix in {".py", ".js", ".jsx", ".ts", ".tsx"}
    ]
    return fallback_candidates[:10]


def _read_file_samples(*, runtime_workspace: Path, candidate_files: list[str]) -> dict[str, str]:
    samples: dict[str, str] = {}
    for relative_path in candidate_files:
        path = runtime_workspace / relative_path
        if not path.exists() or not path.is_file():
            continue
        samples[relative_path] = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    return samples


def _validate_edit_operations(
    *,
    operations: list[EditOperationPayload],
    candidate_files: list[str],
) -> tuple[str | None, str | None]:
    if not operations:
        return ("edit_payload_invalid", None)
    candidate_set = set(candidate_files)
    for operation in operations:
        if operation.operation not in SUPPORTED_EDIT_OPERATIONS:
            return ("edit_payload_invalid", None)
        if operation.path.startswith("/") or ".." in Path(operation.path).parts:
            return ("edit_target_rejected", None)
        seam_rejection = seam_target_rejection_reason(operation.path)
        if seam_rejection is not None:
            return (seam_rejection, seam_rejection)
        if operation.path not in candidate_set:
            return ("edit_target_rejected", None)
        if operation.operation in {"insert_after", "insert_before"} and not operation.anchor:
            return ("edit_payload_invalid", None)
        if operation.operation in {"insert_after", "insert_before", "append_text"} and not operation.content:
            return ("edit_payload_invalid", None)
        if operation.operation == "replace_text" and (not operation.old or operation.new is None):
            return ("edit_payload_invalid", None)
    return (None, None)
