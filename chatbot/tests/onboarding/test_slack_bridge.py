import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.agent_contracts import AgentMessage, ApprovalType, RunEvent, RunState
from chatbot.src.onboarding.slack_bridge import InMemorySlackBridge, SlackWebBridge


def test_slack_bridge_posts_root_message_and_preserves_thread_key():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    payload = bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    assert payload["channel"] == "#onboarding-runs"
    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["run_id"] == "food-run-001"


def test_slack_bridge_posts_agent_message_into_same_thread():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    event = RunEvent(
        event_type="analysis.completed",
        run_id="food-run-001",
        state=RunState.ANALYZING,
        payload={"phase": "analysis"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Analyzer",
        claim="Detected session auth",
        evidence=["session token cookie is read in login flow"],
        confidence=0.91,
        risk="medium",
        next_action="forward auth capability to planner",
        blocking_issue="none",
    )

    payload = bridge.post_agent_message(event=event, message=message)

    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["role"] == "Analyzer"
    assert payload["message"]["event_type"] == "analysis.completed"


def test_slack_bridge_posts_approval_request_payload():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    payload = bridge.post_approval_request(
        run_id="food-run-001",
        approval_type=ApprovalType.APPLY,
        summary="Overlay is ready to apply",
        recommended_option="approve",
        risk_if_approved="runtime patch may fail",
        risk_if_rejected="run will stop before validation",
        available_actions=["approve", "reject"],
    )

    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["approval_type"] == "apply"
    assert payload["message"]["recommended_option"] == "approve"
    actions = payload["message"]["actions"]
    assert actions[0]["text"] == "진행"
    approve_value = json.loads(actions[0]["value"])
    assert approve_value["run_id"] == "food-run-001"
    assert approve_value["approval_type"] == "apply"
    assert approve_value["decision"] == "approve"
    assert actions[1]["text"] == "보류"
    reject_value = json.loads(actions[1]["value"])
    assert reject_value["decision"] == "reject"


def test_slack_bridge_keeps_all_messages_in_memory():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    bridge.post_approval_request(
        run_id="food-run-001",
        approval_type=ApprovalType.ANALYSIS,
        summary="Confirm analysis",
        recommended_option="approve",
        risk_if_approved="bad analysis propagates",
        risk_if_rejected="run pauses",
        available_actions=["approve", "reject"],
    )

    assert len(bridge.messages) == 2
    assert all(entry["thread_key"] == "food-run-001" for entry in bridge.messages)


def test_slack_bridge_preserves_diagnostic_evidence():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    event = RunEvent(
        event_type="diagnosis.completed",
        run_id="food-run-001",
        state=RunState.DIAGNOSING,
        payload={"phase": "diagnosis"},
        created_at="2026-03-16T10:00:00+09:00",
    )
    message = AgentMessage(
        role="Diagnostician",
        claim="Structural failure should stop retries",
        evidence=[
            "failure signature: missing:127",
            "retryable: False",
            "missing scripts: ['missing']",
        ],
        confidence=0.9,
        risk="high",
        next_action="request_human_review",
        blocking_issue="missing smoke script",
    )

    payload = bridge.post_agent_message(event=event, message=message)

    assert payload["message"]["role"] == "Diagnostician"
    assert "retryable: False" in payload["message"]["evidence"]


def test_slack_bridge_can_record_export_approval_decision():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    payload = bridge.record_approval_decision(
        run_id="food-run-001",
        approval_type="export",
        decision="approve",
    )

    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["approval_type"] == "export"
    assert payload["message"]["decision"] == "approve"


def test_slack_bridge_can_record_run_summary():
    bridge = InMemorySlackBridge(channel="#onboarding-runs")

    payload = bridge.post_run_summary(
        run_id="food-run-001",
        current_state="completed",
        pending_approval=None,
        artifacts={
            "proposed_patch": "/tmp/generated/food/proposed.patch",
            "merge_simulation": "/tmp/generated/food/merge-simulation.json",
        },
    )

    assert payload["thread_key"] == "food-run-001"
    assert payload["message"]["kind"] == "run_summary"
    assert payload["message"]["current_state"] == "completed"


def test_slack_web_bridge_stores_thread_ts_from_root_message():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client, conversation_mode="thread")

    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    event = RunEvent(
        event_type="analysis.completed",
        run_id="food-run-001",
        state=RunState.ANALYZING,
        payload={"phase": "analysis"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Analyzer",
        claim="Detected session auth",
        evidence=["session token cookie is read in login flow"],
        confidence=0.91,
        risk="medium",
        next_action="forward auth capability to planner",
        blocking_issue="none",
    )

    bridge.post_agent_message(event=event, message=message)

    assert client.calls[1]["thread_ts"] == "1710000000.100"


def test_slack_web_bridge_posts_block_kit_approval_message():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    payload = bridge.post_approval_request(
        run_id="food-run-001",
        approval_type=ApprovalType.APPLY,
        summary="Overlay is ready to apply",
        recommended_option="approve",
        risk_if_approved="runtime patch may fail",
        risk_if_rejected="run will stop before validation",
        available_actions=["approve", "reject"],
    )

    blocks = client.calls[-1]["blocks"]
    assert blocks[-1]["type"] == "actions"
    assert blocks[-1]["elements"][0]["type"] == "button"
    assert blocks[1]["text"]["text"] == "승인 확인: 적용"
    assert "왜 필요한가" in blocks[2]["text"]["text"]
    assert "다음 단계" in blocks[3]["text"]["text"]
    assert blocks[-1]["elements"][0]["text"]["text"] == "진행"
    assert blocks[-1]["elements"][1]["text"]["text"] == "보류"
    assert payload["message"]["approval_type"] == "apply"
    assert client.calls[-1]["username"] == "Approval Gate"


def test_slack_web_bridge_posts_agent_persona_blocks():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    event = RunEvent(
        event_type="analysis.completed",
        run_id="food-run-001",
        state=RunState.ANALYZING,
        payload={"phase": "analysis"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Analyzer",
        claim="Detected session auth",
        evidence=["session token cookie is read in login flow"],
        confidence=0.91,
        risk="medium",
        next_action="forward auth capability to planner",
        blocking_issue="none",
    )

    bridge.post_agent_message(event=event, message=message)

    blocks = client.calls[-1]["blocks"]
    rendered = json.dumps(blocks, ensure_ascii=False)
    assert "요약" in blocks[0]["text"]["text"]
    assert "핵심 근거" in rendered
    assert "다음 액션" in rendered
    assert "분석 결과를 공유합니다." in blocks[0]["text"]["text"]
    assert "구조 확인 중" not in rendered
    assert "confidence" not in rendered
    assert "risk:" not in rendered
    assert client.calls[-1]["username"] == "Onboarding Analyzer"


def test_slack_web_bridge_posts_human_readable_generator_narrative():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    event = RunEvent(
        event_type="generation.completed",
        run_id="food-run-001",
        state=RunState.GENERATING,
        payload={"phase": "generation"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Generator",
        claim="Prepared overlay artifact proposal",
        evidence=[
            "frontend mount point detected in frontend/src/App.js",
            "session-cookie auth flow detected in backend/users/views.py",
        ],
        confidence=0.88,
        risk="medium",
        next_action="materialize proposed files and patches",
        blocking_issue="none",
        metadata={
            "proposed_files": [
                "files/backend/chat_auth.py",
                "files/frontend/src/chatbot/SharedChatbotWidget.jsx",
            ],
            "proposed_patches": ["patches/frontend_widget_mount.patch"],
        },
    )

    bridge.post_agent_message(event=event, message=message)

    blocks = client.calls[-1]["blocks"]
    narrative_text = json.dumps(blocks, ensure_ascii=False)

    assert "요약" in narrative_text
    assert "대상 파일" in narrative_text
    assert "핵심 근거" in narrative_text
    assert "SharedChatbotWidget.jsx" in narrative_text
    assert "frontend_widget_mount.patch" in narrative_text
    assert "상세 산출물" not in narrative_text


def test_slack_web_bridge_posts_run_summary_blocks():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    bridge.post_run_summary(
        run_id="food-run-001",
        current_state="completed",
        pending_approval=None,
        artifacts={
            "proposed_patch": "/tmp/generated/food/proposed.patch",
            "patch_comparison": "/tmp/generated/food/patch-comparison.json",
            "merge_simulation": "/tmp/generated/food/merge-simulation.json",
        },
    )

    blocks = client.calls[-1]["blocks"]
    summary_text = json.dumps(blocks, ensure_ascii=False)
    assert blocks[1]["text"]["text"] == "최종 요약"
    assert "온보딩 준비 완료" in summary_text
    assert "대기 중 승인" in summary_text
    assert "proposed.patch" not in summary_text
    assert client.calls[-1]["username"] == "Run Reporter"


def test_slack_web_bridge_posts_human_readable_run_summary_from_patch_proposal(tmp_path: Path):
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    proposal_path = tmp_path / "patch-proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "target_files": [
                    {
                        "path": "frontend/src/App.js",
                        "reason": "frontend app shell",
                        "intent": "mount chatbot widget",
                    },
                    {
                        "path": "backend/users/views.py",
                        "reason": "auth handler",
                        "intent": "add onboarding auth stub",
                    },
                ],
                "supporting_generated_files": [
                    "files/backend/chat_auth.py",
                    "files/frontend/src/chatbot/SharedChatbotWidget.jsx",
                ],
                "recommended_outputs": ["chat_auth", "frontend_patch"],
                "analysis_summary": {
                    "auth_style": "session_cookie",
                    "frontend_mount_points": ["frontend/src/App.js"],
                    "route_prefixes": ["/api"],
                },
            }
        ),
        encoding="utf-8",
    )

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_summary(
        run_id="food-run-001",
        current_state="completed",
        pending_approval=None,
        artifacts={
            "patch_proposal": proposal_path,
        },
    )

    summary_text = json.dumps(client.calls[-1]["blocks"], ensure_ascii=False)

    assert "만든 것" in summary_text
    assert "수정 대상" in summary_text
    assert "핵심 판단" in summary_text
    assert "SharedChatbotWidget.jsx" in summary_text
    assert "frontend/src/App.js" in summary_text
    assert "session_cookie" in summary_text


