from __future__ import annotations

import re
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
    if existing_contract is None:
        export_symbol = "chat_auth_blueprint"
        generated_leaf_route = leaf_route
        import_line = f"from {handler_module} import {export_symbol}\n"
        register_line = (
            f'app.register_blueprint({export_symbol}, url_prefix="{blueprint_prefix}")\n'
        )
        updated = _inject_import_line(original=original, import_line=import_line)
        updated = _inject_blueprint_registration(updated=updated, register_line=register_line)
    else:
        export_symbol = existing_contract["symbol"]
        generated_leaf_route = _route_within_prefix(
            contract_path=plan.chat_auth_contract_path,
            prefix=existing_contract["prefix"],
        )
        updated = original

    supporting_file = SupportingArtifactBundle(
        bundle_id="supporting:chat-auth-blueprint",
        path=plan.generated_handler_path,
        reason="generated flask chat auth blueprint",
        content=_build_blueprint_content(
            generated_leaf_route,
            site_id=plan.site_id,
            export_symbol=export_symbol,
        ),
    )
    return BackendWiringBundle(
        bundle_id="backend:flask-wiring",
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
        supporting_files=[supporting_file],
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
