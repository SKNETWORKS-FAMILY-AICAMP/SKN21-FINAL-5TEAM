import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.role_runner import LLMRoleRunner, build_llm_role_runner


class FakeLLM:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return type("LLMResponse", (), {"content": self.content})()


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


def test_diagnostician_prompt_requires_retry_budget_and_root_cause_fields():
    fake_llm = FakeLLM(
        """
        {
          "claim": "Failure looks transient",
          "evidence": ["single smoke step failed once"],
          "confidence": 0.76,
          "risk": "medium",
          "next_action": "retry_validation",
          "blocking_issue": "none",
          "metadata": {"should_retry": true, "root_cause_hypothesis": "temporary patch mismatch"}
        }
        """
    )
    runner = LLMRoleRunner(llm_factory=lambda: fake_llm)

    runner.run_role(
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
    assert "metadata.should_retry" in system_message
