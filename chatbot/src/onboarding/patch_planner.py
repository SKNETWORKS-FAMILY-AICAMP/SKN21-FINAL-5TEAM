from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any


def build_patch_proposal(
    *,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
) -> dict[str, Any]:
    target_files: list[dict[str, str]] = []
    for target in codebase_map.get("candidate_edit_targets") or []:
        target_files.append(
            {
                "path": str(target.get("path") or ""),
                "reason": str(target.get("reason") or ""),
                "intent": _infer_intent(
                    path=str(target.get("path") or ""),
                    analysis=analysis,
                    recommended_outputs=recommended_outputs,
                ),
            }
        )

    supporting_generated_files = _supporting_files(recommended_outputs)
    return {
        "target_files": target_files,
        "supporting_generated_files": supporting_generated_files,
        "recommended_outputs": recommended_outputs,
        "analysis_summary": {
            "auth_style": ((analysis.get("auth") or {}).get("auth_style") or "unknown"),
            "frontend_mount_points": analysis.get("frontend_mount_points") or [],
            "route_prefixes": analysis.get("route_prefixes") or [],
        },
    }


def write_patch_proposal(
    *,
    analysis: dict[str, Any],
    codebase_map: dict[str, Any],
    recommended_outputs: list[str],
    output_path: str | Path,
) -> Path:
    payload = build_patch_proposal(
        analysis=analysis,
        codebase_map=codebase_map,
        recommended_outputs=recommended_outputs,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_unified_diff_draft(
    *,
    source_root: str | Path,
    generated_run_root: str | Path,
    output_path: str | Path,
) -> Path:
    source = Path(source_root)
    generated_root = Path(generated_run_root)
    patch_chunks: list[str] = []

    files_root = generated_root / "files"
    if files_root.exists():
        for generated_file in sorted(path for path in files_root.rglob("*") if path.is_file()):
            relative = generated_file.relative_to(files_root)
            source_file = source / relative
            source_lines = _read_text_or_empty(source_file)
            generated_lines = _read_text_or_empty(generated_file)
            if source_lines == generated_lines:
                continue
            diff = difflib.unified_diff(
                source_lines,
                generated_lines,
                fromfile=f"a/{relative.as_posix()}",
                tofile=f"b/{relative.as_posix()}",
            )
            patch_chunks.append("".join(diff))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(patch_chunks), encoding="utf-8")
    return path


def _infer_intent(*, path: str, analysis: dict[str, Any], recommended_outputs: list[str]) -> str:
    lower = path.lower()
    if "views.py" in lower:
        return "extend backend auth/session handler for onboarding-compatible chat auth"
    if "urls.py" in lower:
        return "wire onboarding-related route entrypoint without touching the original source directly"
    if lower.endswith(("app.js", "app.jsx", "app.tsx", "app.ts", ".vue")):
        return "identify frontend widget mount integration point"
    if recommended_outputs:
        return f"support {recommended_outputs[0]} capability"
    return f"support auth style {((analysis.get('auth') or {}).get('auth_style') or 'unknown')}"


def _supporting_files(recommended_outputs: list[str]) -> list[str]:
    file_map = {
        "chat_auth": "files/backend/chat_auth.py",
        "order_adapter": "files/backend/order_adapter_client.py",
        "product_adapter": "files/backend/product_adapter_client.py",
        "frontend_patch": "patches/frontend_widget_mount.patch",
    }
    return [file_map[item] for item in recommended_outputs if item in file_map]


def _read_text_or_empty(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines(keepends=True)
