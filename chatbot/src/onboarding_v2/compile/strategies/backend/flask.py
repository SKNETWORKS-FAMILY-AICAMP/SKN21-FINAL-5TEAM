from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.models.compile import BackendWiringBundle, EditOperation, SupportingArtifactBundle
from chatbot.src.onboarding_v2.models.planning import BackendWiringPlan


def compile_flask_backend_bundle(
    *,
    source_root: str | Path,
    plan: BackendWiringPlan,
) -> BackendWiringBundle:
    root = Path(source_root)
    target = root / plan.route_target
    original = target.read_text(encoding="utf-8")
    import_line = "from chat_auth import chat_auth_blueprint\n"
    register_line = "app.register_blueprint(chat_auth_blueprint)\n"
    updated = original
    if import_line not in updated:
        updated = f"{import_line}{updated}"
    if register_line not in updated:
        updated = f"{updated.rstrip()}\n\n{register_line}"
    supporting_files = []
    if plan.generated_handler_path:
        supporting_files.append(
            SupportingArtifactBundle(
                bundle_id="supporting:chat-auth-blueprint",
                path=plan.generated_handler_path,
                reason="generated flask chat auth blueprint",
                content=(
                    "from flask import Blueprint, jsonify\n\n"
                    'chat_auth_blueprint = Blueprint("chat_auth", __name__)\n\n'
                    '@chat_auth_blueprint.route("/api/chat/auth-token", methods=["GET", "POST"])\n'
                    "def chat_auth_token():\n"
                    '    return jsonify({"authenticated": False, "access_token": None})\n'
                ),
            )
        )
    return BackendWiringBundle(
        bundle_id="backend:flask-wiring",
        strategy=plan.strategy,
        target_paths=[plan.route_target],
        operations=[EditOperation(path=plan.route_target, operation="replace_text", old=original, new=updated)],
        supporting_files=supporting_files,
        handler_reference="chat_auth.chat_auth_blueprint",
    )
