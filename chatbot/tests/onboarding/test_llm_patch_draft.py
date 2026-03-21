from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")
sys.modules.setdefault("langchain_ollama", types.SimpleNamespace(ChatOllama=object))

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.patch_planner import write_llm_patch_draft


class FakeLLM:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return type("LLMResponse", (), {"content": self.content})()


class SequentialFakeLLM:
    def __init__(self, contents: list[str]):
        self.contents = contents
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        index = min(len(self.calls) - 1, len(self.contents) - 1)
        return type("LLMResponse", (), {"content": self.contents[index]})()


def test_write_llm_patch_draft_recovery_strips_fences_and_records_recovered_llm(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """```diff
--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,6 @@
 def login(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
```"""
    )

    path = write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [{"path": "backend/users/views.py", "reason": "auth handler"}]
        },
        patch_proposal={
            "target_files": [{"path": "backend/users/views.py", "intent": "add auth stub"}],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    content = path.read_text(encoding="utf-8")
    execution = json.loads((run_root / "reports" / "llm-patch-draft-execution.json").read_text(encoding="utf-8"))

    assert path == output_path
    assert "--- a/backend/users/views.py" in content
    assert "+++ b/backend/users/views.py" in content
    assert "onboarding_chat_auth_token" in content
    assert "unified diff" in str(fake_llm.calls[0][0].content).lower()
    assert execution["source"] == "recovered_llm"
    assert execution["recovery_reason"] == "patch_fences_removed"
    assert execution["hard_fallback_reason"] is None


def test_write_llm_patch_draft_includes_evidence_in_user_prompt(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "generated" / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "config").mkdir(parents=True)
    (source_root / "backend" / "config" / "router.py").write_text(
        "urlpatterns = []\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """--- a/backend/config/router.py
+++ b/backend/config/router.py
@@ -1 +1,2 @@
 urlpatterns = []
+# ok
"""
    )

    write_llm_patch_draft(
        source_root=source_root,
        analysis={"route_prefixes": ["api/account/"]},
        codebase_map={
            "urlconf_candidates": [{"path": "backend/config/router.py", "has_urlpatterns": True}],
            "candidate_edit_targets": [{"path": "backend/config/router.py", "reason": "route candidate"}],
        },
        patch_proposal={
            "target_files": [{"path": "backend/config/router.py", "intent": "register route"}],
            "analysis_summary": {"route_prefixes": ["api/account/"]},
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    user_message = str(fake_llm.calls[0][1].content)
    assert '"path": "backend/config/router.py"' in user_message
    assert '"route_prefixes": [' in user_message


def test_write_llm_patch_draft_recovery_uses_hard_fallback_for_malformed_patch(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ malformed
"""
    )

    path = write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [{"path": "backend/users/views.py", "reason": "auth handler"}]
        },
        patch_proposal={
            "target_files": [{"path": "backend/users/views.py", "intent": "add auth stub"}],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    content = path.read_text(encoding="utf-8")
    execution = json.loads((run_root / "reports" / "llm-patch-draft-execution.json").read_text(encoding="utf-8"))
    debug_payload = json.loads((run_root / "reports" / "llm-debug" / "patch-draft.json").read_text(encoding="utf-8"))
    generation_log = (run_root / "reports" / "generation.log").read_text(encoding="utf-8")

    assert path == output_path
    assert "LLM patch rejected" in content
    assert execution["source"] == "hard_fallback"
    assert execution["hard_fallback_reason"] == "invalid_patch_format"
    assert debug_payload["status"] == "hard_fallback"
    assert debug_payload["hard_fallback_reason"] == "invalid_patch_format"
    assert "hard_fallback" in generation_log


def test_write_llm_patch_draft_recovery_removes_redundant_hunk_marker(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,5 @@
@@
 def login(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
"""
    )

    path = write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [{"path": "backend/users/views.py", "reason": "auth handler"}]
        },
        patch_proposal={
            "target_files": [{"path": "backend/users/views.py", "intent": "add auth stub"}],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    content = path.read_text(encoding="utf-8")
    execution = json.loads((run_root / "reports" / "llm-patch-draft-execution.json").read_text(encoding="utf-8"))

    assert "\n@@\n" not in content
    assert execution["source"] == "recovered_llm"
    assert execution["recovery_reason"] == "patch_redundant_hunk_marker_removed"


def test_write_llm_patch_draft_prompt_requires_strict_unified_diff_contract(tmp_path: Path):
    source_root = tmp_path / "source"
    output_path = tmp_path / "generated" / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,3 @@
 def login(request):
     return None
+# ok
"""
    )

    write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={"candidate_edit_targets": [{"path": "backend/users/views.py", "reason": "auth handler"}]},
        patch_proposal={"target_files": [{"path": "backend/users/views.py", "intent": "add auth stub"}]},
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    system_message = str(fake_llm.calls[0][0].content)

    assert "@@ -old_start,old_count +new_start,new_count @@" in system_message
    assert "Every target file diff must include --- a/path, +++ b/path, and at least one @@ hunk header." in system_message
    assert "Do not return prose, bullets, comments, or code fences outside the unified diff." in system_message


def test_write_llm_patch_draft_recovers_valid_prefix_from_multifile_malformed_diff(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "config").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "config" / "router.py").write_text(
        "urlpatterns = []\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,5 @@
 def login(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
--- a/backend/config/router.py
+++ b/backend/config/router.py
@@ malformed
"""
    )

    path = write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [
                {"path": "backend/users/views.py", "reason": "auth handler"},
                {"path": "backend/config/router.py", "reason": "route wiring"},
            ]
        },
        patch_proposal={
            "target_files": [
                {"path": "backend/users/views.py", "intent": "add auth stub"},
                {"path": "backend/config/router.py", "intent": "register route"},
            ],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    content = path.read_text(encoding="utf-8")
    execution = json.loads((run_root / "reports" / "llm-patch-draft-execution.json").read_text(encoding="utf-8"))

    assert path == output_path
    assert "--- a/backend/users/views.py" in content
    assert "+++ b/backend/users/views.py" in content
    assert "onboarding_chat_auth_token" in content
    assert "backend/config/router.py" not in content
    assert execution["source"] == "recovered_llm"
    assert execution["recovery_reason"] == "patch_invalid_trailing_file_section_removed"
    assert execution["hard_fallback_reason"] is None


def test_write_llm_patch_draft_retries_invalid_patch_format_once(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    fake_llm = SequentialFakeLLM(
        [
            """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ malformed
""",
            """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,5 @@
 def login(request):
     return None
+
+def onboarding_chat_auth_token(request):
+    return None
""",
        ]
    )

    path = write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [{"path": "backend/users/views.py", "reason": "auth handler"}]
        },
        patch_proposal={
            "target_files": [{"path": "backend/users/views.py", "intent": "add auth stub"}],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    content = path.read_text(encoding="utf-8")
    execution = json.loads((run_root / "reports" / "llm-patch-draft-execution.json").read_text(encoding="utf-8"))
    debug_payload = json.loads((run_root / "reports" / "llm-debug" / "patch-draft.json").read_text(encoding="utf-8"))

    assert path == output_path
    assert len(fake_llm.calls) == 2
    assert "onboarding_chat_auth_token" in content
    assert execution["source"] == "recovered_llm"
    assert execution["recovery_reason"] == "invalid_patch_format_retry_succeeded"
    assert execution["hard_fallback_reason"] is None
    assert debug_payload["attempt_count"] == 2


def test_write_llm_patch_draft_does_not_salvage_truncated_prefix_section(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "config").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "config" / "router.py").write_text(
        "urlpatterns = []\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,5 @@
 def login(request):
     return None
+
--- a/backend/config/router.py
+++ b/backend/config/router.py
@@ malformed
"""
    )

    path = write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [
                {"path": "backend/users/views.py", "reason": "auth handler"},
                {"path": "backend/config/router.py", "reason": "route wiring"},
            ]
        },
        patch_proposal={
            "target_files": [
                {"path": "backend/users/views.py", "intent": "add auth stub"},
                {"path": "backend/config/router.py", "intent": "register route"},
            ],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    content = path.read_text(encoding="utf-8")
    execution = json.loads((run_root / "reports" / "llm-patch-draft-execution.json").read_text(encoding="utf-8"))

    assert "LLM patch rejected" in content
    assert execution["source"] == "hard_fallback"
    assert execution["hard_fallback_reason"] == "invalid_patch_format"


def test_write_llm_patch_draft_records_retry_failure_details(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )

    fake_llm = SequentialFakeLLM(
        [
            """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ malformed
""",
            """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ still malformed
""",
        ]
    )

    write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [{"path": "backend/users/views.py", "reason": "auth handler"}]
        },
        patch_proposal={
            "target_files": [{"path": "backend/users/views.py", "intent": "add auth stub"}],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    debug_payload = json.loads((run_root / "reports" / "llm-debug" / "patch-draft.json").read_text(encoding="utf-8"))

    assert debug_payload["attempt_count"] == 2
    assert debug_payload["retry_error_type"] == "invalid_patch_format"
    assert "invalid unified diff hunk header" in debug_payload["retry_error_message"]


def test_write_llm_patch_draft_does_not_salvage_prefix_section_with_trailing_prose(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "config").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "config" / "router.py").write_text(
        "urlpatterns = []\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
@@ -1,2 +1,3 @@
 def login(request):
     return None
+# ok
THIS IS NOT DIFF CONTENT
--- a/backend/config/router.py
+++ b/backend/config/router.py
@@ malformed
"""
    )

    path = write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [
                {"path": "backend/users/views.py", "reason": "auth handler"},
                {"path": "backend/config/router.py", "reason": "route wiring"},
            ]
        },
        patch_proposal={
            "target_files": [
                {"path": "backend/users/views.py", "intent": "add auth stub"},
                {"path": "backend/config/router.py", "intent": "register route"},
            ],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    content = path.read_text(encoding="utf-8")
    execution = json.loads((run_root / "reports" / "llm-patch-draft-execution.json").read_text(encoding="utf-8"))

    assert "LLM patch rejected" in content
    assert execution["source"] == "hard_fallback"
    assert execution["hard_fallback_reason"] == "invalid_patch_format"


def test_write_llm_patch_draft_does_not_salvage_prefix_section_with_prose_before_first_hunk(tmp_path: Path):
    source_root = tmp_path / "source"
    run_root = tmp_path / "generated"
    output_path = run_root / "patches" / "llm-proposed.patch"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "config").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "config" / "router.py").write_text(
        "urlpatterns = []\n",
        encoding="utf-8",
    )

    fake_llm = FakeLLM(
        """--- a/backend/users/views.py
+++ b/backend/users/views.py
THIS IS NOT A HUNK HEADER
@@ -1,2 +1,3 @@
 def login(request):
     return None
+# ok
--- a/backend/config/router.py
+++ b/backend/config/router.py
@@ malformed
"""
    )

    path = write_llm_patch_draft(
        source_root=source_root,
        analysis={"auth": {"auth_style": "session_cookie"}},
        codebase_map={
            "candidate_edit_targets": [
                {"path": "backend/users/views.py", "reason": "auth handler"},
                {"path": "backend/config/router.py", "reason": "route wiring"},
            ]
        },
        patch_proposal={
            "target_files": [
                {"path": "backend/users/views.py", "intent": "add auth stub"},
                {"path": "backend/config/router.py", "intent": "register route"},
            ],
            "supporting_generated_files": ["files/backend/chat_auth.py"],
        },
        output_path=output_path,
        llm_factory=lambda: fake_llm,
    )

    content = path.read_text(encoding="utf-8")
    execution = json.loads((run_root / "reports" / "llm-patch-draft-execution.json").read_text(encoding="utf-8"))

    assert "LLM patch rejected" in content
    assert execution["source"] == "hard_fallback"
    assert execution["hard_fallback_reason"] == "invalid_patch_format"
