import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.generator_eval import GeneratorEvalFixture, evaluate_generator_proposal


def _fixture() -> GeneratorEvalFixture:
    return GeneratorEvalFixture.model_validate(
        {
            "id": "food-basic",
            "site": "food",
            "input": {
                "analysis": {"framework": {"backend": "django", "frontend": "react"}},
                "recommended_outputs": ["chat_auth", "frontend_patch"],
            },
            "expected": {
                "proposed_files": ["files/backend/chat_auth.py"],
                "proposed_patches": ["patches/frontend_widget_mount.patch"],
            },
            "forbidden": ["food/backend/", "runtime/"],
        }
    )


def test_generator_rubric_reports_missing_extra_and_forbidden_items():
    result = evaluate_generator_proposal(
        _fixture(),
        proposed_files=["files/backend/order_adapter_client.py", "food/backend/users/views.py"],
        proposed_patches=[],
    )

    assert result.passed is False
    assert result.missing_files == ["files/backend/chat_auth.py"]
    assert result.extra_files == [
        "files/backend/order_adapter_client.py",
        "food/backend/users/views.py",
    ]
    assert result.missing_patches == ["patches/frontend_widget_mount.patch"]
    assert result.extra_patches == []
    assert result.forbidden_hits == ["food/backend/users/views.py"]


def test_generator_rubric_passes_when_expected_proposals_match():
    result = evaluate_generator_proposal(
        _fixture(),
        proposed_files=["files/backend/chat_auth.py"],
        proposed_patches=["patches/frontend_widget_mount.patch"],
    )

    assert result.passed is True
    assert result.missing_files == []
    assert result.extra_files == []
    assert result.missing_patches == []
    assert result.extra_patches == []
    assert result.forbidden_hits == []


def test_generator_rubric_returns_category_scores():
    result = evaluate_generator_proposal(
        _fixture(),
        proposed_files=["files/backend/chat_auth.py"],
        proposed_patches=[],
    )

    assert result.score == 0.75
    assert result.checks == {
        "required_files": True,
        "required_patches": False,
        "no_extra_artifacts": True,
        "no_forbidden_hits": True,
    }
