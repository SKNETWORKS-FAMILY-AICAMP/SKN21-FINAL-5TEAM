import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.template_generator import generate_frontend_mount_patch


def test_generate_frontend_mount_patch_creates_patch_for_detected_mount_file(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "frontend_mount_points": ["frontend/src/App.js"],
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    patch_path = generate_frontend_mount_patch(run_root)

    assert patch_path == run_root / "patches" / "frontend_widget_mount.patch"
    assert patch_path.exists()
    content = patch_path.read_text(encoding="utf-8")
    assert "--- a/frontend/src/App.js" in content
    assert "+++ b/frontend/src/App.js" in content
    assert "widget.js" in content
    assert "order-cs-widget" in content
    assert "/api/chat/auth-token" in content


def test_generate_frontend_mount_patch_uses_default_app_file_when_no_mount_detected(tmp_path: Path):
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "bilyeo-run-001",
                "site": "bilyeo",
                "source_root": "/workspace/bilyeo",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "frontend_mount_points": [],
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    patch_path = generate_frontend_mount_patch(run_root)

    content = patch_path.read_text(encoding="utf-8")
    assert "--- a/frontend/src/App.js" in content


def test_generate_frontend_mount_patch_uses_source_file_context_when_available(tmp_path: Path):
    source_root = tmp_path / "shop"
    run_root = tmp_path / "generated" / "shop" / "shop-run-001"
    run_root.mkdir(parents=True)

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "export default function App() {\n  return <main>Home</main>;\n}\n",
        encoding="utf-8",
    )

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "shop-run-001",
                "site": "shop",
                "source_root": str(source_root),
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "frontend_mount_points": ["frontend/src/App.js"],
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    patch_path = generate_frontend_mount_patch(run_root)

    content = patch_path.read_text(encoding="utf-8")
    assert "@@ -" in content
    assert 'globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"]' in content
    assert 'orderCsWidgetScript.dataset.orderCsWidgetBundle = "true";' in content
    assert "<order-cs-widget />" in content
    assert "+  <main>Home</main>;" not in content
    assert "+export default function App()" not in content


def test_generate_frontend_mount_patch_inserts_widget_inside_component_tree(tmp_path: Path):
    source_root = tmp_path / "food"
    run_root = tmp_path / "generated" / "food" / "food-run-322"
    run_root.mkdir(parents=True)

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        "import React from \"react\";\n"
        "\n"
        "function App() {\n"
        "  return (\n"
        "    <div>\n"
        "      <h1>Food</h1>\n"
        "    </div>\n"
        "  );\n"
        "}\n"
        "\n"
        "export default App;\n",
        encoding="utf-8",
    )

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-322",
                "site": "food",
                "source_root": str(source_root),
                "created_at": "2026-03-18T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {"frontend_mount_points": ["frontend/src/App.js"]},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    content = generate_frontend_mount_patch(run_root).read_text(encoding="utf-8")

    assert "+      <order-cs-widget />" in content
    assert "\n+export default App;\n+\n+  <order-cs-widget />" not in content


def test_generate_frontend_mount_patch_includes_widget_path(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "frontend-run-002"
    run_root.mkdir(parents=True)

    widget_path = "frontend/src/chatbot/SharedChatbotWidget.jsx"
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "frontend-run-002",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "frontend_widget_path": widget_path,
                    "frontend_mount_points": ["frontend/src/App.js"],
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    patch_path = generate_frontend_mount_patch(run_root)
    content = patch_path.read_text(encoding="utf-8")

    assert "widget.js" in content
    assert "order-cs-widget" in content
    assert "SharedChatbotWidget" not in content


def test_generate_frontend_mount_patch_prefers_strategy_mount_target_for_vue(tmp_path: Path):
    source_root = tmp_path / "shop"
    run_root = tmp_path / "generated" / "shop" / "shop-run-vue"
    run_root.mkdir(parents=True)

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.vue").write_text(
        "<template><main>Home</main></template>\n",
        encoding="utf-8",
    )

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "shop-run-vue",
                "site": "shop",
                "source_root": str(source_root),
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "frontend_strategy": "vue",
                    "frontend_mount_points": [],
                    "frontend_mount_targets": ["frontend/src/App.vue"],
                },
                "generated_files": [],
                "patch_targets": [],
                "frontend_artifacts": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    patch_path = generate_frontend_mount_patch(run_root)
    content = patch_path.read_text(encoding="utf-8")

    assert "--- a/frontend/src/App.vue" in content
    assert "<order-cs-widget />" in content
    assert "widget.js" in content


def test_generate_frontend_mount_patch_normalizes_vue_widget_path_into_src_boundary(tmp_path: Path):
    source_root = tmp_path / "bilyeo"
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-safe-vue"
    run_root.mkdir(parents=True)

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.vue").write_text(
        "<template>\n  <router-view />\n</template>\n",
        encoding="utf-8",
    )

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "bilyeo-run-safe-vue",
                "site": "bilyeo",
                "source_root": str(source_root),
                "created_at": "2026-03-19T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "frontend_strategy": "vue",
                    "frontend_widget_path": "frontend/widgets/SharedChatbotWidget.vue",
                    "frontend_mount_targets": ["frontend/src/App.vue"],
                },
                "generated_files": [],
                "patch_targets": [],
                "frontend_artifacts": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    content = generate_frontend_mount_patch(run_root).read_text(encoding="utf-8")

    assert 'globalThis["__ORDER_CS_WIDGET_HOST_CONTRACT__"]' in content
    assert "widget.js" in content
    assert "../widgets/SharedChatbotWidget" not in content


def test_generate_frontend_mount_patch_keeps_widget_outside_routes_children(tmp_path: Path):
    source_root = tmp_path / "food"
    run_root = tmp_path / "generated" / "food" / "food-run-routes-safe"
    run_root.mkdir(parents=True)

    (source_root / "frontend" / "src").mkdir(parents=True)
    (source_root / "frontend" / "src" / "App.js").write_text(
        'import { BrowserRouter, Routes, Route } from "react-router-dom";\n'
        "\n"
        "export default function App() {\n"
        "  return (\n"
        "    <BrowserRouter>\n"
        "      <main>\n"
        "        <Routes>\n"
        '          <Route path="/" element={<div>Home</div>} />\n'
        "        </Routes>\n"
        "      </main>\n"
        "    </BrowserRouter>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-routes-safe",
                "site": "food",
                "source_root": str(source_root),
                "created_at": "2026-03-22T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {"frontend_mount_points": ["frontend/src/App.js"]},
                "generated_files": [],
                "patch_targets": [],
                "frontend_artifacts": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    content = generate_frontend_mount_patch(run_root).read_text(encoding="utf-8")

    assert "+      <order-cs-widget />\n         </Routes>\n" not in content
    assert "+      <order-cs-widget />\n       </main>\n" in content
