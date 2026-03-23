from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding.onboarding_ignore import OnboardingIgnoreMatcher
from chatbot.src.onboarding.site_analyzer import analyze_site
from chatbot.src.onboarding_v2.models.analysis import (
    AmbiguitySnapshot,
    AnalysisProvenance,
    AnalysisSnapshot,
    BackendSeams,
    DomainIntegration,
    FrontendSeams,
    RepoProfile,
)
from chatbot.src.onboarding_v2.models.common import PathCandidate


def build_analysis_snapshot(*, site: str, source_root: str | Path) -> AnalysisSnapshot:
    root = Path(source_root)
    analysis = analyze_site(root)
    integration_contract = analysis.get("integration_contract") or {}
    backend_contract = integration_contract.get("backend") or {}
    frontend_contract = integration_contract.get("frontend") or {}
    backend_route_targets = _scan_backend_route_targets(root=root, analysis=analysis)
    tool_registry_targets = _scan_tool_registry_targets(root=root)
    user_resolver_candidates = _scan_user_resolver_candidates(root=root)
    app_shell_scan_candidates = _scan_frontend_app_shell_candidates(root=root)
    router_boundary_scan_candidates = _scan_frontend_router_boundaries(root=root)
    api_client_candidates = _scan_frontend_api_client_candidates(root=root)
    widget_mount_candidates = _scan_frontend_mount_candidates(root=root, analysis=analysis)
    order_bridge_targets = _scan_order_bridge_targets(root=root, analysis=analysis)

    app_shell_candidates = []
    app_shell_path = str(frontend_contract.get("app_shell_path") or "").strip()
    if app_shell_path:
        app_shell_candidates.append(
            PathCandidate(
                path=app_shell_path,
                reason="frontend app shell candidate",
                source="heuristic",
                evidence_refs=["site_analyzer.frontend.app_shell_path"],
            )
        )
    app_shell_candidates.extend(
        _to_candidates(app_shell_scan_candidates, default_reason="frontend app shell candidate")
    )

    router_boundary = str(frontend_contract.get("router_boundary_path") or "").strip()
    router_boundary_candidates = []
    if router_boundary:
        router_boundary_candidates.append(
            PathCandidate(
                path=router_boundary,
                reason="frontend router boundary candidate",
                source="heuristic",
                evidence_refs=["site_analyzer.frontend.router_boundary_path"],
            )
        )
    router_boundary_candidates.extend(
        _to_candidates(
            router_boundary_scan_candidates,
            default_reason="frontend router boundary candidate",
        )
    )

    open_questions: list[str] = []
    if len({candidate.path for candidate in app_shell_candidates if candidate.path}) > 1:
        open_questions.append("multiple frontend app shell candidates detected")
    if len({candidate.path for candidate in router_boundary_candidates if candidate.path}) > 1:
        open_questions.append("multiple router boundary candidates detected")

    return AnalysisSnapshot(
        repo_profile=RepoProfile(
            site=site,
            source_root=str(root),
            backend_framework=str(analysis.get("framework", {}).get("backend") or "unknown"),
            frontend_framework=str(analysis.get("framework", {}).get("frontend") or "unknown"),
            auth_style=str(analysis.get("auth", {}).get("auth_style") or "unknown"),
            backend_entrypoints=list(analysis.get("backend_entrypoints") or []),
            frontend_entrypoints=list(analysis.get("frontend_mount_targets") or []),
        ),
        backend_seams=BackendSeams(
            auth_source_candidates=_to_candidates(
                backend_contract.get("auth_source_paths") or [],
                default_reason="backend auth source candidate",
            ),
            user_resolver_candidates=_to_candidates(
                user_resolver_candidates,
                default_reason="backend session resolver candidate",
            ),
            route_registration_points=_to_candidates(
                backend_route_targets,
                default_reason="backend route registration candidate",
            ),
            tool_registry_candidates=_to_candidates(
                tool_registry_targets,
                default_reason="backend tool registry candidate",
            ),
        ),
        frontend_seams=FrontendSeams(
            app_shell_candidates=_dedupe_candidates(app_shell_candidates),
            router_boundary_candidates=_dedupe_candidates(router_boundary_candidates),
            api_client_candidates=_to_candidates(
                api_client_candidates or frontend_contract.get("api_client_paths") or [],
                default_reason="frontend api client candidate",
            ),
            widget_mount_candidates=_to_candidates(
                widget_mount_candidates or frontend_contract.get("widget_mount_points") or [],
                default_reason="frontend widget mount candidate",
            ),
            auth_store_candidates=_infer_auth_store_candidates(root=root),
        ),
        domain_integration=DomainIntegration(
            product_api_base_paths=list(analysis.get("product_api") or []),
            order_api_base_paths=list(analysis.get("order_api") or []),
            order_bridge_targets=_to_candidates(
                order_bridge_targets,
                default_reason="order bridge target candidate",
            ),
        ),
        ambiguity=AmbiguitySnapshot(
            open_questions=open_questions,
            competing_candidates=[],
            rejected_candidates=[],
        ),
        provenance=AnalysisProvenance(
            discovered_by=["heuristic", "legacy_adapter"],
            llm_augmented=False,
            soft_dropped_candidates=[],
            evidence_refs=["legacy.site_analyzer", "legacy.codebase_mapper"],
            confidence_notes=["analysis snapshot derived from legacy heuristic analyzers"],
        ),
    )


