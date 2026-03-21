from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .failure_classifier import build_failure_signature
from .smoke_contract import SmokeRecoveryPayload, SmokeTestPlan, SmokeTestStep

TEMPLATE_PATTERN = re.compile(r"{{\s*([^}\s]+)\s*}}")
EXPORT_TOKEN_PATTERN = re.compile(r"([^\.\[\]]+)|\[(\d+|'[^']+'|\"[^\"]+\")\]")


def _render_template(value: str | None, context: dict[str, object]) -> str | None:
    if not isinstance(value, str):
        return value

    def replace(match: re.Match) -> str:
        key = match.group(1)
        return str(context.get(key) or "")

    return TEMPLATE_PATTERN.sub(replace, value)


def _render_template_value(value: Any, context: dict[str, object]) -> Any:
    if isinstance(value, str):
        return _render_template(value, context)
    if isinstance(value, dict):
        return {key: _render_template_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_template_value(item, context) for item in value]
    return value


def _read_export_path(source: Any, expression: str) -> Any:
    current = source
    remainder = expression
    for prefix in ("json", "headers"):
        if expression == prefix:
            remainder = ""
            break
        if expression.startswith(f"{prefix}."):
            remainder = expression[len(prefix) + 1 :]
            break
        if expression.startswith(f"{prefix}["):
            remainder = expression[len(prefix) :]
            break
    for match in EXPORT_TOKEN_PATTERN.finditer(remainder):
        token = match.group(1)
        bracket = match.group(2)
        if token is not None:
            if not isinstance(current, dict) or token not in current:
                return None
            current = current[token]
            continue
        if bracket is None:
            continue
        cleaned = bracket.strip("'\"")
        if cleaned.isdigit():
            index = int(cleaned)
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
            continue
        if not isinstance(current, dict):
            return None
        matched_key = next((key for key in current if key.lower() == cleaned.lower()), None)
        if matched_key is None:
            return None
        current = current[matched_key]
    return current


def _resolve_export(
    value: str,
    *,
    status: int | None,
    response_headers: dict[str, str],
    json_payload: Any,
) -> str | None:
    if value.startswith("json"):
        resolved = _read_export_path(json_payload or {}, value)
        return None if resolved is None else str(resolved)
    if value.startswith("headers"):
        resolved = _read_export_path(response_headers or {}, value)
        return None if resolved is None else str(resolved)
    if value.startswith("cookies."):
        cookie_name = value.split(".", 1)[1]
        cookie_header = next(
            (header_value for header_name, header_value in response_headers.items() if header_name.lower() == "set-cookie"),
            "",
        )
        for cookie_pair in cookie_header.split(";"):
            if "=" in cookie_pair:
                name, val = cookie_pair.split("=", 1)
                if name.strip() == cookie_name:
                    return val.strip()
        return None
    if value == "status" and status is not None:
        return str(status)
    return value


def _is_http_probe(step: SmokeTestStep) -> bool:
    return getattr(step, "kind", None) == "http" or bool(getattr(step, "url", None))


