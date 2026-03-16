from __future__ import annotations

import json
from pathlib import Path


def _build_recommended_outputs(manifest: dict) -> list[str]:
    analysis = manifest.get("analysis", {})
    outputs: list[str] = []

    auth = analysis.get("auth", {})
    if auth.get("login_entrypoints") and auth.get("me_entrypoints"):
        outputs.append("chat_auth_endpoint")

    if analysis.get("frontend_mount_points"):
        outputs.append("frontend_widget_mount_patch")

    if analysis.get("product_api"):
        outputs.append("product_adapter_client")

    if analysis.get("order_api"):
        outputs.append("order_adapter_client")

    return outputs


def _build_default_smoke_steps(manifest: dict) -> list[dict]:
    analysis = manifest.get("analysis", {})
    steps: list[dict] = []

    auth = analysis.get("auth", {})
    if auth.get("login_entrypoints"):
        steps.append(
            {
                "id": "login",
                "script": "smoke-tests/login.sh",
                "env": {},
                "timeout_seconds": 5,
                "required": True,
                "category": "auth",
            }
        )
    if auth.get("me_entrypoints"):
        steps.append(
            {
                "id": "chat-auth-token",
                "script": "smoke-tests/chat_auth_token.sh",
                "env": {},
                "timeout_seconds": 5,
                "required": True,
                "category": "auth",
            }
        )
    if analysis.get("product_api"):
        steps.append(
            {
                "id": "product-api",
                "script": "smoke-tests/product_api.sh",
                "env": {},
                "timeout_seconds": 5,
                "required": True,
                "category": "catalog",
            }
        )
    if analysis.get("order_api"):
        steps.append(
            {
                "id": "order-api",
                "script": "smoke-tests/order_api.sh",
                "env": {},
                "timeout_seconds": 5,
                "required": True,
                "category": "orders",
            }
        )

    return steps


def _write_smoke_script(path: Path, message: str) -> None:
    path.write_text(f"#!/bin/sh\necho {message}\n", encoding="utf-8")
    path.chmod(0o755)


def generate_overlay_scaffold(run_root: str | Path) -> Path:
    root = Path(run_root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    (root / "files").mkdir(parents=True, exist_ok=True)
    (root / "patches").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    smoke_root = root / "smoke-tests"
    smoke_root.mkdir(parents=True, exist_ok=True)

    smoke_steps = _build_default_smoke_steps(manifest)
    smoke_messages = {
        "smoke-tests/login.sh": "login-ok",
        "smoke-tests/chat_auth_token.sh": "chat-auth-ok",
        "smoke-tests/product_api.sh": "product-api-ok",
        "smoke-tests/order_api.sh": "order-api-ok",
    }
    for step in smoke_steps:
        _write_smoke_script(
            root / step["script"],
            smoke_messages.get(step["script"], "smoke-ok"),
        )

    generation_plan = {
        "run_id": manifest.get("run_id"),
        "site": manifest.get("site"),
        "detected": manifest.get("analysis", {}),
        "recommended_outputs": _build_recommended_outputs(manifest),
    }

    manifest["tests"] = {
        **(manifest.get("tests") or {}),
        "smoke": smoke_steps,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (root / "reports" / "generation-plan.json").write_text(
        json.dumps(generation_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return root