def test_slack_web_bridge_omits_internal_patch_recommendation_details_from_summary(tmp_path: Path):
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    comparison_path = tmp_path / "patch-comparison.json"
    comparison_path.write_text(
        json.dumps(
            {
                "recommended_source": "llm",
                "simulation": {
                    "deterministic_passed": False,
                    "llm_passed": True,
                },
            }
        ),
        encoding="utf-8",
    )

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    bridge.post_run_summary(
        run_id="food-run-001",
        current_state="completed",
        pending_approval=None,
        artifacts={
            "patch_comparison": comparison_path,
        },
    )

    blocks = client.calls[-1]["blocks"]
    summary_text = json.dumps(blocks, ensure_ascii=False)

    assert "추천 patch" not in summary_text
    assert "deterministic=False" not in summary_text
    assert "llm=True" not in summary_text


def test_slack_web_bridge_omits_llm_execution_details_from_summary(tmp_path: Path):
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    execution_path = tmp_path / "llm-role-execution.json"
    execution_path.write_text(
        json.dumps(
            {
                "roles": {
                    "Analyzer": {"source": "hard_fallback", "fallback_reason": "invalid_llm_response"},
                    "Planner": {"source": "llm", "fallback_reason": None},
                    "Generator": {"source": "recovered_llm", "fallback_reason": None},
                }
            }
        ),
        encoding="utf-8",
    )

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    bridge.post_run_summary(
        run_id="food-run-001",
        current_state="completed",
        pending_approval=None,
        artifacts={
            "llm_role_execution": execution_path,
        },
    )

    summary_text = json.dumps(client.calls[-1]["blocks"], ensure_ascii=False)

    assert "LLM role 실행" not in summary_text
    assert "recovered_llm" not in summary_text
    assert "hard_fallback" not in summary_text


