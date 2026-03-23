from __future__ import annotations

from importlib import import_module


_LAZY_EXPORTS = {
    "AgentMessage": (".agent_contracts", "AgentMessage"),
    "ApprovalType": (".agent_contracts", "ApprovalType"),
    "RunEvent": (".agent_contracts", "RunEvent"),
    "RunState": (".agent_contracts", "RunState"),
    "ApprovalStore": (".approval_store", "ApprovalStore"),
    "export_runtime_patch": (".exporter", "export_runtime_patch"),
    "OverlayManifest": (".manifest", "OverlayManifest"),
    "OverlayManifestError": (".manifest", "OverlayManifestError"),
    "generate_overlay_scaffold": (".overlay_generator", "generate_overlay_scaffold"),
    "run_onboarding_generation": (".orchestrator", "run_onboarding_generation"),
    "generate_run_bundle": (".run_generator", "generate_run_bundle"),
    "SmokeTestPlan": (".smoke_contract", "SmokeTestPlan"),
    "load_smoke_plan": (".smoke_runner", "load_smoke_plan"),
    "run_smoke_tests": (".smoke_runner", "run_smoke_tests"),
    "prepare_runtime_workspace": (".runtime_runner", "prepare_runtime_workspace"),
    "analyze_site": (".site_analyzer", "analyze_site"),
    "generate_chat_auth_template": (".template_generator", "generate_chat_auth_template"),
    "generate_frontend_mount_patch": (".template_generator", "generate_frontend_mount_patch"),
    "generate_order_adapter_template": (".template_generator", "generate_order_adapter_template"),
    "generate_product_adapter_template": (".template_generator", "generate_product_adapter_template"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
