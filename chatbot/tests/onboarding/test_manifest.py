import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.manifest import OverlayManifest, OverlayManifestError


def test_overlay_manifest_parses_valid_payload():
    manifest = OverlayManifest.model_validate(
        {
            "run_id": "food-20260315-001",
            "site": "food",
            "source_root": "/workspace/food",
            "created_at": "2026-03-15T12:00:00+09:00",
            "agent_version": "v1",
            "analysis": {"auth": {"type": "session_cookie"}},
            "generated_files": ["files/backend/chat_auth.py"],
            "patch_targets": ["patches/users_views.patch"],
            "docker": {"compose_override": "files/docker-compose.override.yml"},
            "tests": {"smoke": ["smoke-tests/login.sh"]},
            "status": "generated",
        }
    )

    assert manifest.run_id == "food-20260315-001"
    assert manifest.site == "food"
    assert manifest.status == "generated"


@pytest.mark.parametrize(
    "payload, expected_message",
    [
        (
            {
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "generated",
            },
            "run_id",
        ),
        (
            {
                "run_id": "food-20260315-001",
                "site": "food",
                "source_root": "/workspace/food",
                "created_at": "2026-03-15T12:00:00+09:00",
                "agent_version": "v1",
                "analysis": {},
                "generated_files": [],
                "patch_targets": [],
                "docker": {},
                "tests": {},
                "status": "unknown",
            },
            "status",
        ),
    ],
)
def test_overlay_manifest_rejects_invalid_payload(payload: dict, expected_message: str):
    with pytest.raises(OverlayManifestError, match=expected_message):
        OverlayManifest.from_dict(payload)
