import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.role_runner import (
    LLMRoleRunner,
    ReliableLLMRoleRunner,
    RoleRunner,
    build_llm_role_runner,
)


class FakeLLM:
    def __init__(self, content: str, usage_metadata: dict | None = None):
        self.content = content
        self.usage_metadata = usage_metadata or {}
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return type(
            "LLMResponse",
            (),
            {
                "content": self.content,
                "usage_metadata": self.usage_metadata,
                "response_metadata": {
                    "token_usage": {
                        "prompt_tokens": self.usage_metadata.get("input_tokens", 0),
                        "completion_tokens": self.usage_metadata.get("output_tokens", 0),
                        "total_tokens": self.usage_metadata.get("total_tokens", 0),
                        "prompt_tokens_details": {
                            "cached_tokens": self.usage_metadata.get("cached_input_tokens", 0),
                        },
                    }
                },
            },
        )()


def _build_fallback_runner() -> RoleRunner:
    return RoleRunner(
        responders={
            "Analyzer": lambda context: {
                "claim": "대체 분석 결과",
                "evidence": context.get("evidence", []),
                "confidence": 0.5,
                "risk": "medium",
                "next_action": "대체 경로로 계속 진행",
                "blocking_issue": "none",
                "metadata": {},
            }
        }
    )


def test_llm_role_runner_parses_structured_json_response():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Detected Django session auth",
          "evidence": ["session_token cookie is used"],
          "confidence": 0.91,
          "risk": "medium",
          "next_action": "send auth capability to planner",
          "blocking_issue": "none",
          "metadata": {"auth_type": "session_cookie"}
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    message = runner.run_role("Analyzer", {"site": "food", "evidence": ["users/views.py has login"]})

    assert message.role == "Analyzer"
    assert message.claim == "Detected Django session auth"
    assert message.metadata["auth_type"] == "session_cookie"


def test_llm_role_runner_builds_role_specific_prompt():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Need auth and order generation",
          "evidence": ["auth and order endpoints detected"],
          "confidence": 0.82,
          "risk": "medium",
          "next_action": "ask generator for overlay",
          "blocking_issue": "none",
          "metadata": {}
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    runner.run_role("Planner", {"site": "food", "evidence": ["order route exists"]})

    system_message = fake_llm.calls[0][0]
    user_message = fake_llm.calls[0][1]
    assert "Planner" in str(system_message.content)
    assert "JSON" in str(system_message.content)
    assert '"site": "food"' in str(user_message.content)
    assert "capabilities" in str(system_message.content)
    assert "Do not invent routes" in str(system_message.content)
    assert "한국어" in str(system_message.content)


def test_analyzer_prompt_requires_capability_mapping_and_conservative_behavior():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Detected auth and order candidates",
          "evidence": ["login and order routes found"],
          "confidence": 0.74,
          "risk": "medium",
          "next_action": "send capability candidates to planner",
          "blocking_issue": "none",
          "metadata": {"capabilities": ["auth.chat_token_issue", "orders.list"]}
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    runner.run_role("Analyzer", {"site": "food", "evidence": ["login route", "order route"]})

    system_message = str(fake_llm.calls[0][0].content)
    assert "auth.login_state_detection" in system_message
    assert "auth.chat_token_issue" in system_message
    assert "orders.list" in system_message
    assert "If evidence is weak" in system_message
    assert "metadata" in system_message


def test_planner_prompt_requires_priority_and_missing_capabilities():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Auth should be implemented before export",
          "evidence": ["auth capability is incomplete"],
          "confidence": 0.83,
          "risk": "medium",
          "next_action": "prioritize auth and order before frontend patch",
          "blocking_issue": "none",
          "metadata": {"priority_capabilities": ["auth.chat_token_issue", "orders.list"]}
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    runner.run_role("Planner", {"site": "food", "analysis": {"capabilities": ["orders.list"]}})

    system_message = str(fake_llm.calls[0][0].content)
    assert "priority_capabilities" in system_message
    assert "missing_capabilities" in system_message
    assert "Do not propose deployment" in system_message
    assert "runtime copy" in system_message


