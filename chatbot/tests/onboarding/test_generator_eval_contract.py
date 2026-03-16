import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.generator_eval import (
    GeneratorEvalFixture,
    load_generator_eval_fixture,
)


def test_generator_eval_fixture_validates_required_fields(tmp_path: Path):
    fixture_path = tmp_path / "food-basic.json"
    fixture_path.write_text(
        json.dumps(
            {
                "id": "food-basic",
                "site": "food",
                "input": {
                    "analysis": {"framework": {"backend": "django"}},
                    "recommended_outputs": ["chat_auth", "frontend_patch"],
                },
                "expected": {
                    "proposed_files": ["files/backend/chat_auth.py"],
                    "proposed_patches": ["patches/frontend_widget_mount.patch"],
                },
                "forbidden": ["food/backend/"],
                "notes": "baseline food case",
            }
        ),
        encoding="utf-8",
    )

    fixture = load_generator_eval_fixture(fixture_path)

    assert isinstance(fixture, GeneratorEvalFixture)
    assert fixture.id == "food-basic"
    assert fixture.expected.proposed_files == ["files/backend/chat_auth.py"]
    assert fixture.expected.proposed_patches == ["patches/frontend_widget_mount.patch"]


def test_generator_eval_fixture_rejects_invalid_expected_shape():
    with pytest.raises(ValidationError):
        GeneratorEvalFixture.model_validate(
            {
                "id": "bad-case",
                "site": "food",
                "input": {
                    "analysis": {"framework": {"backend": "django"}},
                    "recommended_outputs": ["chat_auth"],
                },
                "expected": {
                    "proposed_files": "files/backend/chat_auth.py",
                    "proposed_patches": [],
                },
                "forbidden": [],
            }
        )
