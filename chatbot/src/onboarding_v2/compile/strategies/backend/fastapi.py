from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.models.compile import BackendWiringBundle, EditOperation, SupportingArtifactBundle
from chatbot.src.onboarding_v2.models.planning import BackendWiringPlan


def compile_fastapi_backend_bundle(
    *,
    source_root: str | Path,
    plan: BackendWiringPlan,
) -> BackendWiringBundle:
    root = Path(source_root)
    target = root / plan.route_target
    original = target.read_text(encoding="utf-8")
    import_line = "from chat_auth import router as chat_auth_router\n"
    include_line = "app.include_router(chat_auth_router)\n"
    updated = original
    if import_line not in updated:
        updated = f"{import_line}{updated}"
    if include_line not in updated:
        updated = f"{updated.rstrip()}\n\n{include_line}"
    supporting_files = []
    if plan.generated_handler_path:
        supporting_files.append(
            SupportingArtifactBundle(
                bundle_id="supporting:chat-auth-router",
                path=plan.generated_handler_path,
                reason="generated fastapi chat auth router",
                content=(
                    "from fastapi import APIRouter\n\n"
                    "router = APIRouter()\n\n"
                    '@router.api_route("/api/chat/auth-token", methods=["GET", "POST"])\n'
                    "def chat_auth_token():\n"
                    '    return {"authenticated": False, "access_token": None}\n'
                ),
            )
        )
    return BackendWiringBundle(
        bundle_id="backend:fastapi-wiring",
        strategy=plan.strategy,
        target_paths=[plan.route_target],
        operations=[EditOperation(path=plan.route_target, operation="replace_text", old=original, new=updated)],
        supporting_files=supporting_files,
        handler_reference="chat_auth.chat_auth_router",
    )