def test_planner_prompt_requires_strategy_and_wiring_targets():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Use django and react integration strategy",
          "evidence": ["url target and app shell were detected"],
          "confidence": 0.8,
          "risk": "medium",
          "next_action": "generate backend and frontend wiring outputs",
          "blocking_issue": "none",
          "metadata": {
            "priority_capabilities": ["auth.chat_token_issue"],
            "recommended_outputs": ["chat_auth", "frontend_patch"]
          }
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    runner.run_role(
        "Planner",
        {
            "site": "food",
            "analysis": {
                "backend_strategy": "django",
                "frontend_strategy": "react",
                "backend_route_targets": ["backend/shop/urls.py"],
                "frontend_mount_targets": ["frontend/src/App.js"],
            },
        },
    )

    system_message = str(fake_llm.calls[0][0].content)
    assert "backend_strategy" in system_message
    assert "frontend_strategy" in system_message
    assert "backend_route_targets" in system_message
    assert "frontend_mount_targets" in system_message
    assert "tool registry" in system_message


def test_build_llm_role_runner_uses_provider_and_model():
    captured: dict[str, str] = {}

    def fake_make_chat_llm(provider: str, model: str, temperature: float = 0):
        captured["provider"] = provider
        captured["model"] = model
        captured["temperature"] = str(temperature)
        return FakeLLM(
            """
            {
              "claim": "ok",
              "evidence": ["e1"],
              "confidence": 0.8,
              "risk": "low",
              "next_action": "next",
              "blocking_issue": "none",
              "metadata": {}
            }
            """
        )

    runner = build_llm_role_runner(
        provider="openai",
        model="gpt-4o-mini",
        llm_builder=fake_make_chat_llm,
    )
    runner.run_role("Validator", {"passed": True, "evidence": ["smoke ok"]})

    assert captured == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": "0",
    }


def test_generator_prompt_requires_patch_proposal_fields():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Need auth endpoint and frontend mount patch",
          "evidence": ["auth login entrypoint and frontend mount were detected"],
          "confidence": 0.84,
          "risk": "medium",
          "next_action": "apply overlay scaffold generation",
          "blocking_issue": "none",
          "metadata": {
            "proposed_files": ["files/backend/chat_auth.py"],
            "proposed_patches": ["patches/frontend_widget_mount.patch"]
          }
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    runner.run_role(
        "Generator",
        {
            "recommended_outputs": ["chat_auth", "frontend_patch"],
            "analysis": {"frontend_mount_points": ["frontend/src/App.js"]},
        },
    )

    system_message = str(fake_llm.calls[0][0].content)
    assert "proposed_files" in system_message
    assert "proposed_patches" in system_message
    assert "Do not output full code" in system_message
    assert "overlay" in system_message


def test_validator_prompt_requires_step_level_failure_assessment():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Validation found one failing smoke step",
          "evidence": ["order_api.sh returned 1"],
          "confidence": 0.9,
          "risk": "high",
          "next_action": "send failure to diagnostician",
          "blocking_issue": "smoke failure",
          "metadata": {"failed_steps": ["order_api.sh"]}
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    runner.run_role("Validator", {"smoke_results": [{"step": "order_api.sh", "returncode": 1}]})

    system_message = str(fake_llm.calls[0][0].content)
    assert "failed_steps" in system_message
    assert "approval recommendation" in system_message
    assert "Do not claim success" in system_message