def _run_http_probe(
    *,
    step: SmokeTestStep,
    workspace: Path,
    root: Path,
    context: dict[str, object],
) -> dict[str, Any]:
    missing_credentials = _missing_credential_keys(step=step, context=context)
    if missing_credentials:
        return {
            "step": step.id,
            "step_id": step.id,
            "strategy": step.strategy,
            "uses": list(step.uses or []),
            "required": step.required,
            "category": step.category,
            "timed_out": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "Missing onboarding credentials for auth probe: " + ", ".join(missing_credentials),
            "request": {"method": (getattr(step, "method", None) or "GET").upper(), "url": getattr(step, "url", ""), "headers": {}, "body": None},
            "response": {"status": None, "headers": {}, "body": ""},
            "exports": {},
        }
    method = (getattr(step, "method", None) or "GET").upper()
    url = _render_template(getattr(step, "url", ""), context) or ""
    headers = {
        key: str(_render_template(value, context) or "")
        for key, value in (getattr(step, "headers", {}) or {}).items()
        if value is not None
    }
    body = _render_template_value(getattr(step, "body", None), context)
    if isinstance(body, dict):
        request_body = json.dumps(body)
        body = request_body.encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif isinstance(body, str):
        request_body = body
        body = body.encode("utf-8")
    else:
        request_body = None

    query = getattr(step, "query", None)
    if isinstance(query, dict):
        rendered = {
            key: _render_template(str(value), context)
            for key, value in query.items()
            if value is not None
        }
        url = f"{url}?{urllib.parse.urlencode(rendered)}" if rendered else url

    request = urllib.request.Request(url, data=body, method=method)
    for key, value in headers.items():
        request.add_header(key, value)

    timeout = getattr(step, "timeout_seconds", 5)
    timed_out = False
    status = None
    response_body = ""
    response_headers = {}
    json_payload = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            response_body = response.read().decode("utf-8", errors="ignore")
            response_headers = dict(response.getheaders())
            try:
                json_payload = json.loads(response_body)
            except json.JSONDecodeError:
                json_payload = None
    except urllib.error.HTTPError as exc:
        status = exc.code
        response_body = exc.read().decode("utf-8", errors="ignore")
        response_headers = dict(exc.headers)
    except urllib.error.URLError as exc:
        return {
            "step": step.id,
            "step_id": step.id,
            "strategy": step.strategy,
            "uses": list(step.uses or []),
            "required": step.required,
            "category": step.category,
            "timed_out": isinstance(exc.reason, TimeoutError),
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
            "request": {"method": method, "url": url, "headers": headers, "body": request_body},
            "response": {"status": None, "headers": {}, "body": ""},
            "exports": {},
        }
    except Exception as exc:
        return {
            "step": step.id,
            "step_id": step.id,
            "strategy": step.strategy,
            "uses": list(step.uses or []),
            "required": step.required,
            "category": step.category,
            "timed_out": isinstance(exc, TimeoutError),
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
            "request": {"method": method, "url": url, "headers": headers, "body": request_body},
            "response": {"status": None, "headers": {}, "body": ""},
            "exports": {},
        }

    expects = step.expects
    status_expected = expects.status
    json_keys = expects.json_keys
    status_ok = status == status_expected or (isinstance(status_expected, list) and status in status_expected)
    json_ok = True
    for key in json_keys:
        if not (isinstance(json_payload, dict) and key in json_payload):
            json_ok = False
            break
    if json_ok and expects.json_path_equals:
        for path, expected in expects.json_path_equals.items():
            actual = _read_export_path(json_payload, f"json.{path}")
            if actual != expected:
                json_ok = False
                break
    if json_ok and expects.json_type == "list" and not isinstance(json_payload, list):
        json_ok = False
    if json_ok and expects.json_array_min_length is not None:
        array_target = _resolve_expected_array(json_payload, expects.json_array_key)
        if not isinstance(array_target, list) or len(array_target) < expects.json_array_min_length:
            json_ok = False

    exports: dict[str, object] = {}
    for name, expression in (getattr(step, "exports", {}) or {}).items():
        value = _resolve_export(
            str(expression),
            status=status,
            response_headers=response_headers,
            json_payload=json_payload,
        )
        if value is not None:
            exports[name] = value

    result = {
        "step": step.id,
        "step_id": step.id,
        "strategy": step.strategy,
        "uses": list(step.uses or []),
        "required": step.required,
        "category": step.category,
        "timed_out": timed_out,
        "returncode": 0 if status_ok and json_ok else 1,
        "stdout": response_body,
        "stderr": "" if status_ok and json_ok else f"status={status} json_ok={json_ok}",
        "request": {"method": method, "url": url, "headers": headers, "body": request_body},
        "response": {"status": status, "headers": response_headers, "body": response_body},
        "exports": exports,
    }
    return result


def _resolve_expected_array(json_payload: Any, array_key: str | None) -> Any:
    if array_key:
        if not isinstance(json_payload, dict):
            return None
        return json_payload.get(array_key)
    return json_payload



