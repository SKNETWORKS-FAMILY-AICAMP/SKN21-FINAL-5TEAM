from __future__ import annotations

import re
import textwrap
from pathlib import Path, PurePosixPath

from chatbot.src.onboarding_v2.models.compile import (
    BackendWiringBundle,
    EditOperation,
    SupportingArtifactBundle,
)
from chatbot.src.onboarding_v2.models.planning import BackendWiringPlan

_APP_ASSIGNMENT_PATTERN = re.compile(r"^\s*app\s*=\s*Flask\(")
_REGISTER_BLUEPRINT_PATTERN = re.compile(r"^\s*app\.register_blueprint\(")
_RETURN_APP_PATTERN = re.compile(r"^\s*return\s+app\s*$")
_IMPORT_FROM_MODULE_PATTERN = re.compile(
    r"^\s*from\s+(?P<module>[A-Za-z0-9_\.]+)\s+import\s+(?P<symbols>.+?)\s*$"
)
_REGISTER_BLUEPRINT_CAPTURE_PATTERN = re.compile(
    r"^\s*app\.register_blueprint\(\s*(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*url_prefix\s*=\s*['\"](?P<prefix>[^'\"]+)['\"]\s*\)\s*$"
)
_SITE_ID_PATTERN = re.compile(r"(?m)^_SITE_ID\s*=\s*['\"][^'\"]*['\"]\s*$")
_BLUEPRINT_ASSIGNMENT_PATTERN = re.compile(
    r"(?m)^(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*Blueprint\([^\n]*\)\s*$"
)


def compile_flask_backend_bundle(
    *,
    source_root: str | Path,
    plan: BackendWiringPlan,
) -> BackendWiringBundle:
    root = Path(source_root)
    target = root / plan.route_target
    if not target.exists():
        raise ValueError(f"flask route target not found: {plan.route_target}")
    if not plan.generated_handler_path:
        raise ValueError("flask_missing_generated_handler_path: generated handler path is required")

    original = target.read_text(encoding="utf-8")
    blueprint_prefix, leaf_route = _decompose_contract_path(plan.chat_auth_contract_path)
    runtime_boundary = _runtime_boundary_root(plan.route_target)
    handler_module = _module_path_within_boundary(
        generated_handler_path=plan.generated_handler_path,
        runtime_boundary=runtime_boundary,
    )
    existing_contract = _detect_existing_chat_auth_contract(
        original=original,
        handler_module=handler_module,
    )
    operations = [
        EditOperation(
            path=plan.route_target,
            operation="replace_text",
            old=original,
            new="",
        )
    ]
    supporting_files: list[SupportingArtifactBundle] = []
    target_paths = [plan.route_target]
    if existing_contract is None:
        export_symbol = "chat_auth_blueprint"
        generated_leaf_route = leaf_route
        import_line = f"from {handler_module} import {export_symbol}\n"
        register_line = (
            f'app.register_blueprint({export_symbol}, url_prefix="{blueprint_prefix}")\n'
        )
        updated = _inject_import_line(original=original, import_line=import_line)
        updated = _inject_blueprint_registration(updated=updated, register_line=register_line)
        supporting_files = [
            SupportingArtifactBundle(
                bundle_id="supporting:chat-auth-blueprint",
                path=plan.generated_handler_path,
                reason="generated flask chat auth blueprint",
                content=_build_blueprint_content(
                    generated_leaf_route,
                    site_id=plan.site_id,
                    export_symbol=export_symbol,
                ),
            )
        ]
    else:
        export_symbol = existing_contract["symbol"]
        generated_leaf_route = _route_within_prefix(
            contract_path=plan.chat_auth_contract_path,
            prefix=existing_contract["prefix"],
        )
        updated = original
        handler_target = root / plan.generated_handler_path
        if handler_target.exists():
            handler_original = handler_target.read_text(encoding="utf-8")
            auth_transport = _infer_auth_transport_from_chat_auth_content(handler_original)
            handler_updated = _patch_existing_chat_auth_content(
                original=handler_original,
                site_id=plan.site_id,
                export_symbol=export_symbol,
                leaf_route=generated_leaf_route,
                auth_transport=auth_transport,
            )
            operations.append(
                EditOperation(
                    path=plan.generated_handler_path,
                    operation="replace_text",
                    old=handler_original,
                    new=handler_updated,
                )
            )
            target_paths.append(plan.generated_handler_path)
        else:
            supporting_files = [
                SupportingArtifactBundle(
                    bundle_id="supporting:chat-auth-blueprint",
                    path=plan.generated_handler_path,
                    reason="generated flask chat auth blueprint",
                    content=_build_blueprint_content(
                        generated_leaf_route,
                        site_id=plan.site_id,
                        export_symbol=export_symbol,
                    ),
                )
            ]

    operations[0] = operations[0].model_copy(update={"new": updated})
    return BackendWiringBundle(
        bundle_id="backend:flask-wiring",
        strategy=plan.strategy,
        target_paths=target_paths,
        operations=operations,
        supporting_files=supporting_files,
        handler_reference=f"{handler_module}.{export_symbol}",
    )


