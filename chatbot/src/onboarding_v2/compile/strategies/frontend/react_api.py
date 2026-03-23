from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.models.compile import EditOperation, FrontendApiBundle
from chatbot.src.onboarding_v2.models.planning import FrontendIntegrationPlan


def compile_react_api_bundle(
    *,
    source_root: str | Path,
    plan: FrontendIntegrationPlan,
) -> FrontendApiBundle:
    root = Path(source_root)
    target = root / plan.api_client_target
    if not target.exists():
        raise ValueError(f"frontend api target not found: {plan.api_client_target}")
    original = target.read_text(encoding="utf-8")
    updated = "".join(_build_frontend_api_client_updated_lines(original.splitlines(keepends=True)))
    return FrontendApiBundle(
        bundle_id="frontend:api",
        strategy=plan.api_strategy,
        target_path=plan.api_client_target,
        auth_bootstrap_path=plan.auth_bootstrap_path,
        operations=[
            EditOperation(
                path=plan.api_client_target,
                operation="replace_text",
                old=original,
                new=updated,
            )
        ],
    )


def _build_frontend_api_client_updated_lines(source_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    current_text = "".join(updated_lines)
    if "/api/chat/auth-token" not in current_text:
        updated_lines = _insert_lines_after_import_block(
            updated_lines,
            [
                'export const ORDER_CS_CHAT_AUTH_BOOTSTRAP_PATH = "/api/chat/auth-token";\n',
                "\n",
                "export function withOrderCsCredentials(config = {}) {\n",
                "  return {\n",
                "    ...config,\n",
                "    withCredentials: config.withCredentials ?? true,\n",
                "  };\n",
                "}\n",
                "\n",
            ],
        )
    return updated_lines


def _insert_lines_after_import_block(source_lines: list[str], insertion_lines: list[str]) -> list[str]:
    updated_lines = list(source_lines)
    insert_index = 0
    for index, line in enumerate(updated_lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_index = index + 1
            continue
        if stripped == "":
            if insert_index:
                insert_index = index + 1
            continue
        break
    updated_lines[insert_index:insert_index] = insertion_lines
    return updated_lines