def test_diagnostician_recovery_prompt_requires_retry_budget_and_root_cause_fields():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Failure looks transient",
          "evidence": ["single smoke step failed once"],
          "confidence": 0.76,
          "risk": "medium",
          "next_action": "retry_validation",
          "blocking_issue": "none",
          "metadata": {
            "classification": "response_schema_mismatch",
            "should_retry": true,
            "root_cause_hypothesis": "temporary patch mismatch",
            "proposed_fix": "flatten access_token export",
            "failure_signature": "response_schema_mismatch:chat-auth-token"
          }
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    message = runner.run_role(
        "Diagnostician",
        {
            "retry_count": 1,
            "retry_budget": 3,
            "failure_signature": "smoke:order_api.sh:1",
        },
    )

    system_message = str(fake_llm.calls[0][0].content)
    assert "root_cause_hypothesis" in system_message
    assert "proposed_fix" in system_message
    assert "retry budget" in system_message
    assert "classification" in system_message
    assert "metadata.should_retry" in system_message
    assert message.metadata["classification"] == "response_schema_mismatch"
    assert message.metadata["should_retry"] is True
    assert message.metadata["proposed_fix"] == "flatten access_token export"


def test_reliable_llm_role_runner_prefers_llm_output_when_valid():
    fake_llm = FakeLLM(
        """
        {
          "claim": "llm analyzer",
          "evidence": ["e1"],
          "confidence": 0.9,
          "risk": "low",
          "next_action": "next",
          "blocking_issue": "none",
          "metadata": {}
        }
        """
    )
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm),
        fallback_runner=_build_fallback_runner(),
    )

    message = runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    execution = runner.execution_log["Analyzer"]

    assert message.claim == "llm analyzer"
    assert execution["source"] == "llm"
    assert execution["fallback_reason"] is None


def test_reliable_llm_role_runner_falls_back_on_invalid_json():
    fake_llm = FakeLLM("not-json")
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm),
        fallback_runner=_build_fallback_runner(),
    )

    message = runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    execution = runner.execution_log["Analyzer"]

    assert message.claim == "대체 분석 결과"
    assert execution["source"] == "hard_fallback"
    assert execution["fallback_reason"] == "invalid_llm_response"


def test_reliable_llm_role_runner_falls_back_on_missing_required_field():
    fake_llm = FakeLLM(
        """
        {
          "claim": "broken payload",
          "evidence": ["e1"],
          "confidence": 0.9,
          "risk": "low",
          "blocking_issue": "none",
          "metadata": {}
        }
        """
    )
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm),
        fallback_runner=_build_fallback_runner(),
    )

    message = runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    execution = runner.execution_log["Analyzer"]

    assert message.claim == "대체 분석 결과"
    assert execution["source"] == "hard_fallback"
    assert execution["fallback_reason"] == "invalid_llm_payload"


def test_reliable_llm_role_runner_can_write_llm_debug_log(tmp_path: Path):
    fake_llm = FakeLLM("not-json")
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm),
        fallback_runner=_build_fallback_runner(),
    )

    runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    reports_root = tmp_path / "reports"
    runner.write_debug_artifacts(reports_root)

    payload = json.loads((reports_root / "llm-debug" / "Analyzer.json").read_text(encoding="utf-8"))

    assert payload["status"] == "hard_fallback"
    assert payload["fallback_reason"] == "invalid_llm_response"
    assert "not-json" in payload["raw_response"]


def test_llm_role_runner_normalizes_nullable_and_scalar_fields():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Detected Django session auth",
          "evidence": "session_token cookie is used",
          "confidence": "0.91",
          "risk": "Medium",
          "next_action": "send auth capability to planner",
          "blocking_issue": null,
          "metadata": null
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    message = runner.run_role("Analyzer", {"site": "food", "evidence": ["users/views.py has login"]})

    assert message.claim == "Detected Django session auth"
    assert message.evidence == ["session_token cookie is used"]
    assert message.confidence == 0.91
    assert message.risk == "medium"
    assert message.blocking_issue == ""
    assert message.metadata == {}


