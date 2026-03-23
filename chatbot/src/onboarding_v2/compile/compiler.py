from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.compile.registry import CompilerRegistry
from chatbot.src.onboarding_v2.compile.strategies.backend.django import compile_django_backend_bundle
from chatbot.src.onboarding_v2.compile.strategies.backend.fastapi import compile_fastapi_backend_bundle
from chatbot.src.onboarding_v2.compile.strategies.backend.flask import compile_flask_backend_bundle
from chatbot.src.onboarding_v2.compile.strategies.frontend.react_api import compile_react_api_bundle
from chatbot.src.onboarding_v2.compile.strategies.frontend.react_mount import compile_react_mount_bundle
from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.compile import EditProgram
from chatbot.src.onboarding_v2.models.planning import IntegrationPlan


def build_compiler_registry() -> CompilerRegistry:
    registry = CompilerRegistry()
    registry.register("django_project_urlconf_import_view", compile_django_backend_bundle)
    registry.register("flask_app_register_blueprint", compile_flask_backend_bundle)
    registry.register("fastapi_include_router", compile_fastapi_backend_bundle)
    registry.register("react_app_shell_outside_routes", compile_react_mount_bundle)
    registry.register("react_api_client_augment_existing", compile_react_api_bundle)
    return registry


def compile_plan(
    *,
    snapshot: AnalysisSnapshot,
    plan: IntegrationPlan,
    source_root: str | Path,
) -> EditProgram:
    del snapshot
    registry = build_compiler_registry()
    source_root = Path(source_root)
    backend_compiler = registry.resolve(plan.backend_wiring.strategy)
    mount_compiler = registry.resolve(plan.frontend_integration.mount_strategy)
    api_compiler = registry.resolve(plan.frontend_integration.api_strategy)

    backend_bundle = backend_compiler(source_root=source_root, plan=plan.backend_wiring)
    mount_bundle = mount_compiler(source_root=source_root, plan=plan.frontend_integration)
    api_bundle = api_compiler(source_root=source_root, plan=plan.frontend_integration)

    supporting_bundles = list(backend_bundle.supporting_files)
    return EditProgram(
        backend_wiring_bundles=[backend_bundle],
        frontend_mount_bundles=[mount_bundle],
        frontend_api_bundles=[api_bundle],
        supporting_artifact_bundles=supporting_bundles,
        execution_metadata={
            "backend_strategy": plan.backend_wiring.strategy,
            "mount_strategy": plan.frontend_integration.mount_strategy,
            "api_strategy": plan.frontend_integration.api_strategy,
        },
    )