def load_smoke_plan(run_root: str | Path) -> SmokeTestPlan:
    root = Path(run_root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    tests = manifest.get("tests") or {}
    raw_steps = list(tests.get("smoke") or [])
    return SmokeTestPlan.model_validate({"steps": raw_steps})


def run_smoke_tests(
    *,
    run_root: str | Path,
    runtime_workspace: str | Path,
    plan: SmokeTestPlan,
    recovery_payload: SmokeRecoveryPayload | dict[str, Any] | None = None,
) -> list[dict]:
    root = Path(run_root)
    workspace = Path(runtime_workspace)
    results: list[dict] = []
    normalized_recovery = _normalize_recovery_payload(recovery_payload)

    context: dict[str, object] = _load_probe_context(root)
    for step in plan.steps:
        effective_step, recovery_metadata = _apply_recovery_to_step(
            step=step,
            recovery_payload=normalized_recovery,
        )
        if _is_http_probe(effective_step):
            result = _run_http_probe(
                step=effective_step,
                workspace=workspace,
                root=root,
                context=context,
            )
        else:
            result = _run_script_step(step=effective_step, workspace=workspace, root=root)
        if recovery_metadata is not None:
            result["recovery"] = recovery_metadata
        results.append(result)
        exports = result.get("exports") or {}
        for key, value in exports.items():
            context[key] = value
    _persist_probe_context(root=root, context=context)
    return results


def _load_probe_context(root: Path) -> dict[str, object]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    credentials = dict(manifest.get("credentials") or {})
    if not credentials:
        username = os.environ.get("ONBOARDING_SMOKE_USERNAME")
        email = os.environ.get("ONBOARDING_SMOKE_EMAIL")
        password = os.environ.get("ONBOARDING_SMOKE_PASSWORD")
        if username:
            credentials["username"] = username
        if email:
            credentials["email"] = email
        if password:
            credentials["password"] = password
    context: dict[str, object] = {}
    for key, value in credentials.items():
        if value is not None and value != "":
            context[f"probe.credentials.{key}"] = value
    return context


def _missing_credential_keys(*, step: SmokeTestStep, context: dict[str, object]) -> list[str]:
    referenced = sorted(
        {
            key
            for key in _collect_template_keys(step.model_dump())
            if key.startswith("probe.credentials.")
        }
    )
    return [key for key in referenced if not context.get(key)]


def _collect_template_keys(value: Any) -> list[str]:
    if isinstance(value, str):
        return TEMPLATE_PATTERN.findall(value)
    if isinstance(value, dict):
        keys: list[str] = []
        for item in value.values():
            keys.extend(_collect_template_keys(item))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for item in value:
            keys.extend(_collect_template_keys(item))
        return keys
    return []


def _normalize_recovery_payload(
    recovery_payload: SmokeRecoveryPayload | dict[str, Any] | None,
) -> SmokeRecoveryPayload | None:
    if recovery_payload is None:
        return None
    if isinstance(recovery_payload, SmokeRecoveryPayload):
        return recovery_payload
    if isinstance(recovery_payload, dict):
        allowed_keys = {
            "classification",
            "should_retry",
            "proposed_probe_updates",
            "proposed_schema_overrides",
            "repair_actions",
        }
        filtered_payload = {
            key: value
            for key, value in recovery_payload.items()
            if key in allowed_keys
        }
        return SmokeRecoveryPayload.model_validate(filtered_payload)
    return SmokeRecoveryPayload.model_validate(recovery_payload)


def _apply_recovery_to_step(
    *,
    step: SmokeTestStep,
    recovery_payload: SmokeRecoveryPayload | None,
) -> tuple[SmokeTestStep, dict[str, Any] | None]:
    if recovery_payload is None:
        return step, None

    step_payload = step.model_dump()
    probe_updates = [
        update for update in recovery_payload.proposed_probe_updates if update.step_id == step.id
    ]
    schema_overrides = [
        override for override in recovery_payload.proposed_schema_overrides if override.step_id == step.id
    ]
    if not probe_updates and not schema_overrides:
        return step, None

    for update in probe_updates:
        for key, value in update.merge.items():
            current = step_payload.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                merged = dict(current)
                merged.update(value)
                step_payload[key] = merged
            else:
                step_payload[key] = value

    for override in schema_overrides:
        if override.expects is not None:
            step_payload["expects"] = override.expects.model_dump()
        if override.exports:
            merged_exports = dict(step_payload.get("exports") or {})
            merged_exports.update(override.exports)
            step_payload["exports"] = merged_exports

    effective_step = SmokeTestStep.model_validate(step_payload)
    return effective_step, {
        "classification": recovery_payload.classification,
        "applied": True,
        "probe_update_step_ids": [update.step_id for update in probe_updates],
        "schema_override_step_ids": [override.step_id for override in schema_overrides],
    }


def _persist_probe_context(*, root: Path, context: dict[str, object]) -> None:
    if not context:
        return
    path = root / "reports" / "smoke-context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_script_step(*, step: SmokeTestStep, workspace: Path, root: Path) -> dict:
    script_path = (root / (step.script or "")).resolve()
    if not script_path.exists():
        return {
            "step": step.script,
            "step_id": step.id,
            "required": step.required,
            "category": step.category,
            "timed_out": False,
            "returncode": 127,
            "stdout": "",
            "stderr": f"Smoke script not found: {script_path}",
            "request": {"type": "script", "path": str(script_path)},
            "response": {
                "status": 127,
                "stdout": "",
                "stderr": f"Smoke script not found: {script_path}",
            },
            "exports": {},
        }

    try:
        proc = subprocess.run(
            [str(script_path)],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            timeout=step.timeout_seconds,
            env={**os.environ, **step.env},
        )
        returncode = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        timed_out = True

    return {
        "step": step.script,
        "step_id": step.id,
        "strategy": step.strategy,
        "uses": list(step.uses or []),
        "required": step.required,
        "category": step.category,
        "timed_out": timed_out,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "request": {"type": "script", "path": str(script_path)},
        "response": {
            "status": returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
        "exports": {},
    }


def summarize_smoke_results(results: list[dict]) -> dict:
    failures = [result for result in results if result.get("returncode") != 0]
    auth_bootstrap_passed = any(
        (result.get("step_id") or result.get("step")) == "chat-auth-token"
        and result.get("returncode") == 0
        for result in results
    )
    required_failures = [
        result.get("step_id") or result.get("step")
        for result in failures
        if result.get("required", True)
    ]
    optional_failures = [
        result.get("step_id") or result.get("step")
        for result in failures
        if not result.get("required", True)
    ]
    timed_out_steps = [
        result.get("step_id") or result.get("step")
        for result in failures
        if result.get("timed_out") is True
    ]
    missing_scripts = [
        result.get("step_id") or result.get("step")
        for result in failures
        if "Smoke script not found:" in (result.get("stderr") or "")
    ]
    failure_signature = None
    if failures:
        failure_tokens = sorted(
            f"{_normalize_smoke_step_token(result.get('step_id') or result.get('step'))}_{int(result.get('returncode') or 0)}"
            for result in failures
        )
        failure_detail = "|".join(failure_tokens)
        failure_signature = build_failure_signature(
            classification="smoke",
            detail=failure_detail,
        )

    return {
        "passed": len(required_failures) == 0,
        "total_steps": len(results),
        "failure_count": len(failures),
        "required_failures": required_failures,
        "optional_failures": optional_failures,
        "timed_out_steps": timed_out_steps,
        "missing_scripts": missing_scripts,
        "auth_bootstrap_passed": auth_bootstrap_passed,
        "failure_signature": failure_signature,
    }


def _normalize_smoke_step_token(step_name: Any) -> str:
    value = str(step_name or "").strip().lower()
    value = value.replace("-", "_").replace("/", "_").replace(".", "_")
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "unknown_step"