def _decompose_contract_path(contract_path: str) -> tuple[str, str]:
    normalized = str(contract_path or "").strip()
    if not normalized.startswith("/"):
        raise ValueError(
            f"flask_invalid_auth_contract_path: expected absolute path, got {contract_path!r}"
        )
    raw_parts = [part for part in normalized.split("/") if part]
    if len(raw_parts) < 2:
        raise ValueError(
            "flask_invalid_auth_contract_path: expected prefix and leaf route for blueprint wiring"
        )
    return "/" + "/".join(raw_parts[:-1]), "/" + raw_parts[-1]


def _runtime_boundary_root(route_target: str) -> str:
    parts = PurePosixPath(route_target).parts
    if parts and parts[0] == "backend":
        return "backend"
    return ""


def _module_path_within_boundary(*, generated_handler_path: str, runtime_boundary: str) -> str:
    handler = PurePosixPath(generated_handler_path)
    parts = handler.parts
    if runtime_boundary:
        if not parts or parts[0] != runtime_boundary:
            raise ValueError(
                "flask_generated_handler_outside_runtime_boundary: generated handler must stay within backend runtime boundary"
            )
        parts = parts[1:]
    module_parts = PurePosixPath(*parts).with_suffix("").parts if parts else ()
    if not module_parts:
        raise ValueError("flask_invalid_generated_handler_path: handler module path is empty")
    return ".".join(module_parts)


def _inject_import_line(*, original: str, import_line: str) -> str:
    if import_line in original:
        return original
    lines = original.splitlines(keepends=True)
    insert_at = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from ") or stripped.startswith("import "):
            insert_at = index + 1
            continue
        if stripped:
            break
    lines.insert(insert_at, import_line)
    if insert_at == 0 or (insert_at < len(lines) - 1 and lines[insert_at + 1].strip()):
        lines.insert(insert_at + 1, "\n")
    return "".join(lines)


def _inject_blueprint_registration(*, updated: str, register_line: str) -> str:
    if register_line in updated:
        return updated
    lines = updated.splitlines(keepends=True)
    factory_span = _find_create_app_span(lines)
    if factory_span is not None:
        return _insert_registration_for_factory(lines=lines, span=factory_span, register_line=register_line)
    return _insert_registration_for_module(lines=lines, register_line=register_line)


def _find_create_app_span(lines: list[str]) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        if line.startswith((" ", "\t")):
            continue
        if line.lstrip().startswith("def create_app("):
            return index, _block_end(lines, index)
    return None