def test_reliable_llm_role_runner_marks_recovered_llm_for_normalizable_payload():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Detected auth candidate",
          "evidence": "users/views.py has login",
          "confidence": "0.84",
          "risk": "LOW",
          "next_action": "continue",
          "blocking_issue": null,
          "metadata": null
        }
        """
    )
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm),
        fallback_runner=_build_fallback_runner(),
    )

    message = runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    execution = runner.execution_log["Analyzer"]

    assert message.claim == "Detected auth candidate"
    assert message.blocking_issue == ""
    assert execution["source"] == "recovered_llm"
    assert execution["fallback_reason"] is None
    assert execution["recovery_reason"] == "agent_payload_normalized"


def test_llm_role_runner_normalizes_confidence_string_with_annotation():
    fake_llm = FakeLLM(
        """
        {
          "claim": "overlay artifact proposal ready",
          "evidence": ["recommended outputs were provided"],
          "confidence": "0.82 (중간-높음)",
          "risk": "medium",
          "next_action": "continue",
          "blocking_issue": "none",
          "metadata": {
            "proposed_files": ["files/backend/chat_auth.py"],
            "proposed_patches": ["patches/frontend_widget_mount.patch"]
          }
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    message = runner.run_role(
        "Generator",
        {"recommended_outputs": ["chat_auth", "frontend_patch"]},
    )

    assert message.confidence == 0.82


def test_reliable_llm_role_runner_recovered_llm_for_generator_confidence_annotation():
    fake_llm = FakeLLM(
        """
        {
          "claim": "overlay artifact proposal ready",
          "evidence": ["recommended outputs were provided"],
          "confidence": "0.82 (중간-높음)",
          "risk": "medium",
          "next_action": "continue",
          "blocking_issue": "none",
          "metadata": {
            "proposed_files": ["files/backend/chat_auth.py"],
            "proposed_patches": ["patches/frontend_widget_mount.patch"]
          }
        }
        """
    )
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm),
        fallback_runner=_build_fallback_runner(),
    )

    message = runner.run_role(
        "Generator",
        {"recommended_outputs": ["chat_auth", "frontend_patch"]},
    )
    execution = runner.execution_log["Generator"]

    assert message.confidence == 0.82
    assert execution["source"] == "recovered_llm"
    assert execution["recovery_reason"] == "agent_payload_normalized"


def test_reliable_llm_role_runner_recovered_llm_for_generator_percentage_confidence():
    fake_llm = FakeLLM(
        """
        {
          "claim": "overlay artifact proposal ready",
          "evidence": ["recommended outputs were provided"],
          "confidence": "86%",
          "risk": "medium",
          "next_action": "continue",
          "blocking_issue": "none",
          "metadata": {
            "proposed_files": ["files/backend/chat_auth.py"],
            "proposed_patches": ["patches/frontend_widget_mount.patch"]
          }
        }
        """
    )
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm),
        fallback_runner=_build_fallback_runner(),
    )

    message = runner.run_role(
        "Generator",
        {"recommended_outputs": ["chat_auth", "frontend_patch"]},
    )
    execution = runner.execution_log["Generator"]

    assert message.confidence == 0.86
    assert execution["source"] == "recovered_llm"
    assert execution["recovery_reason"] == "agent_payload_normalized"


def test_reliable_llm_role_runner_recovered_llm_uses_hard_fallback_for_irrecoverable_payload():
    fake_llm = FakeLLM(
        """
        {
          "claim": "broken payload",
          "evidence": ["e1"],
          "confidence": 0.9,
          "risk": "low",
          "blocking_issue": "none",
          "metadata": {}
        }
        """
    )
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm),
        fallback_runner=_build_fallback_runner(),
    )

    message = runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    execution = runner.execution_log["Analyzer"]

    assert message.claim == "대체 분석 결과"
    assert execution["source"] == "hard_fallback"
    assert execution["fallback_reason"] == "invalid_llm_payload"