def _to_candidates(items: list[dict] | list[str], *, default_reason: str) -> list[PathCandidate]:
    results: list[PathCandidate] = []
    for item in items:
        if isinstance(item, str):
            path = item.strip()
            if not path:
                continue
            results.append(PathCandidate(path=path, reason=default_reason))
            continue
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        results.append(
            PathCandidate(
                path=path,
                reason=str(item.get("reason") or default_reason),
                source=str(item.get("source") or "heuristic"),
            )
        )
    return _dedupe_candidates(results)


def _dedupe_candidates(items: list[PathCandidate]) -> list[PathCandidate]:
    seen: set[str] = set()
    deduped: list[PathCandidate] = []
    for item in items:
        if not item.path or item.path in seen:
            continue
        deduped.append(item)
        seen.add(item.path)
    return deduped


def _infer_auth_store_candidates(*, root: Path) -> list[PathCandidate]:
    candidates: list[PathCandidate] = []
    for path in sorted(root.rglob("*Auth*.js*")):
        if not path.is_file():
            continue
        candidates.append(
            PathCandidate(
                path=path.relative_to(root).as_posix(),
                reason="frontend auth store candidate",
            )
        )
    for path in sorted(root.rglob("*Auth*.tsx")):
        if not path.is_file():
            continue
        candidates.append(
            PathCandidate(
                path=path.relative_to(root).as_posix(),
                reason="frontend auth store candidate",
            )
        )
    return _dedupe_candidates(candidates)


def _iter_text_files(root: Path):
    ignore_matcher = OnboardingIgnoreMatcher(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not ignore_matcher.includes(path):
            continue
        if path.suffix not in {".py", ".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        yield path, text


def _scan_backend_route_targets(*, root: Path, analysis: dict) -> list[dict[str, str]]:
    explicit = list(analysis.get("backend_route_targets") or [])
    if explicit:
        return [{"path": item, "reason": "backend route registration candidate"} for item in explicit]
    targets: list[dict[str, str]] = []
    for path, text in _iter_text_files(root):
        if path.suffix != ".py":
            continue
        if "urlpatterns" in text or "include_router(" in text or "register_blueprint(" in text:
            targets.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "reason": "backend route registration candidate",
                }
            )
    return targets


def _scan_tool_registry_targets(*, root: Path) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for path, _text in _iter_text_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.endswith("tool_registry.py"):
            targets.append({"path": relative, "reason": "backend tool registry candidate"})
    return targets


def _scan_user_resolver_candidates(*, root: Path) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for path, text in _iter_text_files(root):
        if path.suffix != ".py":
            continue
        if "_find_active_session" in text or "get_authenticated_user" in text or "require_authenticated_user" in text:
            targets.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "reason": "backend session resolver candidate",
                }
            )
    return targets


def _scan_frontend_app_shell_candidates(*, root: Path) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for path, text in _iter_text_files(root):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        relative = path.relative_to(root).as_posix()
        lowered = relative.lower()
        if lowered.endswith(("app.js", "app.jsx", "app.ts", "app.tsx", "layout.js", "layout.jsx", "layout.tsx")):
            targets.append({"path": relative, "reason": "frontend app shell candidate"})
            continue
        if "<Routes" in text or "function App" in text or "export default function App" in text:
            targets.append({"path": relative, "reason": "frontend app shell candidate"})
    return targets


def _scan_frontend_router_boundaries(*, root: Path) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for path, text in _iter_text_files(root):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        if "<Routes" not in text and "BrowserRouter" not in text and "RouterProvider" not in text:
            continue
        targets.append(
            {
                "path": path.relative_to(root).as_posix(),
                "reason": "frontend router boundary candidate",
            }
        )
    return targets


def _scan_frontend_api_client_candidates(*, root: Path) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for path, text in _iter_text_files(root):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        relative = path.relative_to(root).as_posix()
        if "/api/" in relative.replace("\\", "/") or "fetch(" in text or "axios" in text:
            targets.append({"path": relative, "reason": "frontend api client candidate"})
    return targets


def _scan_frontend_mount_candidates(*, root: Path, analysis: dict) -> list[dict[str, str]]:
    explicit = list(analysis.get("frontend_mount_targets") or [])
    if explicit:
        return [{"path": item, "reason": "frontend widget mount candidate"} for item in explicit]
    targets: list[dict[str, str]] = []
    for path, text in _iter_text_files(root):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        if "function App" in text or "<Routes" in text or "<router-view" in text:
            targets.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "reason": "frontend widget mount candidate",
                }
            )
    return targets


def _scan_order_bridge_targets(*, root: Path, analysis: dict) -> list[dict[str, str]]:
    explicit = list(analysis.get("order_bridge_targets") or [])
    if explicit:
        return [{"path": item, "reason": "order bridge target candidate"} for item in explicit]
    targets: list[dict[str, str]] = []
    for path, _text in _iter_text_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("backend/") and "order" in relative.lower():
            targets.append({"path": relative, "reason": "order bridge target candidate"})
    return targets
