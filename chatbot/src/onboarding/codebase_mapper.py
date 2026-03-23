from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from chatbot.src.graph.llm_providers import make_chat_llm

from .onboarding_ignore import OnboardingIgnoreMatcher
from .site_analyzer import analyze_site
from .debug_logging import (
    append_generation_log,
    append_llm_usage,
    append_onboarding_event,
    append_recovery_event,
    extract_llm_usage,
    write_llm_debug_artifact,
)


TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}


class RankedCandidate(BaseModel):
    path: str
    reason: str


class CodebaseInterpretationPayload(BaseModel):
    structure_summary: str
    framework_assessment: dict[str, Any]
    ranked_candidates: list[RankedCandidate]


def build_codebase_map(*, source_root: str | Path) -> dict:
    root = Path(source_root)
    ignore_matcher = OnboardingIgnoreMatcher(root)
    analysis = analyze_site(root)
    integration_contract = analysis["integration_contract"]
    files: list[str] = []
    candidate_edit_targets: list[dict[str, str]] = []
    auth_candidates: list[dict[str, object]] = []
    urlconf_candidates: list[dict[str, object]] = []
    frontend_component_candidates: list[dict[str, object]] = []
    api_client_candidates: list[dict[str, str]] = []
    backend_texts: list[str] = []
    frontend_texts: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not ignore_matcher.includes(path):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix()
        files.append(relative)

        content = _read_text(path)
        if content is None:
            continue
        if path.suffix == ".py":
            backend_texts.append(content)
        elif path.suffix in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            frontend_texts.append(content)

        auth_candidate = _build_auth_candidate(relative, content)
        urlconf_candidate = _build_urlconf_candidate(relative, content)
        frontend_candidate = _build_frontend_component_candidate(relative, path, content)
        api_client_candidate = _build_api_client_candidate(relative, path, content)

        reason = _infer_reason(relative, path, content)
        if reason is None:
            if auth_candidate is not None:
                reason = "backend auth or session handler candidate"
            elif urlconf_candidate is not None:
                reason = "backend route or handler candidate"
            elif frontend_candidate is not None:
                reason = "frontend mount or integration candidate"
            elif api_client_candidate is not None:
                reason = str(api_client_candidate.get("reason") or "frontend api client candidate")

        if reason is not None:
            candidate_edit_targets.append(
                {
                    "path": relative,
                    "reason": reason,
                }
            )

        if auth_candidate is not None:
            auth_candidates.append(auth_candidate)

        if urlconf_candidate is not None:
            urlconf_candidates.append(urlconf_candidate)

        if frontend_candidate is not None:
            frontend_component_candidates.append(frontend_candidate)
        if api_client_candidate is not None:
            api_client_candidates.append(api_client_candidate)

    backend_strategy = _detect_backend_strategy("\n".join(backend_texts))
    frontend_strategy = _detect_frontend_strategy(frontend_component_candidates, "\n".join(frontend_texts))
    backend_route_targets = _build_backend_route_targets(
        integration_contract=integration_contract,
        urlconf_candidates=urlconf_candidates,
        candidate_edit_targets=candidate_edit_targets,
    )
    frontend_mount_targets = _build_frontend_mount_targets(frontend_component_candidates)
    tool_registry_targets = _build_tool_registry_targets(auth_candidates, candidate_edit_targets)
    order_bridge_targets = _build_order_bridge_targets(
        analysis=analysis,
        candidate_edit_targets=candidate_edit_targets,
    )
    auth_session_resolver_candidates = _build_auth_session_resolver_candidates(auth_candidates)
    frontend_app_shell_candidates = _build_frontend_app_shell_candidates(frontend_component_candidates)
    frontend_router_boundaries = _build_frontend_router_boundaries(frontend_component_candidates)
    validated_frontend_mount_targets = _build_validated_frontend_mount_targets(frontend_mount_targets)

    return {
        "source_root": str(root),
        "files": files,
        "backend_strategy": backend_strategy,
        "frontend_strategy": frontend_strategy,
        "integration_contract": integration_contract,
        "candidate_edit_targets": candidate_edit_targets,
        "auth_candidates": auth_candidates,
        "auth_session_resolver_candidates": auth_session_resolver_candidates,
        "urlconf_candidates": urlconf_candidates,
        "frontend_component_candidates": frontend_component_candidates,
        "frontend_app_shell_candidates": frontend_app_shell_candidates,
        "frontend_router_boundaries": frontend_router_boundaries,
        "api_client_candidates": api_client_candidates,
        "backend_route_targets": backend_route_targets,
        "frontend_mount_targets": frontend_mount_targets,
        "validated_frontend_mount_targets": validated_frontend_mount_targets,
        "tool_registry_targets": tool_registry_targets,
        "order_bridge_targets": order_bridge_targets,
    }


