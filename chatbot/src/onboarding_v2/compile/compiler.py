from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.compile.registry import CompilerRegistry
from chatbot.src.onboarding_v2.compile.strategies.backend.django import compile_django_backend_bundle
from chatbot.src.onboarding_v2.compile.strategies.backend.fastapi import compile_fastapi_backend_bundle
from chatbot.src.onboarding_v2.compile.strategies.backend.flask import compile_flask_backend_bundle
from chatbot.src.onboarding_v2.compile.strategies.chatbot.generated_adapter import (
    compile_generated_chatbot_bridge_bundle,
)
from chatbot.src.onboarding_v2.compile.strategies.frontend.react_api import compile_react_api_bundle
from chatbot.src.onboarding_v2.compile.strategies.frontend.react_mount import compile_react_mount_bundle
from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot
from chatbot.src.onboarding_v2.models.compile import (
    ChatbotEditProgram,
    CompilePreflightSpec,
    EditProgram,
    HostEditProgram,
)
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
    chatbot_source_root: str | Path | None = None,
) -> EditProgram:
    del snapshot
    registry = build_compiler_registry()
    host_source_root = Path(source_root)
    chatbot_source_root = Path(chatbot_source_root) if chatbot_source_root is not None else Path(__file__).resolve().parents[3]
    backend_compiler = registry.resolve(plan.host_backend.strategy)
    mount_compiler = registry.resolve(plan.host_frontend.mount_strategy)
    api_compiler = registry.resolve(plan.host_frontend.api_strategy)

    backend_bundle = backend_compiler(source_root=host_source_root, plan=plan.host_backend)
    mount_bundle = mount_compiler(source_root=host_source_root, plan=plan.host_frontend)
    api_bundle = api_compiler(source_root=host_source_root, plan=plan.host_frontend)
    chatbot_bridge_bundle = compile_generated_chatbot_bridge_bundle(
        chatbot_source_root=chatbot_source_root,
        plan=plan.chatbot_bridge,
    )

    return EditProgram(
        host_program=HostEditProgram(
            backend_wiring_bundles=[backend_bundle],
            frontend_mount_bundles=[mount_bundle],
            frontend_api_bundles=[api_bundle],
            supporting_artifact_bundles=list(backend_bundle.supporting_files),
        ),
        chatbot_program=ChatbotEditProgram(
            bridge_bundles=[chatbot_bridge_bundle],
            supporting_artifact_bundles=list(chatbot_bridge_bundle.supporting_files),
            compile_preflight=CompilePreflightSpec(),
        ),
        execution_metadata={
            "host_backend_strategy": plan.host_backend.strategy,
            "host_mount_strategy": plan.host_frontend.mount_strategy,
            "host_api_strategy": plan.host_frontend.api_strategy,
            "chatbot_bridge_site_key": plan.chatbot_bridge.site_key,
        },
    )
