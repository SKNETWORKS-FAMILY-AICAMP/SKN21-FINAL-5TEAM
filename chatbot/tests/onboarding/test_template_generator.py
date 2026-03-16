import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.template_generator import generate_chat_auth_template


def test_generate_chat_auth_template_for_food_site_creates_python_file(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    reports_root = run_root / "reports"
    files_root = run_root / "files"
    reports_root.mkdir(parents=True)
    files_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "food-run-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "auth": {
                        "login_entrypoints": ["backend/users/views.py:login"],
                        "me_entrypoints": ["backend/users/views.py:me"],
                    }
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_chat_auth_template(run_root)

    assert output_path == run_root / "files" / "backend" / "chat_auth.py"
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "chat_auth_token" in content
    assert "site-a" in content
    assert "issue_chat_token" in content
    assert 'request.COOKIES.get("session_token")' in content
    assert "SessionToken.objects.select_related" in content
    assert '"authenticated": False' in content


def test_generate_chat_auth_template_for_bilyeo_site_uses_site_b(tmp_path: Path):
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "bilyeo-run-001",
                "site": "bilyeo",
                "source_root": "/workspace/bilyeo",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {"auth": {"login_entrypoints": ["backend/routes/auth.py:login"], "me_entrypoints": []}},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_chat_auth_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert "site-b" in content
    assert 'session.get("user_id")' in content
    assert 'session.get("email")' in content
    assert "issue_chat_token" in content


def test_generate_chat_auth_template_for_ecommerce_site_uses_access_token_cookie(tmp_path: Path):
    run_root = tmp_path / "generated" / "ecommerce" / "ecommerce-run-001"
    run_root.mkdir(parents=True)

    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "ecommerce-run-001",
                "site": "ecommerce",
                "source_root": "/workspace/ecommerce",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "test-v1",
                "analysis": {
                    "auth": {
                        "login_entrypoints": ["backend/app/router/users/router.py:login"],
                        "me_entrypoints": ["backend/app/router/users/router.py:me"],
                    }
                },
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = generate_chat_auth_template(run_root)

    content = output_path.read_text(encoding="utf-8")
    assert "site-c" in content
    assert 'request.cookies.get("access_token")' in content
    assert "crud.get_user_by_email" not in content
    assert "get_current_user" not in content