def test_generator_prompt_requires_decimal_confidence_and_string_actions():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Need auth endpoint and frontend mount patch",
          "evidence": ["auth login entrypoint and frontend mount were detected"],
          "confidence": 0.84,
          "risk": "medium",
          "next_action": "apply overlay scaffold generation",
          "blocking_issue": "none",
          "metadata": {
            "proposed_files": ["files/backend/chat_auth.py"],
            "proposed_patches": ["patches/frontend_widget_mount.patch"]
          }
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    runner.run_role(
        "Generator",
        {
            "recommended_outputs": ["chat_auth", "frontend_patch"],
            "analysis": {"frontend_mount_points": ["frontend/src/App.js"]},
        },
    )

    system_message = str(fake_llm.calls[0][0].content)

    assert "confidence must be a JSON number between 0 and 1" in system_message
    assert "Do not return percentages" in system_message
    assert "next_action must be a single string" in system_message


def test_llm_role_runner_normalizes_sequence_fields_to_strings():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Detected auth candidate",
          "evidence": ["users/views.py has login"],
          "confidence": 0.84,
          "risk": ["Medium", "csrf review needed"],
          "next_action": ["inspect users/urls.py", "inspect App.js"],
          "blocking_issue": null,
          "metadata": {}
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    message = runner.run_role("Analyzer", {"evidence": ["users/views.py"]})

    assert message.risk == "medium; csrf review needed"
    assert message.next_action == "inspect users/urls.py; inspect App.js"


def test_reliable_llm_role_runner_writes_llm_usage_report(tmp_path: Path):
    fake_llm = FakeLLM(
        """
        {
          "claim": "llm analyzer",
          "evidence": ["e1"],
          "confidence": 0.9,
          "risk": "low",
          "next_action": "next",
          "blocking_issue": "none",
          "metadata": {}
        }
        """,
        usage_metadata={
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "cached_input_tokens": 80,
        },
    )
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm, provider="openai", model="gpt-4o-mini"),
        fallback_runner=_build_fallback_runner(),
    )

    runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    reports_root = tmp_path / "reports"
    runner.write_debug_artifacts(reports_root)

    usage_payload = json.loads((reports_root / "llm-usage.json").read_text(encoding="utf-8"))

    assert usage_payload["totals"]["input_tokens"] == 120
    assert usage_payload["totals"]["output_tokens"] == 30
    assert usage_payload["totals"]["cached_input_tokens"] == 80
    assert usage_payload["totals"]["estimated_total_cost_usd"] == 0.00003
    assert usage_payload["calls"][0]["component"] == "role:Analyzer"
    assert usage_payload["calls"][0]["model"] == "gpt-4o-mini"


def test_reliable_llm_role_runner_writes_generation_log_entries(tmp_path: Path):
    fake_llm = FakeLLM("not-json")
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm, provider="openai", model="gpt-4o-mini"),
        fallback_runner=_build_fallback_runner(),
    )

    runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    reports_root = tmp_path / "reports"
    runner.write_debug_artifacts(reports_root)

    log_text = (reports_root / "generation.log").read_text(encoding="utf-8")

    assert "role_completed" in log_text
    assert "role=Analyzer" in log_text
    assert "source=hard_fallback" in log_text
    assert "fallback_reason=invalid_llm_response" in log_text


def test_reliable_llm_role_runner_writes_canonical_events(tmp_path: Path):
    fake_llm = FakeLLM("not-json")
    runner = ReliableLLMRoleRunner(
        llm_runner=LLMRoleRunner(llm_factory=lambda: fake_llm, provider="openai", model="gpt-4o-mini"),
        fallback_runner=_build_fallback_runner(),
    )

    runner.run_role("Analyzer", {"evidence": ["users/views.py"]})
    reports_root = tmp_path / "reports"
    runner.write_debug_artifacts(reports_root)

    trace_lines = [
        json.loads(line)
        for line in (reports_root / "execution-trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    events = {(item["component"], item["event"]) for item in trace_lines}
    assert ("role_runner", "llm_call_started") in events
    assert ("role_runner", "hard_fallback_used") in events
    assert ("role_runner", "artifact_written") in events

    artifact_events = [
        item
        for item in trace_lines
        if item["component"] == "role_runner" and item["event"] == "artifact_written"
    ]
    assert artifact_events[-1]["debug_artifact_path"].endswith("llm-debug/Analyzer.json")
