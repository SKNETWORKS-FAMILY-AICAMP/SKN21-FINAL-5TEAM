from __future__ import annotations

import json
import sys
from types import ModuleType
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

fake_langchain_ollama = ModuleType("langchain_ollama")


class _FakeChatOllama:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


fake_langchain_ollama.ChatOllama = _FakeChatOllama
sys.modules.setdefault("langchain_ollama", fake_langchain_ollama)

from chatbot.src.onboarding.patch_planner import write_patch_comparison_report


def test_write_patch_comparison_report_summarizes_deterministic_and_llm_drafts(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "run-001"
    deterministic_path = run_root / "patches" / "proposed.patch"
    llm_path = run_root / "patches" / "llm-proposed.patch"
    output_path = run_root / "reports" / "patch-comparison.json"

    deterministic_path.parent.mkdir(parents=True, exist_ok=True)
    deterministic_path.write_text(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,5 @@
 def login(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
""",
        encoding="utf-8",
    )
    llm_path.write_text(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,6 @@
 def login(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
+# extra comment
""",
        encoding="utf-8",
    )

    path = write_patch_comparison_report(
        run_root=run_root,
        output_path=output_path,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path == output_path
    assert payload["deterministic_patch"]["path"].endswith("patches/proposed.patch")
    assert payload["llm_patch"]["path"].endswith("patches/llm-proposed.patch")
    assert payload["same_content"] is False
    assert payload["deterministic_patch"]["target_files"] == ["backend/users/views.py"]
    assert payload["llm_patch"]["target_files"] == ["backend/users/views.py"]
    assert payload["llm_patch"]["line_count"] > payload["deterministic_patch"]["line_count"]
    assert payload["line_count_delta"] == (
        payload["llm_patch"]["line_count"] - payload["deterministic_patch"]["line_count"]
    )
    assert payload["target_file_delta"]["only_in_deterministic"] == []
    assert payload["target_file_delta"]["only_in_llm"] == []
    assert payload["recommended_source"] == "manual_review"


def test_write_patch_comparison_report_recommends_deterministic_when_llm_patch_missing(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "run-002"
    deterministic_path = run_root / "patches" / "proposed.patch"
    output_path = run_root / "reports" / "patch-comparison.json"

    deterministic_path.parent.mkdir(parents=True, exist_ok=True)
    deterministic_path.write_text(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,1 +1,2 @@
 def login(request):
+    return None
""",
        encoding="utf-8",
    )

    path = write_patch_comparison_report(
        run_root=run_root,
        output_path=output_path,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path == output_path
    assert payload["llm_patch"]["exists"] is False
    assert payload["recommended_source"] == "deterministic"
    assert payload["target_file_delta"]["only_in_deterministic"] == ["backend/users/views.py"]
    assert payload["target_file_delta"]["only_in_llm"] == []


def test_write_patch_comparison_report_prefers_llm_when_llm_simulation_passes_and_deterministic_fails(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "run-003"
    deterministic_path = run_root / "patches" / "proposed.patch"
    llm_path = run_root / "patches" / "llm-proposed.patch"
    reports_root = run_root / "reports"
    output_path = reports_root / "patch-comparison.json"

    deterministic_path.parent.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    deterministic_path.write_text(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,1 +1,2 @@
 def login(request):
+    return None
""",
        encoding="utf-8",
    )
    llm_path.write_text(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,1 +1,2 @@
 def login(request):
+    return None
""",
        encoding="utf-8",
    )
    (reports_root / "merge-simulation.json").write_text(
        json.dumps({"passed": False}),
        encoding="utf-8",
    )
    (reports_root / "llm-patch-simulation.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )

    payload = json.loads(
        write_patch_comparison_report(run_root=run_root, output_path=output_path).read_text(encoding="utf-8")
    )

    assert payload["simulation"]["deterministic_passed"] is False
    assert payload["simulation"]["llm_passed"] is True
    assert payload["recommended_source"] == "llm"


def test_write_patch_comparison_report_prefers_exported_replay_metadata_when_available(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "run-004"
    reports_root = run_root / "reports"
    deterministic_path = reports_root / "approved.patch"
    llm_path = reports_root / "llm-approved.patch"
    output_path = reports_root / "patch-comparison.json"

    reports_root.mkdir(parents=True, exist_ok=True)
    deterministic_path.write_text(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,1 +1,2 @@
 def login(request):
+    return None
""",
        encoding="utf-8",
    )
    llm_path.write_text(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,1 +1,3 @@
 def login(request):
+    return None
+# llm
""",
        encoding="utf-8",
    )
    (reports_root / "export-metadata.json").write_text(
        json.dumps({"patch_path": str(deterministic_path), "replay_passed": False}),
        encoding="utf-8",
    )
    (reports_root / "llm-export-metadata.json").write_text(
        json.dumps({"patch_path": str(llm_path), "replay_passed": True}),
        encoding="utf-8",
    )

    payload = json.loads(
        write_patch_comparison_report(run_root=run_root, output_path=output_path).read_text(encoding="utf-8")
    )

    assert payload["deterministic_patch"]["path"].endswith("reports/approved.patch")
    assert payload["llm_patch"]["path"].endswith("reports/llm-approved.patch")
    assert payload["simulation"]["deterministic_passed"] is False
    assert payload["simulation"]["llm_passed"] is True
    assert payload["recommended_source"] == "llm"
