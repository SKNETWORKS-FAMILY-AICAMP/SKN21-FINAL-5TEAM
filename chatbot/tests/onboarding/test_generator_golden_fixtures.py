import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.generator_eval import load_generator_eval_fixture
from chatbot.src.onboarding.recovery_planner import build_recovery_plan


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


def test_food_and_bilyeo_contract_regression_fixtures_capture_strategy_shape():
    fixture_root = Path(__file__).resolve().parent / "fixtures"
    food_contract = json.loads((fixture_root / "food_chat_auth_contract.json").read_text(encoding="utf-8"))
    bilyeo_contract = json.loads((fixture_root / "bilyeo_chat_auth_contract.json").read_text(encoding="utf-8"))

    assert food_contract["backend"]["framework"] == "django"
    assert food_contract["backend"]["route_registration_points"] == ["backend/foodshop/urls.py"]
    assert food_contract["frontend"]["framework"] == "react"
    assert food_contract["frontend"]["widget_mount_points"] == ["frontend/src/App.js"]

    assert bilyeo_contract["backend"]["framework"] == "flask"
    assert bilyeo_contract["backend"]["route_registration_points"] == ["backend/app.py"]
    assert bilyeo_contract["frontend"]["framework"] == "vue"
    assert bilyeo_contract["frontend"]["widget_mount_points"] == ["frontend/src/App.vue"]


def test_food_failure_regression_fixtures_classify_and_repair():
    fixture_root = Path(__file__).resolve().parent / "fixtures"
    food_run_003 = json.loads((fixture_root / "food_run_003_failure.json").read_text(encoding="utf-8"))
    food_run_004 = json.loads((fixture_root / "food_run_004_failure.json").read_text(encoding="utf-8"))

    plan_003 = build_recovery_plan(food_run_003)
    plan_004 = build_recovery_plan(food_run_004)

    assert plan_003["classification"] == "missing_import_target"
    assert plan_003["repair_actions"] == [
        {
            "action": "create_chat_auth_module",
            "target_path": "backend/chat_auth.py",
            "framework": "django",
        }
    ]
    assert plan_004["classification"] == "response_schema_mismatch"
    assert plan_004["should_retry"] is True