def test_slack_web_bridge_omits_llm_patch_proposal_details_from_summary(tmp_path: Path):
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    execution_path = tmp_path / "llm-patch-proposal-execution.json"
    execution_path.write_text(
        json.dumps(
            {
                "source": "fallback",
                "fallback_reason": "invalid_target_selection",
            }
        ),
        encoding="utf-8",
    )

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    bridge.post_run_summary(
        run_id="food-run-001",
        current_state="completed",
        pending_approval=None,
        artifacts={
            "llm_patch_proposal_execution": execution_path,
        },
    )

    summary_text = json.dumps(client.calls[-1]["blocks"], ensure_ascii=False)

    assert "LLM patch proposal" not in summary_text
    assert "invalid_target_selection" not in summary_text


def test_slack_web_bridge_omits_llm_codebase_details_from_summary(tmp_path: Path):
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    interpretation_path = tmp_path / "llm-codebase-interpretation.json"
    interpretation_path.write_text(
        json.dumps(
            {
                "source": "llm",
                "fallback_reason": None,
                "ranked_candidates": [
                    {"path": "backend/account/handlers.py", "reason": "primary auth entrypoint"},
                ],
            }
        ),
        encoding="utf-8",
    )

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )

    bridge.post_run_summary(
        run_id="food-run-001",
        current_state="completed",
        pending_approval=None,
        artifacts={
            "llm_codebase_interpretation": interpretation_path,
        },
    )

    summary_text = json.dumps(client.calls[-1]["blocks"], ensure_ascii=False)

    assert "LLM codebase 해석" not in summary_text
    assert "backend/account/handlers.py" not in summary_text


