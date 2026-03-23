from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.models.compile import BackendWiringBundle, EditOperation, SupportingArtifactBundle
from chatbot.src.onboarding_v2.models.planning import BackendWiringPlan


def compile_django_backend_bundle(
    *,
    source_root: str | Path,
    plan: BackendWiringPlan,
) -> BackendWiringBundle:
    root = Path(source_root)
    route_path = root / plan.route_target
    if not route_path.exists():
        raise ValueError(f"django route target not found: {plan.route_target}")
    original = route_path.read_text(encoding="utf-8")
    updated = _ensure_django_route_wiring(original)
    supporting_files = []
    if plan.generated_handler_path:
        supporting_files.append(
            SupportingArtifactBundle(
                bundle_id="supporting:chat-auth-module",
                path=plan.generated_handler_path,
                reason="generated django chat auth bridge",
                content=_build_django_chat_auth_module(plan.auth_handler_source),
            )
        )
    return BackendWiringBundle(
        bundle_id="backend:django-wiring",
        strategy=plan.strategy,
        target_paths=[plan.route_target],
        operations=[
            EditOperation(
                path=plan.route_target,
                operation="replace_text",
                old=original,
                new=updated,
            )
        ],
        supporting_files=supporting_files,
        handler_reference="chat_auth.chat_auth_token",
    )


def _ensure_django_route_wiring(content: str) -> str:
    lines = content.splitlines(keepends=True)
    import_line = "from chat_auth import chat_auth_token\n"
    route_line = '    path("api/chat/auth-token", chat_auth_token),\n'
    if import_line not in lines:
        insert_index = 0
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("from ") or stripped.startswith("import "):
                insert_index = index + 1
                continue
            if stripped == "":
                if insert_index:
                    insert_index = index + 1
                continue
            break
        lines[insert_index:insert_index] = [import_line]
    if route_line not in lines:
        urlpatterns_index = next((index for index, line in enumerate(lines) if "urlpatterns" in line), None)
        if urlpatterns_index is None:
            if lines and lines[-1].strip():
                lines.append("\n")
            lines.extend(["urlpatterns = [\n", route_line, "]\n"])
        else:
            closing_index = _find_list_closing_index(lines, start_index=urlpatterns_index)
            if closing_index is None:
                lines.append(route_line)
            else:
                lines.insert(closing_index, route_line)
    return "".join(lines)


def _find_list_closing_index(lines: list[str], *, start_index: int) -> int | None:
    depth = 0
    seen_open = False
    for index in range(start_index, len(lines)):
        line = lines[index]
        if "[" in line:
            depth += line.count("[")
            seen_open = True
        if "]" in line:
            depth -= line.count("]")
            if seen_open and depth <= 0:
                return index
    return None


def _build_django_chat_auth_module(auth_source: str) -> str:
    source_module = auth_source.removesuffix(".py").replace("/", ".")
    if source_module.startswith("backend."):
        source_module = source_module.removeprefix("backend.")
    return (
        "from __future__ import annotations\n\n"
        "from django.http import JsonResponse\n"
        "from django.views.decorators.csrf import csrf_exempt\n\n"
        f"from {source_module} import _build_user_payload, _find_active_session\n\n\n"
        "@csrf_exempt\n"
        "def chat_auth_token(request):\n"
        '    """Generated onboarding bridge endpoint."""\n'
        "    session = _find_active_session(request)\n"
        "    if not session:\n"
        '        return JsonResponse({"authenticated": False, "access_token": None}, status=200)\n'
        '    access_token = f"session-{session.user_id}-{session.token[:12]}"\n'
        "    return JsonResponse(\n"
        "        {\n"
        '            "authenticated": True,\n'
        '            "access_token": access_token,\n'
        '            "user": _build_user_payload(session.user),\n'
        "        },\n"
        "        status=200,\n"
        "    )\n"
    )
