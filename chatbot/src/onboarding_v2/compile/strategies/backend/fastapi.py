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
                    "import json\n"
                    "import os\n\n"
                    "from fastapi import APIRouter, Request\n\n"
                    "router = APIRouter()\n\n"
                    f'_SITE_ID = "{plan.site_id}"\n\n'
                    "def _runtime_capability_payload():\n"
                    '    raw_corpora = os.environ.get("ONBOARDING_ENABLED_RETRIEVAL_CORPORA", "[]")\n'
                    '    raw_features = os.environ.get("ONBOARDING_WIDGET_FEATURES", "{}")\n'
                    "    try:\n"
                    "        corpora = json.loads(raw_corpora)\n"
                    "    except Exception:\n"
                    "        corpora = []\n"
                    "    try:\n"
                    "        features = json.loads(raw_features)\n"
                    "    except Exception:\n"
                    "        features = {}\n"
                    "    return {\n"
                    '        "capability_profile": os.environ.get("ONBOARDING_CAPABILITY_PROFILE", "order_cs_only"),\n'
                    '        "enabled_retrieval_corpora": corpora if isinstance(corpora, list) else [],\n'
                    '        "widget_features": features if isinstance(features, dict) else {},\n'
                    "    }\n\n"
                    '@router.api_route("/api/chat/auth-token", methods=["GET", "POST"])\n'
                    "def chat_auth_token(request: Request):\n"
                    '    if os.environ.get("ONBOARDING_VALIDATION") == "1":\n'
                    '        email = os.environ.get("ONBOARDING_VALIDATION_EMAIL", "test1@example.com")\n'
                    '        name = os.environ.get("ONBOARDING_VALIDATION_NAME", f"{_SITE_ID} validation user")\n'
                    "        return {\n"
                    '            "authenticated": True,\n'
                    '            "site_id": _SITE_ID,\n'
                    '            "access_token": f"validation-{_SITE_ID}",\n'
                    '            "user": {"id": "validation-user", "email": email, "name": name},\n'
                    "            **_runtime_capability_payload(),\n"
                    "        }\n"
                    '    token = request.cookies.get("access_token") or ""\n'
                    '    auth_header = request.headers.get("authorization", "")\n'
                    '    if not token and auth_header.lower().startswith("bearer "):\n'
                    '        token = auth_header[7:].strip()\n'
                    '    if not token:\n'
                    '        return {"authenticated": False, "site_id": _SITE_ID, "access_token": "", "user": None, **_runtime_capability_payload()}\n'
                    "    return {\n"
                    '        "authenticated": True,\n'
                    '        "site_id": _SITE_ID,\n'
                    '        "access_token": token,\n'
                    '        "user": {"id": request.cookies.get("user_id") or "session-user"},\n'
                    "        **_runtime_capability_payload(),\n"
                    "    }\n"
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
