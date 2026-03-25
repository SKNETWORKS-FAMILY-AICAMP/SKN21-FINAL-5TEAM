from __future__ import annotations

from pathlib import Path

from chatbot.src.onboarding_v2.models.compile import EditOperation, FrontendMountBundle
from chatbot.src.onboarding_v2.models.planning import HostFrontendPlan


def compile_react_mount_bundle(
    *,
    source_root: str | Path,
    plan: HostFrontendPlan,
) -> FrontendMountBundle:
    root = Path(source_root)
    target = root / plan.mount_target
    if not target.exists():
        raise ValueError(f"frontend mount target not found: {plan.mount_target}")
    original = target.read_text(encoding="utf-8")
    updated_lines = _build_react_mount_updated_lines(
        original.splitlines(keepends=True),
        chatbot_server_base_url_expression=plan.chatbot_server_base_url_expression,
        auth_bootstrap_path=plan.auth_bootstrap_path,
    )
    return FrontendMountBundle(
        bundle_id="frontend:mount",
        strategy=plan.mount_strategy,
        target_path=plan.mount_target,
        operations=[
            EditOperation(
                path=plan.mount_target,
                operation="replace_text",
                old=original,
                new="".join(updated_lines),
            )
        ],
    )


def _build_react_mount_updated_lines(
    source_lines: list[str],
    *,
    chatbot_server_base_url_expression: str,
    auth_bootstrap_path: str,
) -> list[str]:
    updated_lines = list(source_lines)
    current = "".join(updated_lines)
    if "__ORDER_CS_WIDGET_HOST_CONTRACT__" not in current:
        updated_lines = _insert_lines_after_import_block(
            updated_lines,
            _build_shared_widget_bootstrap_lines(
                chatbot_server_base_url_expression=chatbot_server_base_url_expression,
                auth_bootstrap_path=auth_bootstrap_path,
            ),
        )
    widget_line = "      <order-cs-widget />\n"
    if widget_line not in updated_lines:
        insert_index = _find_mount_insert_index(updated_lines)
        if insert_index is None:
            updated_lines.extend(["\n", "  <order-cs-widget />\n"])
        else:
            updated_lines.insert(insert_index, widget_line)
    return updated_lines


def _build_shared_widget_bootstrap_lines(
    *,
    chatbot_server_base_url_expression: str,
    auth_bootstrap_path: str,
) -> list[str]:
    return [
        "const ORDER_CS_WIDGET_HOST_CONTRACT = {\n",
        f"  chatbotServerBaseUrl: {chatbot_server_base_url_expression},\n",
        f'  authBootstrapPath: "{auth_bootstrap_path}",\n',
        '  widgetBundlePath: "/widget.js",\n',
        '  widgetElementTag: "order-cs-widget",\n',
        '  mountMode: "floating_launcher",\n',
        "};\n",
        "\n",
        'if (typeof globalThis === "object") {\n',
        '  globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"] = ORDER_CS_WIDGET_HOST_CONTRACT;\n',
        "}\n",
        "\n",
        'if (typeof document !== "undefined" && !document.querySelector(\'script[data-order-cs-widget-bundle="true"]\')) {\n',
        '  const orderCsWidgetScript = document.createElement("script");\n',
        "  orderCsWidgetScript.src = `${ORDER_CS_WIDGET_HOST_CONTRACT.chatbotServerBaseUrl}${ORDER_CS_WIDGET_HOST_CONTRACT.widgetBundlePath}`;\n",
        "  orderCsWidgetScript.async = true;\n",
        '  orderCsWidgetScript.dataset.orderCsWidgetBundle = "true";\n',
        "  document.head.appendChild(orderCsWidgetScript);\n",
        "}\n",
        "\n",
    ]


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


def _find_mount_insert_index(lines: list[str]) -> int | None:
    preferred_markers = {"</main>", "</BrowserRouter>", "</div>"}
    for index, line in enumerate(lines):
        if line.strip() in preferred_markers:
            return index
    return None
