import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.generator_eval import load_generator_eval_fixture


def test_generator_golden_fixtures_validate_against_contract():
    fixture_dir = Path(__file__).resolve().parent / "goldens" / "generator"
    fixture_paths = sorted(fixture_dir.glob("*.json"))

    assert len(fixture_paths) >= 6

    fixture_ids = []
    for fixture_path in fixture_paths:
        fixture = load_generator_eval_fixture(fixture_path)
        fixture_ids.append(fixture.id)

    assert "food-auth-and-frontend" in fixture_ids
    assert "bilyeo-basic" in fixture_ids
    assert "ecommerce-basic" in fixture_ids
    assert "django-template-only" in fixture_ids
    assert "fastapi-react-token-auth" in fixture_ids
    assert "spring-thymeleaf-basic" in fixture_ids
