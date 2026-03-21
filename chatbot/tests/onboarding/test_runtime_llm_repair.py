import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding import runtime_llm_repair as runtime_llm_repair_module


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLlm:
    def __init__(self):
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return _FakeResponse("")


def test_normalize_patch_response_rejects_apply_patch_format():
    raw_response = (
        "*** Begin Patch\n"
        "*** Update File: manage.py\n"
        "@@\n"
        "-old\n"
        "+new\n"
        "*** End Patch\n"
    )

    normalized = runtime_llm_repair_module._normalize_patch_response(raw_response)

    assert normalized == ""


def test_build_candidate_file_list_prefers_traceback_and_runtime_entrypoints(tmp_path: Path):
    runtime_workspace = tmp_path / "workspace"
    urls_path = runtime_workspace / "backend" / "foodshop" / "urls.py"
    chat_auth_path = runtime_workspace / "backend" / "chat_auth.py"
    app_path = runtime_workspace / "frontend" / "src" / "App.js"
    widget_path = runtime_workspace / "frontend" / "src" / "chatbot" / "SharedChatbotWidget.jsx"

    urls_path.parent.mkdir(parents=True, exist_ok=True)
    chat_auth_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.parent.mkdir(parents=True, exist_ok=True)
    widget_path.parent.mkdir(parents=True, exist_ok=True)

    for path in (urls_path, chat_auth_path, app_path, widget_path):
        path.write_text("// sample\n", encoding="utf-8")

    candidates = runtime_llm_repair_module._build_candidate_file_list(
        runtime_workspace=runtime_workspace,
        evidence_payload={
            "backend_probe": {
                "stderr": (
                    'Traceback (most recent call last):\n'
                    f'  File "{urls_path}", line 1, in <module>\n'
                    "    from backend.chat_auth import chat_auth_token\n"
                    "ModuleNotFoundError: No module named 'backend'\n"
                )
            },
            "frontend_probe": {
                "stderr": "ERROR in ./src/chatbot/SharedChatbotWidget.jsx Module not found",
            },
        },
    )

    assert "backend/foodshop/urls.py" in candidates
    assert "backend/chat_auth.py" in candidates
    assert "frontend/src/App.js" in candidates
    assert "frontend/src/chatbot/SharedChatbotWidget.jsx" in candidates


def test_attempt_llm_runtime_repair_normalizes_non_json_evidence(tmp_path: Path):
    runtime_workspace = tmp_path / "workspace"
    run_root = tmp_path / "run"
    urls_path = runtime_workspace / "backend" / "foodshop" / "urls.py"

    urls_path.parent.mkdir(parents=True, exist_ok=True)
    urls_path.write_text("from chat_auth import chat_auth_token\n", encoding="utf-8")

    fake_llm = _FakeLlm()

    result = runtime_llm_repair_module.attempt_llm_runtime_repair(
        run_root=run_root,
        runtime_workspace=runtime_workspace,
        failure_signature="backend_server_boot_failed",
        evidence_payload={
            "backend_probe": {
                "stderr": f'Traceback:\n  File "{urls_path}", line 1, in <module>\n',
                "process": object(),
            }
        },
        attempt_id="validation-1",
        llm_factory=lambda: fake_llm,
    )

    assert fake_llm.calls
    assert result["failure_reason"] == "invalid_llm_response"