def test_slack_web_bridge_omits_llm_usage_from_summary(tmp_path: Path):
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    usage_path = tmp_path / "llm-usage.json"
    usage_path.write_text(
        json.dumps(
            {
                "totals": {
                    "input_tokens": 1200,
                    "output_tokens": 300,
                    "cached_input_tokens": 800,
                    "total_tokens": 1500,
                    "estimated_input_cost_usd": 0.0012,
                    "estimated_output_cost_usd": 0.0018,
                    "estimated_cached_input_cost_usd": 0.0002,
                    "estimated_total_cost_usd": 0.0032,
                },
                "calls": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)

    bridge.post_run_summary(
        run_id="food-run-001",
        current_state="completed",
        pending_approval=None,
        artifacts={"llm_usage": usage_path},
    )

    summary_text = json.dumps(client.calls[-1]["blocks"], ensure_ascii=False)

    assert "LLM 사용량" not in summary_text
    assert "total=1500" not in summary_text
    assert "$0.003200" not in summary_text


def test_slack_web_bridge_includes_runtime_setup_failure_in_final_summary(tmp_path: Path):
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    backend_path = tmp_path / "backend-evaluation.json"
    backend_path.write_text(
        json.dumps(
            {
                "backend_bootstrap": {
                    "bootstrap_attempted": True,
                    "bootstrap_passed": False,
                    "bootstrap_failure_reason": "pip install failed",
                }
            }
        ),
        encoding="utf-8",
    )
    frontend_path = tmp_path / "frontend-build-validation.json"
    frontend_path.write_text(
        json.dumps(
            {
                "bootstrap_failure_stage": "install_environment_failed",
                "bootstrap_failure_reason": "npm install failed",
            }
        ),
        encoding="utf-8",
    )

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_summary(
        run_id="food-run-001",
        current_state="failed",
        pending_approval=None,
        artifacts={
            "backend_evaluation": backend_path,
            "frontend_build_validation": frontend_path,
        },
    )

    summary_text = json.dumps(client.calls[-1]["blocks"], ensure_ascii=False)

    assert "런타임 준비 실패" in summary_text
    assert "pip install failed" in summary_text or "npm install failed" in summary_text


def test_slack_web_bridge_includes_generator_targets_in_message_text():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    event = RunEvent(
        event_type="generation.completed",
        run_id="food-run-001",
        state=RunState.GENERATING,
        payload={"phase": "generation"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Generator",
        claim="Prepared overlay artifact proposal",
        evidence=["proposal ready"],
        confidence=0.88,
        risk="medium",
        next_action="materialize proposed files and patches",
        blocking_issue="none",
        metadata={
            "proposed_files": ["files/backend/chat_auth.py"],
            "proposed_patches": ["patches/frontend_widget_mount.patch"],
        },
    )

    bridge.post_agent_message(event=event, message=message)

    assert "chat_auth.py" in client.calls[-1]["text"]
    assert "생성 결과를 공유합니다." in client.calls[-1]["text"]


def test_slack_web_bridge_defaults_to_channel_conversation_without_thread_ts():
    class FakeWebClient:
        def __init__(self):
            self.calls: list[dict] = []

        def chat_postMessage(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "ts": "1710000000.100"}

    client = FakeWebClient()
    bridge = SlackWebBridge(channel="#onboarding-runs", web_client=client)
    bridge.post_run_root(
        run_id="food-run-001",
        site="food",
        source_root="/workspace/food",
        goal="generate onboarding overlay",
        current_state=RunState.QUEUED,
        approval_status="not_requested",
    )
    event = RunEvent(
        event_type="analysis.completed",
        run_id="food-run-001",
        state=RunState.ANALYZING,
        payload={"phase": "analysis"},
        created_at="2026-03-15T23:00:00+09:00",
    )
    message = AgentMessage(
        role="Analyzer",
        claim="Detected session auth",
        evidence=["session token cookie is read in login flow"],
        confidence=0.91,
        risk="medium",
        next_action="forward auth capability to planner",
        blocking_issue="none",
    )

    bridge.post_agent_message(event=event, message=message)

    assert "thread_ts" not in client.calls[-1]