def _detect_backend_strategy(combined: str) -> str:
    if "from fastapi import" in combined or "FastAPI(" in combined or "APIRouter(" in combined:
        return "fastapi"
    if "from flask import" in combined or "Flask(" in combined or "Blueprint(" in combined:
        return "flask"
    if "from django." in combined or "urlpatterns" in combined or "path(" in combined:
        return "django"
    return "unknown"


def _detect_frontend_strategy(frontend_candidates: list[dict[str, object]], combined: str) -> str:
    if any(str(item.get("path") or "").endswith(".vue") for item in frontend_candidates):
        return "vue"
    if "React" in combined or "function App" in combined or "return <" in combined:
        return "react"
    return "unknown"


def _build_backend_route_targets(
    *,
    integration_contract: dict[str, Any],
    urlconf_candidates: list[dict[str, object]],
    candidate_edit_targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    contract_points = [
        str(path).strip()
        for path in ((integration_contract.get("backend") or {}).get("route_registration_points") or [])
        if str(path).strip()
    ]
    if contract_points:
        return [
            {
                "path": path,
                "reason": "backend route wiring candidate",
            }
            for path in contract_points
        ]
    if urlconf_candidates:
        return [
            {
                "path": str(item.get("path") or ""),
                "reason": "backend route wiring candidate",
            }
            for item in urlconf_candidates
            if str(item.get("path") or "")
        ]
    return [
        item
        for item in candidate_edit_targets
        if str(item.get("path") or "").lower().endswith(("main.py", "app.py"))
    ]


def _build_frontend_mount_targets(
    frontend_component_candidates: list[dict[str, object]],
) -> list[dict[str, str]]:
    return [
        {
            "path": str(item.get("path") or ""),
            "reason": "frontend mount candidate",
        }
        for item in frontend_component_candidates
        if str(item.get("path") or "")
    ]


def _build_tool_registry_targets(
    auth_candidates: list[dict[str, object]],
    candidate_edit_targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    if auth_candidates:
        return [
            {
                "path": str(item.get("path") or ""),
                "reason": "backend tool registry candidate",
            }
            for item in auth_candidates
            if str(item.get("path") or "")
        ]
    return [
        item
        for item in candidate_edit_targets
        if str(item.get("path") or "").startswith("backend/")
    ][:3]


def _build_order_bridge_targets(
    *,
    analysis: dict[str, Any],
    candidate_edit_targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    explicit_targets = [
        {
            "path": str(path),
            "reason": "host order bridge compatibility target",
        }
        for path in (analysis.get("order_bridge_targets") or [])
        if str(path).strip()
    ]
    if explicit_targets:
        return explicit_targets

    return [
        {
            "path": str(item.get("path") or ""),
            "reason": "host order bridge fallback target",
        }
        for item in candidate_edit_targets
        if str(item.get("path") or "").startswith("backend/")
        and "order" in str(item.get("path") or "").lower()
    ][:3]


def _build_auth_session_resolver_candidates(
    auth_candidates: list[dict[str, object]],
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for item in auth_candidates:
        path = str(item.get("path") or "")
        markers = {str(marker) for marker in item.get("auth_markers") or []}
        if not path:
            continue
        if markers.intersection({"session_token", "request.COOKIES", "request.cookies", "SessionToken"}) or {
            "login",
            "me",
        }.intersection({str(name) for name in item.get("functions") or []}):
            results.append({"path": path, "reason": "auth or session resolver candidate"})
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in results:
        if item["path"] in seen:
            continue
        deduped.append(item)
        seen.add(item["path"])
    return deduped


def _build_frontend_app_shell_candidates(
    frontend_component_candidates: list[dict[str, object]],
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for item in frontend_component_candidates:
        path = str(item.get("path") or "")
        if not path:
            continue
        if Path(path).stem.lower() == "app":
            results.append({"path": path, "reason": "frontend app shell candidate"})
    return results


def _build_frontend_router_boundaries(
    frontend_component_candidates: list[dict[str, object]],
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for item in frontend_component_candidates:
        path = str(item.get("path") or "")
        markers = {str(marker) for marker in item.get("markers") or []}
        if not path:
            continue
        if markers.intersection({"<BrowserRouter", "<Routes", "<template"}):
            results.append({"path": path, "reason": "frontend router boundary candidate"})
    return results


def _build_validated_frontend_mount_targets(
    frontend_mount_targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        {
            "path": str(item.get("path") or ""),
            "reason": "validated frontend mount target",
        }
        for item in frontend_mount_targets
        if str(item.get("path") or "").startswith("frontend/src/")
    ]


def write_codebase_map(*, source_root: str | Path, output_path: str | Path) -> Path:
    payload = build_codebase_map(source_root=source_root)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_llm_codebase_interpretation(
    *,
    source_root: str | Path,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    output_path: str | Path,
    llm_factory: Callable[[], Any],
    provider: str | None = None,
    model: str | None = None,
) -> Path:
    fallback_candidates = list(codebase_map.get("candidate_edit_targets") or [])[:5]
    report_root = Path(output_path).parent
    payload = {
        "source": "hard_fallback",
        "recovery_applied": False,
        "recovery_reason": None,
        "hard_fallback_reason": "llm_exception",
        "fallback_reason": "llm_exception",
        "validation_error": None,
        "recovered_payload": None,
        "structure_summary": "fallback deterministic interpretation",
        "framework_assessment": {
            "backend": ((analysis.get("framework") or {}).get("backend") or "unknown"),
            "frontend": ((analysis.get("framework") or {}).get("frontend") or "unknown"),
        },
        "ranked_candidates": fallback_candidates,
    }
    debug_payload: dict[str, Any] = {
        "status": "started",
        "fallback_reason": None,
        "recovery_reason": None,
        "hard_fallback_reason": None,
        "raw_response": "",
        "normalized_response": None,
        "recovered_payload": None,
        "validation_error": None,
        "error_type": None,
        "error_message": None,
    }
    append_generation_log(
        report_root=report_root,
        level="INFO",
        component="codebase_mapper",
        event="llm_codebase_interpretation_started",
        message="starting llm codebase interpretation",
        details={"provider": provider or "unknown", "model": model or "unknown"},
    )
    append_onboarding_event(
        report_root=report_root,
        run_id="unknown",
        component="codebase_mapper",
        stage="analysis",
        event="llm_call_started",
        severity="info",
        summary="llm codebase interpretation started",
        source="llm",
        details={"provider": provider or "unknown", "model": model or "unknown"},
    )
    try:
        llm = llm_factory()
        response = llm.invoke(
            [
                SystemMessage(content=_llm_codebase_interpretation_system_prompt()),
                HumanMessage(
                    content=json.dumps(
                        {
                            "source_root": str(source_root),
                            "analysis": analysis,
                            "codebase_map": codebase_map,
                            "file_samples": _build_codebase_file_samples(source_root, codebase_map),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            ]
        )
        debug_payload["raw_response"] = str(response.content)
        append_llm_usage(
            report_root=report_root,
            component="llm_codebase_interpretation",
            provider=provider,
            model=model or getattr(llm, "model_name", None),
            usage=extract_llm_usage(response),
        )
        raw_payload = json.loads(str(response.content))
        llm_payload = CodebaseInterpretationPayload.model_validate(raw_payload)
        llm_payload, dropped_ranked_candidates, ranked_candidate_recovery_reason = _accept_ranked_candidates(
            llm_payload=llm_payload,
            codebase_map=codebase_map,
        )
        debug_payload["status"] = "recovered_llm" if ranked_candidate_recovery_reason else "llm"
        debug_payload["recovery_reason"] = ranked_candidate_recovery_reason
        debug_payload["normalized_response"] = llm_payload.model_dump(mode="json")
        debug_payload["dropped_ranked_candidates"] = dropped_ranked_candidates
        payload = {
            "source": "recovered_llm" if ranked_candidate_recovery_reason else "llm",
            "recovery_applied": bool(ranked_candidate_recovery_reason),
            "recovery_reason": ranked_candidate_recovery_reason,
            "hard_fallback_reason": None,
            "fallback_reason": None,
            "validation_error": None,
            "recovered_payload": None,
            "dropped_ranked_candidates": dropped_ranked_candidates,
            "structure_summary": llm_payload.structure_summary,
            "framework_assessment": llm_payload.framework_assessment,
            "ranked_candidates": llm_payload.model_dump(mode="json")["ranked_candidates"],
        }
    except json.JSONDecodeError as exc:
        debug_payload["status"] = "hard_fallback"
        debug_payload["fallback_reason"] = "invalid_llm_response"
        debug_payload["hard_fallback_reason"] = "invalid_llm_response"
        debug_payload["error_type"] = type(exc).__name__
        debug_payload["error_message"] = str(exc)
        payload["hard_fallback_reason"] = "invalid_llm_response"
        payload["fallback_reason"] = "invalid_llm_response"
    except ValidationError as exc:
        debug_payload["error_type"] = type(exc).__name__
        debug_payload["error_message"] = str(exc)
        debug_payload["validation_error"] = str(exc)
        recovered = _recover_codebase_interpretation_payload(
            raw_payload,
            codebase_map=codebase_map,
        )
        if recovered is not None:
            recovered_payload, recovery_reason = recovered
            try:
                llm_payload = CodebaseInterpretationPayload.model_validate(recovered_payload)
                llm_payload, dropped_ranked_candidates, ranked_candidate_recovery_reason = _accept_ranked_candidates(
                    llm_payload=llm_payload,
                    codebase_map=codebase_map,
                )
            except ValidationError:
                debug_payload["status"] = "hard_fallback"
                debug_payload["fallback_reason"] = "invalid_llm_payload"
                debug_payload["hard_fallback_reason"] = "invalid_llm_payload"
                debug_payload["recovered_payload"] = recovered_payload
                payload["validation_error"] = str(exc)
                payload["recovered_payload"] = recovered_payload
                payload["hard_fallback_reason"] = "invalid_llm_payload"
                payload["fallback_reason"] = "invalid_llm_payload"
            except ValueError as recovered_exc:
                debug_payload["status"] = "hard_fallback"
                debug_payload["fallback_reason"] = "invalid_ranked_candidates"
                debug_payload["hard_fallback_reason"] = "invalid_ranked_candidates"
                debug_payload["error_type"] = type(recovered_exc).__name__
                debug_payload["error_message"] = str(recovered_exc)
                debug_payload["recovered_payload"] = recovered_payload
                payload["validation_error"] = str(exc)
                payload["recovered_payload"] = recovered_payload
                payload["hard_fallback_reason"] = "invalid_ranked_candidates"
                payload["fallback_reason"] = "invalid_ranked_candidates"
            else:
                effective_recovery_reason = ranked_candidate_recovery_reason or recovery_reason
                debug_payload["status"] = "recovered_llm"
                debug_payload["recovery_reason"] = effective_recovery_reason
                debug_payload["normalized_response"] = llm_payload.model_dump(mode="json")
                debug_payload["recovered_payload"] = recovered_payload
                debug_payload["dropped_ranked_candidates"] = dropped_ranked_candidates
                payload = {
                    "source": "recovered_llm",
                    "recovery_applied": True,
                    "recovery_reason": effective_recovery_reason,
                    "hard_fallback_reason": None,
                    "fallback_reason": None,
                    "validation_error": str(exc),
                    "recovered_payload": recovered_payload,
                    "dropped_ranked_candidates": dropped_ranked_candidates,
                    "structure_summary": llm_payload.structure_summary,
                    "framework_assessment": llm_payload.framework_assessment,
                    "ranked_candidates": llm_payload.model_dump(mode="json")["ranked_candidates"],
                }
        else:
            debug_payload["status"] = "hard_fallback"
            debug_payload["fallback_reason"] = "invalid_llm_payload"
            debug_payload["hard_fallback_reason"] = "invalid_llm_payload"
            payload["validation_error"] = str(exc)
            payload["hard_fallback_reason"] = "invalid_llm_payload"
            payload["fallback_reason"] = "invalid_llm_payload"
    except ValueError as exc:
        debug_payload["status"] = "hard_fallback"
        debug_payload["fallback_reason"] = "invalid_ranked_candidates"
        debug_payload["hard_fallback_reason"] = "invalid_ranked_candidates"
        debug_payload["error_type"] = type(exc).__name__
        debug_payload["error_message"] = str(exc)
        payload["hard_fallback_reason"] = "invalid_ranked_candidates"
        payload["fallback_reason"] = "invalid_ranked_candidates"
    except Exception as exc:
        debug_payload["status"] = "hard_fallback"
        debug_payload["fallback_reason"] = "llm_exception"
        debug_payload["hard_fallback_reason"] = "llm_exception"
        debug_payload["error_type"] = type(exc).__name__
        debug_payload["error_message"] = str(exc)
        payload["hard_fallback_reason"] = "llm_exception"
        payload["fallback_reason"] = "llm_exception"

    debug_path = write_llm_debug_artifact(
        report_root=report_root,
        name="codebase-interpretation",
        payload=debug_payload,
    )
    append_onboarding_event(
        report_root=report_root,
        run_id="unknown",
        component="codebase_mapper",
        stage="analysis",
        event="artifact_written",
        severity="info",
        summary="codebase interpretation debug artifact written",
        source=payload["source"],
        details={"artifact_kind": "llm_debug"},
        debug_artifact_path=str(debug_path),
    )
    if payload["source"] in {"recovered_llm", "hard_fallback"}:
        append_generation_log(
            report_root=report_root,
            level="WARN",
            component="codebase_mapper",
            event="recovery_started",
            message="codebase interpretation recovery started",
            details={
                "source": payload["source"],
                "recovery_reason": payload.get("recovery_reason"),
                "hard_fallback_reason": payload.get("hard_fallback_reason"),
            },
        )
        append_generation_log(
            report_root=report_root,
            level="INFO" if payload["source"] == "recovered_llm" else "WARN",
            component="codebase_mapper",
            event="recovery_succeeded" if payload["source"] == "recovered_llm" else "hard_fallback_used",
            message="codebase interpretation recovered" if payload["source"] == "recovered_llm" else "codebase interpretation used hard fallback",
            details={
                "source": payload["source"],
                "recovery_reason": payload.get("recovery_reason"),
                "hard_fallback_reason": payload.get("hard_fallback_reason"),
            },
        )
    if payload["source"] in {"recovered_llm", "hard_fallback"}:
        append_recovery_event(
            report_root=report_root,
            component="llm_codebase_interpretation",
            source=str(payload["source"]),
            recovery_reason=payload.get("recovery_reason"),
            hard_fallback_reason=payload.get("hard_fallback_reason"),
        )
    if payload["source"] in {"llm", "recovered_llm"}:
        append_onboarding_event(
            report_root=report_root,
            run_id="unknown",
            component="codebase_mapper",
            stage="analysis",
            event="llm_output_accepted",
            severity="info",
            summary="llm codebase interpretation accepted",
            source=payload["source"],
            recovery={
                "applied": bool(payload.get("recovery_applied")),
                "reason": payload.get("recovery_reason"),
            } if payload["source"] == "recovered_llm" else None,
            details={"output_path": str(output_path)},
            debug_artifact_path=str(debug_path),
        )
    elif payload["source"] == "hard_fallback":
        append_onboarding_event(
            report_root=report_root,
            run_id="unknown",
            component="codebase_mapper",
            stage="analysis",
            event="hard_fallback_used",
            severity="warn",
            summary="llm codebase interpretation used hard fallback",
            source="hard_fallback",
            recovery={"applied": False, "reason": payload.get("hard_fallback_reason")},
            details={"failure_reason": payload.get("hard_fallback_reason"), "output_path": str(output_path)},
            debug_artifact_path=str(debug_path),
        )
    append_generation_log(
        report_root=report_root,
        level="INFO" if payload["source"] == "llm" else "WARN",
        component="codebase_mapper",
        event="llm_codebase_interpretation_completed" if payload["source"] == "llm" else "llm_codebase_interpretation_recovered" if payload["source"] == "recovered_llm" else "llm_codebase_interpretation_hard_fallback",
        message="llm codebase interpretation finished" if payload["source"] == "llm" else "llm codebase interpretation recovered" if payload["source"] == "recovered_llm" else "llm codebase interpretation used hard fallback",
        details={
            "source": payload["source"],
            "recovery_reason": payload.get("recovery_reason"),
            "hard_fallback_reason": payload.get("hard_fallback_reason"),
            "debug_path": str(debug_path),
        },
    )

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_llm_codebase_interpretation_factory(
    *,
    provider: str,
    model: str,
    llm_builder: Callable[[str, str, float], Any] = make_chat_llm,
) -> Callable[[], Any]:
    return lambda: llm_builder(provider, model, 0)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _infer_reason(relative_path: str, path: Path, content: str) -> str | None:
    lower = relative_path.lower()
    if "views.py" in lower or "routes" in lower or "urls.py" in lower:
        return "backend route or handler candidate"
    if lower.endswith("main.py") or lower.endswith("app.py"):
        lowered = content.lower()
        if "fastapi" in lowered or "flask" in lowered:
            return "backend application entrypoint candidate"
    if path.suffix in {".js", ".jsx", ".ts", ".tsx", ".vue"} and "app" in path.stem.lower():
        return "frontend mount or integration candidate"
    return None


def _build_auth_candidate(relative_path: str, content: str) -> dict[str, object] | None:
    lower = relative_path.lower()
    if not lower.endswith(".py"):
        return None

    module = _parse_python_module(content)
    function_spans = _extract_function_spans(module)
    function_names = [item["name"] for item in function_spans]
    auth_markers = [
        marker
        for marker in ["session_token", "request.COOKIES", "request.cookies", "login", "logout", "me(", "SessionToken"]
        if marker in content
    ]
    if not auth_markers and not any(name in {"login", "logout", "me"} for name in function_names):
        return None

    return {
        "path": relative_path,
        "functions": function_names,
        "function_spans": function_spans,
        "auth_markers": auth_markers,
    }


def _build_urlconf_candidate(relative_path: str, content: str) -> dict[str, object] | None:
    lower = relative_path.lower()
    if not lower.endswith(".py"):
        return None

    module = _parse_python_module(content)
    has_urlpatterns = False
    urlpatterns_span: dict[str, int] | None = None
    include_targets: list[str] = []
    path_literals: list[str] = []

    if module is not None:
        for node in ast.walk(module):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "urlpatterns":
                        has_urlpatterns = True
                        urlpatterns_span = {
                            "start_line": int(node.lineno),
                            "end_line": int(getattr(node, "end_lineno", node.lineno)),
                        }
            if isinstance(node, ast.Call):
                call_name = _call_name(node.func)
                if call_name == "include" and node.args:
                    literal = _string_literal(node.args[0])
                    if literal is not None:
                        include_targets.append(literal)
                if call_name == "path" and node.args:
                    literal = _string_literal(node.args[0])
                    if literal is not None:
                        path_literals.append(literal)

    if not has_urlpatterns:
        has_urlpatterns = "urlpatterns" in content
    if not include_targets:
        include_targets = re.findall(r"include\([\"']([^\"']+)[\"']\)", content)
    if not path_literals:
        path_literals = re.findall(r"path\([\"']([^\"']+)[\"']", content)
    if not has_urlpatterns and not include_targets and not path_literals:
        return None

    return {
        "path": relative_path,
        "has_urlpatterns": has_urlpatterns,
        "urlpatterns_span": urlpatterns_span,
        "include_targets": include_targets,
        "path_literals": path_literals,
    }


def _build_frontend_component_candidate(relative_path: str, path: Path, content: str) -> dict[str, object] | None:
    if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
        return None

    component_names = re.findall(
        r"(?:function|const)\s+([A-Z][A-Za-z0-9_]*)",
        content,
    )
    markers = [
        marker
        for marker in ["<Chatbot", "<BrowserRouter", "<Routes", "react-router-dom", "<template", "export default App"]
        if marker in content
    ]
    if not markers and not ("app" in path.stem.lower() and component_names):
        return None

    return {
        "path": relative_path,
        "components": component_names,
        "markers": markers,
    }


def _build_api_client_candidate(relative_path: str, path: Path, content: str) -> dict[str, str] | None:
    if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
        return None
    if "fetch(" not in content and "axios" not in content:
        return None
    return {
        "path": relative_path,
        "reason": "frontend api client candidate",
    }


def _parse_python_module(content: str) -> ast.AST | None:
    try:
        return ast.parse(content)
    except SyntaxError:
        return None


def _extract_function_spans(module: ast.AST | None) -> list[dict[str, int | str]]:
    if module is None:
        return []

    spans: list[dict[str, int | str]] = []
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append(
                {
                    "name": node.name,
                    "start_line": int(node.lineno),
                    "end_line": int(getattr(node, "end_lineno", node.lineno)),
                }
            )
    spans.sort(key=lambda item: (int(item["start_line"]), str(item["name"])))
    return spans


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _string_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _llm_codebase_interpretation_system_prompt() -> str:
    return (
        "You interpret a codebase map for onboarding integration.\n"
        "Return only JSON with keys: structure_summary, framework_assessment, ranked_candidates.\n"
        "framework_assessment must be a JSON object with fields such as backend, frontend, and summary.\n"
        "Do not return framework_assessment as a plain string.\n"
        "ranked_candidates must be an array of objects with path and reason.\n"
        "Do not return ranked_candidates as strings.\n"
        "ranked_candidates must only contain paths from codebase_map.candidate_edit_targets.\n"
        "Prefer a small conservative ranking of the most relevant edit targets.\n"
    )


def _build_codebase_file_samples(
    source_root: str | Path,
    codebase_map: dict[str, Any],
    *,
    limit: int = 5,
    max_chars: int = 500,
) -> list[dict[str, str]]:
    root = Path(source_root)
    samples: list[dict[str, str]] = []
    for item in (codebase_map.get("candidate_edit_targets") or [])[:limit]:
        relative = str(item.get("path") or "")
        path = root / relative
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        samples.append({"path": relative, "content": content[:max_chars]})
    return samples


def _validate_ranked_candidates(
    *,
    llm_payload: CodebaseInterpretationPayload,
    codebase_map: dict[str, Any],
) -> None:
    valid_paths = {
        str(item.get("path") or "")
        for item in (codebase_map.get("candidate_edit_targets") or [])
    }
    if not llm_payload.ranked_candidates:
        raise ValueError("ranked_candidates must not be empty")
    if len(llm_payload.ranked_candidates) > 8:
        raise ValueError("ranked_candidates must remain conservative")
    for candidate in llm_payload.ranked_candidates:
        if candidate.path not in valid_paths:
            raise ValueError(f"invalid ranked candidate: {candidate.path}")


def _accept_ranked_candidates(
    *,
    llm_payload: CodebaseInterpretationPayload,
    codebase_map: dict[str, Any],
) -> tuple[CodebaseInterpretationPayload, list[dict[str, str]], str | None]:
    if not llm_payload.ranked_candidates:
        raise ValueError("ranked_candidates must not be empty")
    if len(llm_payload.ranked_candidates) > 8:
        raise ValueError("ranked_candidates must remain conservative")
    valid_paths = {
        str(item.get("path") or "")
        for item in (codebase_map.get("candidate_edit_targets") or [])
    }

    accepted_candidates: list[RankedCandidate] = []
    dropped_candidates: list[dict[str, str]] = []
    for candidate in llm_payload.ranked_candidates:
        if candidate.path in valid_paths:
            accepted_candidates.append(candidate)
            continue
        dropped_candidates.append(
            {
                "path": candidate.path,
                "reason": candidate.reason,
                "drop_reason": "invalid_ranked_candidate",
            }
        )

    if not dropped_candidates:
        return llm_payload, [], None
    if not accepted_candidates:
        raise ValueError(f"invalid ranked candidate: {dropped_candidates[0]['path']}")

    return (
        llm_payload.model_copy(update={"ranked_candidates": accepted_candidates}),
        dropped_candidates,
        "invalid_ranked_candidates_filtered",
    )


def _recover_codebase_interpretation_payload(
    payload: dict[str, Any],
    *,
    codebase_map: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str] | None:
    normalized = dict(payload)
    structure_summary = normalized.get("structure_summary")
    if isinstance(structure_summary, dict):
        normalized["structure_summary"] = json.dumps(structure_summary, ensure_ascii=False, sort_keys=True)
        return normalized, "structure_summary_object_to_string"
    framework_assessment = normalized.get("framework_assessment")
    if isinstance(framework_assessment, str):
        normalized["framework_assessment"] = {"summary": framework_assessment}
        return normalized, "framework_assessment_string_to_dict"
    ranked_candidates = normalized.get("ranked_candidates")
    if isinstance(ranked_candidates, list) and ranked_candidates and all(
        isinstance(item, str) for item in ranked_candidates
    ):
        candidate_reasons = {
            str(item.get("path") or ""): str(item.get("reason") or "")
            for item in (codebase_map or {}).get("candidate_edit_targets", [])
        }
        if all(candidate in candidate_reasons for candidate in ranked_candidates):
            normalized["ranked_candidates"] = [
                {
                    "path": candidate,
                    "reason": candidate_reasons[candidate],
                }
                for candidate in ranked_candidates
            ]
            return normalized, "ranked_candidate_paths_to_objects"
    return None
