from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from .debug_logging import append_generation_log, append_llm_usage, write_llm_debug_artifact
from .patch_planner import build_llm_patch_factory
from .runtime_runner import _apply_patch_file, _extract_patch_target_files


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
    patch_root = run_root / "patches"
    patch_root.mkdir(parents=True, exist_ok=True)

    if llm_factory is None:
        return {
            "attempt_id": attempt_id,
            "applied": False,
            "source": "hard_fallback",
            "failure_reason": "llm_runtime_repair_unavailable",
            "patch_path": None,
            "debug_path": None,
            "target_files": [],
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

    patch_path = patch_root / f"runtime-repair-{attempt_id}.patch"
    raw_response = ""
    normalized_patch = ""
    debug_path: Path | None = None
    source = "hard_fallback"
    failure_reason = "llm_exception"

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
        normalized_patch = _normalize_patch_response(raw_response)
        if normalized_patch and not normalized_patch.endswith("\n"):
            normalized_patch += "\n"
        if not normalized_patch.strip():
            failure_reason = "invalid_llm_response"
        else:
            patch_path.write_text(normalized_patch, encoding="utf-8")
            target_files = _extract_patch_target_files(patch_path)
            target_validation_error = _validate_patch_targets(target_files)
            if target_validation_error is not None:
                failure_reason = target_validation_error
            else:
                apply_failure = _apply_patch_file(patch_path=patch_path, workspace=runtime_workspace)
                if apply_failure is None:
                    source = "llm"
                    failure_reason = None
                else:
                    failure_reason = str(apply_failure.get("error") or "patch_apply_failed")
    except Exception:
        failure_reason = "llm_exception"

    debug_payload = {
        "status": "applied" if failure_reason is None else "hard_fallback",
        "source": source,
        "failure_reason": failure_reason,
        "failure_signature": failure_signature,
        "raw_response": raw_response,
        "normalized_response": normalized_patch,
        "candidate_files": candidate_files,
        "target_files": _extract_patch_target_files(patch_path) if patch_path.exists() else [],
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
            "patch_path": str(patch_path),
            "debug_path": str(debug_path),
            "failure_reason": failure_reason,
            "target_files": debug_payload["target_files"],
        },
    )
    return {
        "attempt_id": attempt_id,
        "applied": failure_reason is None,
        "source": source,
        "failure_reason": failure_reason,
        "patch_path": str(patch_path),
        "debug_path": str(debug_path),
        "target_files": debug_payload["target_files"],
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
    return """You are a runtime repair patch generator.
Return only a unified diff patch. Do not wrap in markdown fences. Do not explain.
Patch only files inside the provided runtime workspace. Do not reference absolute paths.
Prefer the smallest safe fix that addresses the observed runtime failure.
If the evidence indicates a Python import/path mismatch, edit the referenced file directly.
If no safe patch can be produced, return an empty string."""


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


def _validate_patch_targets(target_files: list[str]) -> str | None:
    if not target_files:
        return "invalid_patch_targets"
    for target in target_files:
        if target.startswith("/") or ".." in Path(target).parts:
            return "invalid_patch_targets"
    return None
