from __future__ import annotations

from pathlib import Path

from chatbot.src.graph.brand_profiles import resolve_brand_profile
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
        capability_profile=plan.capability_profile,
        enabled_retrieval_corpora=plan.enabled_retrieval_corpora,
        widget_features=plan.widget_features,
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
    capability_profile: str,
    enabled_retrieval_corpora: list[str],
    widget_features: dict[str, object],
) -> list[str]:
    updated_lines = list(source_lines)
    current = "".join(updated_lines)
    if "__ORDER_CS_WIDGET_HOST_CONTRACT__" not in current:
        updated_lines = _insert_lines_after_import_block(
            updated_lines,
            _build_shared_widget_bootstrap_lines(
                chatbot_server_base_url_expression=chatbot_server_base_url_expression,
                site_id=plan.site_id,
                auth_bootstrap_path=auth_bootstrap_path,
                capability_profile=capability_profile,
                enabled_retrieval_corpora=enabled_retrieval_corpora,
                widget_features=widget_features,
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
    site_id: str | None,
    auth_bootstrap_path: str,
    capability_profile: str,
    enabled_retrieval_corpora: list[str],
    widget_features: dict[str, object],
) -> list[str]:
    brand_profile = resolve_brand_profile(site_id)
    lines = [
        "const ORDER_CS_WIDGET_HOST_CONTRACT = {\n",
        f"  chatbotServerBaseUrl: {chatbot_server_base_url_expression},\n",
        f'  authBootstrapPath: "{auth_bootstrap_path}",\n',
        '  widgetBundlePath: "/widget.js",\n',
        '  widgetElementTag: "order-cs-widget",\n',
        '  mountMode: "floating_launcher",\n',
        f'  siteId: "{str(site_id or "").strip()}",\n',
        f'  brandDisplayName: "{brand_profile.display_name}",\n',
        f'  brandStoreLabel: "{brand_profile.store_label}",\n',
        f'  assistantTitle: "{brand_profile.assistant_title}",\n',
        f'  initialGreeting: "{brand_profile.initial_greeting}",\n',
    ]
    if capability_profile and capability_profile != "order_cs_only":
        lines.append(f'  capabilityProfile: "{capability_profile}",\n')
    if enabled_retrieval_corpora:
        corpora_json = "[" + ", ".join(f'"{item}"' for item in enabled_retrieval_corpora) + "]"
        lines.append(f"  enabledRetrievalCorpora: {corpora_json},\n")
    if widget_features.get("image_upload"):
        lines.append('  widgetFeatures: { imageUpload: true },\n')
    lines.extend([
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
    ])
    return lines


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