def _block_end(lines: list[str], start_index: int) -> int:
    base_indent = _indent_level(lines[start_index])
    for index in range(start_index + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            continue
        if _indent_level(line) <= base_indent:
            return index
    return len(lines)


def _insert_registration_for_factory(
    *,
    lines: list[str],
    span: tuple[int, int],
    register_line: str,
) -> str:
    start, end = span
    function_lines = lines[start + 1 : end]
    if not any(_APP_ASSIGNMENT_PATTERN.match(line) for line in function_lines):
        raise ValueError(
            "flask_unsupported_wiring_pattern: create_app() is missing app = Flask(...)"
        )

    registration_indices = [
        index
        for index in range(start + 1, end)
        if _REGISTER_BLUEPRINT_PATTERN.match(lines[index])
    ]
    if registration_indices:
        insert_at = registration_indices[-1] + 1
    else:
        return_indices = [index for index in range(start + 1, end) if _RETURN_APP_PATTERN.match(lines[index])]
        if not return_indices:
            raise ValueError(
                "flask_unsupported_wiring_pattern: create_app() must return app for supported wiring"
            )
        insert_at = return_indices[0]

    lines.insert(insert_at, _indent_register_line(register_line))
    return "".join(lines)


def _insert_registration_for_module(*, lines: list[str], register_line: str) -> str:
    app_indices = [
        index
        for index, line in enumerate(lines)
        if _indent_level(line) == 0 and _APP_ASSIGNMENT_PATTERN.match(line)
    ]
    if not app_indices:
        raise ValueError(
            "flask_unsupported_wiring_pattern: expected module-level app = Flask(...) or supported create_app() factory"
        )
    registration_indices = [
        index
        for index, line in enumerate(lines)
        if _indent_level(line) == 0 and _REGISTER_BLUEPRINT_PATTERN.match(line)
    ]
    insert_at = registration_indices[-1] + 1 if registration_indices else app_indices[-1] + 1
    lines.insert(insert_at, register_line)
    return "".join(lines)


def _detect_existing_chat_auth_contract(*, original: str, handler_module: str) -> dict[str, str] | None:
    imported_symbols: set[str] = set()
    for line in original.splitlines():
        match = _IMPORT_FROM_MODULE_PATTERN.match(line)
        if match is None or match.group("module") != handler_module:
            continue
        for symbol in match.group("symbols").split(","):
            name = symbol.strip().split(" as ", 1)[0].strip()
            if name:
                imported_symbols.add(name)
    if not imported_symbols:
        return None
    for line in original.splitlines():
        match = _REGISTER_BLUEPRINT_CAPTURE_PATTERN.match(line)
        if match is None:
            continue
        symbol = match.group("symbol").strip()
        if symbol in imported_symbols:
            return {"symbol": symbol, "prefix": _normalize_prefix(match.group("prefix"))}
    return None


def _route_within_prefix(*, contract_path: str, prefix: str) -> str:
    normalized_path = _normalize_prefix(contract_path)
    normalized_prefix = _normalize_prefix(prefix)
    if normalized_prefix == "/":
        return normalized_path
    prefix_with_slash = f"{normalized_prefix}/"
    if normalized_path == normalized_prefix:
        return "/"
    if not normalized_path.startswith(prefix_with_slash):
        raise ValueError(
            "flask_existing_chat_auth_prefix_mismatch: existing blueprint prefix does not align with auth contract path"
        )
    return normalized_path[len(normalized_prefix) :]


def _normalize_prefix(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = normalized.rstrip("/")
    return normalized or "/"


def _indent_level(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _indent_register_line(register_line: str) -> str:
    return f"    {register_line}"


def _build_blueprint_content(leaf_route: str, *, site_id: str, export_symbol: str) -> str:
    return (
        "import json\n"
        "import os\n\n"
        "from flask import Blueprint, jsonify, request, session\n\n"
        f'{export_symbol} = Blueprint("chat_auth", __name__)\n\n'
        f'_SITE_ID = "{site_id}"\n\n'
        "def _runtime_capability_payload():\n"
        "    raw_corpora = os.environ.get(\"ONBOARDING_ENABLED_RETRIEVAL_CORPORA\", \"[]\")\n"
        "    raw_features = os.environ.get(\"ONBOARDING_WIDGET_FEATURES\", \"{}\")\n"
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
        "def _validation_payload():\n"
        "    email = os.environ.get(\"ONBOARDING_VALIDATION_EMAIL\", \"test1@example.com\")\n"
        "    name = os.environ.get(\"ONBOARDING_VALIDATION_NAME\", f\"{_SITE_ID} validation user\")\n"
        "    return {\n"
        '        "authenticated": True,\n'
        f'        "site_id": "{site_id}",\n'
        f'        "access_token": "validation-{site_id}",\n'
        '        "user": {"id": "validation-user", "email": email, "name": name},\n'
        "        **_runtime_capability_payload(),\n"
        "    }\n\n"
        "def _session_payload():\n"
        "    token = (\n"
        "        session.get(\"access_token\")\n"
        "        or session.get(\"token\")\n"
        "        or request.cookies.get(\"access_token\")\n"
        "        or request.headers.get(\"Authorization\", \"\").removeprefix(\"Bearer \").strip()\n"
        "    )\n"
        "    user_id = session.get(\"user_id\") or session.get(\"id\")\n"
        "    user_email = session.get(\"email\") or session.get(\"user_email\")\n"
        "    user_name = session.get(\"name\") or session.get(\"user_name\")\n"
        "    if not token or not user_id:\n"
        "        return None\n"
        "    return {\n"
        '        "authenticated": True,\n'
        f'        "site_id": "{site_id}",\n'
        '        "access_token": str(token),\n'
        '        "user": {"id": str(user_id), "email": user_email, "name": user_name},\n'
        "        **_runtime_capability_payload(),\n"
        "    }\n\n"
        f'@{export_symbol}.route("{leaf_route}", methods=["GET", "POST"])\n'
        "def chat_auth_token():\n"
        '    if os.environ.get("ONBOARDING_VALIDATION") == "1":\n'
        "        return jsonify(_validation_payload())\n"
        "    payload = _session_payload()\n"
        "    if payload is None:\n"
        f'        return jsonify({{"authenticated": False, "site_id": "{site_id}", "access_token": "", "user": None, **_runtime_capability_payload()}})\n'
        "    return jsonify(payload)\n"
    )


def _patch_existing_chat_auth_content(
    *,
    original: str,
    site_id: str,
    export_symbol: str,
    leaf_route: str,
    auth_transport: str,
) -> str:
    updated = _ensure_plain_imports(original, ["json", "os"])
    updated = _replace_or_append_site_id(updated, site_id=site_id, export_symbol=export_symbol)
    updated = _replace_or_append_top_level_function(
        updated,
        function_name="_runtime_capability_payload",
        content=_build_runtime_capability_payload_function(),
    )
    updated = _replace_or_append_top_level_function(
        updated,
        function_name="_validation_payload",
        content=_build_validation_payload_function(site_id=site_id, auth_transport=auth_transport),
    )
    updated = _replace_or_append_top_level_function(
        updated,
        function_name="_resolve_bridge_access_token",
        content=_build_resolve_bridge_access_token_function(),
    )
    updated = _replace_or_append_top_level_function(
        updated,
        function_name="_session_payload",
        content=_build_session_payload_function(site_id=site_id),
    )
    updated = _replace_or_append_top_level_function(
        updated,
        function_name="_authenticated_payload_from_user",
        content=_build_authenticated_payload_from_user_function(site_id=site_id),
    )
    updated = _replace_or_append_auth_route(
        updated,
        export_symbol=export_symbol,
        leaf_route=leaf_route,
        site_id=site_id,
    )
    return updated


def _infer_auth_transport_from_chat_auth_content(content: str) -> str:
    lowered = str(content or "").lower()
    if (
        "_parse_bearer_token" in content
        or ("authorization" in lowered and "bearer" in lowered)
    ) and "resolve_authenticated_user_id" in content:
        return "bearer_token"
    return "session_cookie"


def _ensure_plain_imports(original: str, module_names: list[str]) -> str:
    lines = original.splitlines(keepends=True)
    insertion_index = 0
    if lines and lines[0].startswith("from __future__ import "):
        insertion_index = 1
        while insertion_index < len(lines) and not lines[insertion_index].strip():
            insertion_index += 1
    for module_name in module_names:
        import_line = f"import {module_name}\n"
        if import_line in lines:
            continue
        lines.insert(insertion_index, import_line)
        insertion_index += 1
    if insertion_index > 0 and insertion_index < len(lines) and lines[insertion_index].strip():
        lines.insert(insertion_index, "\n")
    return "".join(lines)


def _replace_or_append_site_id(original: str, *, site_id: str, export_symbol: str) -> str:
    replacement = f'_SITE_ID = "{site_id}"'
    if _SITE_ID_PATTERN.search(original):
        return _SITE_ID_PATTERN.sub(replacement, original, count=1)
    blueprint_match = _BLUEPRINT_ASSIGNMENT_PATTERN.search(original)
    if blueprint_match is None or blueprint_match.group("symbol") != export_symbol:
        return f"{original.rstrip()}\n\n{replacement}\n"
    insert_at = blueprint_match.end()
    return f"{original[:insert_at]}\n\n{replacement}{original[insert_at:]}"


def _top_level_function_pattern(function_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?ms)^def {re.escape(function_name)}\([^\n]*\):\n(?:^[ \t].*\n|^\n)*(?=^(?:def |class |@|[^ \t\n])|\Z)"
    )


def _replace_or_append_top_level_function(
    original: str,
    *,
    function_name: str,
    content: str,
) -> str:
    pattern = _top_level_function_pattern(function_name)
    rendered = textwrap.dedent(content).strip() + "\n\n"
    match = pattern.search(original)
    if match is not None:
        return f"{original[:match.start()]}{rendered}{original[match.end():]}"
    anchor = _SITE_ID_PATTERN.search(original) or _BLUEPRINT_ASSIGNMENT_PATTERN.search(original)
    if anchor is not None:
        return f"{original[:anchor.end()]}\n\n{rendered}{original[anchor.end():]}"
    return f"{original.rstrip()}\n\n{rendered}"


def _replace_or_append_auth_route(
    original: str,
    *,
    export_symbol: str,
    leaf_route: str,
    site_id: str,
) -> str:
    existing_name = _find_existing_auth_route_name(original=original, export_symbol=export_symbol) or "chat_auth_token"
    rendered = _build_preserved_auth_route(
        export_symbol=export_symbol,
        function_name=existing_name,
        leaf_route=leaf_route,
        site_id=site_id,
    )
    pattern = re.compile(
        rf"(?ms)^@{re.escape(export_symbol)}\.route\([^\n]*auth-token[^\n]*\)\n(?:^@.*\n)*def {re.escape(existing_name)}\([^\n]*\):\n(?:^[ \t].*\n|^\n)*(?=^(?:def |class |@|[^ \t\n])|\Z)"
    )
    match = pattern.search(original)
    if match is not None:
        return f"{original[:match.start()]}{rendered}{original[match.end():]}"
    return f"{original.rstrip()}\n\n{rendered}"


def _find_existing_auth_route_name(*, original: str, export_symbol: str) -> str | None:
    match = re.search(
        rf"(?ms)^@{re.escape(export_symbol)}\.route\([^\n]*auth-token[^\n]*\)\n(?:^@.*\n)*def (?P<name>[A-Za-z_][A-Za-z0-9_]*)\(",
        original,
    )
    if match is None:
        return None
    return str(match.group("name")).strip() or None


def _build_runtime_capability_payload_function() -> str:
    return """
def _runtime_capability_payload():
    raw_corpora = os.environ.get("ONBOARDING_ENABLED_RETRIEVAL_CORPORA", "[]")
    raw_features = os.environ.get("ONBOARDING_WIDGET_FEATURES", "{}")
    try:
        corpora = json.loads(raw_corpora)
    except Exception:
        corpora = []
    try:
        features = json.loads(raw_features)
    except Exception:
        features = {}
    return {
        "capability_profile": os.environ.get("ONBOARDING_CAPABILITY_PROFILE", "order_cs_only"),
        "enabled_retrieval_corpora": corpora if isinstance(corpora, list) else [],
        "widget_features": features if isinstance(features, dict) else {},
    }
"""


def _build_validation_payload_function(*, site_id: str, auth_transport: str) -> str:
    if auth_transport == "bearer_token":
        return f"""
def _resolve_validation_user_context():
    email = os.environ.get("ONBOARDING_VALIDATION_EMAIL", "test1@example.com")
    name = os.environ.get("ONBOARDING_VALIDATION_NAME", f"{{_SITE_ID}} validation user")
    user_id_text = str(os.environ.get("ONBOARDING_VALIDATION_USER_ID", "") or "").strip()
    candidate_emails = []
    for candidate in [email, "test@example.com", "test1@example.com", "user1@example.com"]:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in candidate_emails:
            candidate_emails.append(normalized)
    user_lookup = None
    try:
        from models.user import find_user_by_email as user_lookup
    except Exception:
        user_lookup = None
    if not user_id_text and callable(user_lookup):
        user_record = None
        for candidate_email in candidate_emails:
            try:
                candidate_record = user_lookup(candidate_email)
            except Exception:
                candidate_record = None
            if isinstance(candidate_record, dict):
                user_record = candidate_record
                break
        if isinstance(user_record, dict):
            user_id_text = str(user_record.get("user_id") or user_record.get("id") or "").strip()
            email = str(user_record.get("email") or email)
            name = str(user_record.get("name") or name)
    return {{
        "id": user_id_text or "validation-user",
        "email": email,
        "name": name,
    }}


def _validation_payload():
    validation_user = _resolve_validation_user_context()
    access_token = str(validation_user.get("id") or "").strip()
    return {{
        "authenticated": True,
        "site_id": "{site_id}",
        "access_token": access_token,
        "user": validation_user,
        **_runtime_capability_payload(),
    }}
"""
    return f"""
def _validation_payload():
    email = os.environ.get("ONBOARDING_VALIDATION_EMAIL", "test1@example.com")
    name = os.environ.get("ONBOARDING_VALIDATION_NAME", f"{{_SITE_ID}} validation user")
    return {{
        "authenticated": True,
        "site_id": "{site_id}",
        "access_token": "validation-{site_id}",
        "user": {{"id": "validation-user", "email": email, "name": name}},
        **_runtime_capability_payload(),
    }}
"""


def _build_resolve_bridge_access_token_function() -> str:
    return """
def _resolve_bridge_access_token(user_id: str = "") -> str:
    raw_header = str(request.headers.get("Authorization") or "").strip()
    bearer_token = ""
    if raw_header:
        parts = raw_header.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            bearer_token = parts[1].strip()
    return str(
        bearer_token
        or session.get("access_token")
        or session.get("token")
        or request.cookies.get("access_token")
        or user_id
        or ""
    ).strip()
"""


def _build_session_payload_function(*, site_id: str) -> str:
    return f"""
def _session_payload():
    user_id = session.get("user_id") or session.get("id")
    if not user_id:
        return None
    user_id_text = str(user_id)
    token = _resolve_bridge_access_token(user_id_text)
    if not token:
        return None
    return {{
        "authenticated": True,
        "site_id": "{site_id}",
        "access_token": token,
        "user_id": user_id_text,
        "user": {{
            "id": user_id_text,
            "email": session.get("email") or session.get("user_email") or "",
            "name": session.get("name") or session.get("user_name") or "",
        }},
        **_runtime_capability_payload(),
    }}
"""


def _build_authenticated_payload_from_user_function(*, site_id: str) -> str:
    return f"""
def _authenticated_payload_from_user(user):
    user_dict = user if isinstance(user, dict) else {{}}
    user_id = str(user_dict.get("user_id") or user_dict.get("id") or "")
    token = _resolve_bridge_access_token(user_id)
    return {{
        "authenticated": True,
        "site_id": "{site_id}",
        "access_token": token,
        "user_id": user_id,
        "user": {{
            "id": user_id,
            "email": user_dict.get("email", ""),
            "name": user_dict.get("name", ""),
        }},
        **_runtime_capability_payload(),
    }}
"""


def _build_preserved_auth_route(
    *,
    export_symbol: str,
    function_name: str,
    leaf_route: str,
    site_id: str,
) -> str:
    return textwrap.dedent(
        f"""
        @{export_symbol}.route("{leaf_route}", methods=["GET", "POST"])
        def {function_name}():
            if os.environ.get("ONBOARDING_VALIDATION") == "1":
                return jsonify(_validation_payload()), 200

            user_getter = globals().get("get_authenticated_user")
            if callable(user_getter):
                user = user_getter()
                if user is None:
                    unauthenticated = globals().get("_unauthenticated_payload")
                    if callable(unauthenticated):
                        payload = unauthenticated()
                        if isinstance(payload, dict):
                            payload = {{
                                **payload,
                                "site_id": "{site_id}",
                                **_runtime_capability_payload(),
                            }}
                            return jsonify(payload), 401
                    return jsonify({{
                        "authenticated": False,
                        "site_id": "{site_id}",
                        "access_token": "",
                        "user": None,
                        **_runtime_capability_payload(),
                    }}), 401
                return jsonify(_authenticated_payload_from_user(user)), 200

            payload = _session_payload()
            if payload is None:
                return jsonify({{
                    "authenticated": False,
                    "site_id": "{site_id}",
                    "access_token": "",
                    "user": None,
                    **_runtime_capability_payload(),
                }}), 401
            return jsonify(payload), 200
        """
    ).strip() + "\n"
