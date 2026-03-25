import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.analysis import build_analysis_bundle, build_analysis_snapshot
from chatbot.src.onboarding_v2.analysis import analyzer as analyzer_module
from chatbot.src.onboarding_v2.models.analysis import ContractRecord, VerifiedContracts


@pytest.fixture(autouse=True)
def _disable_onboarding_v2_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ONBOARDING_V2_ENABLE_LLM", "0")


def test_analyzer_builds_food_snapshot():
    source_root = ROOT / "food"
    snapshot = build_analysis_snapshot(site="food", source_root=source_root)

    assert snapshot.repo_profile.backend_framework == "django"
    assert snapshot.repo_profile.frontend_framework == "react"
    assert any(candidate.path.endswith("backend/foodshop/urls.py") for candidate in snapshot.backend_seams.route_registration_points)
    assert any(candidate.path.endswith("frontend/src/App.js") for candidate in snapshot.frontend_seams.app_shell_candidates)
    assert any(candidate.path.endswith("frontend/src/api/api.js") for candidate in snapshot.frontend_seams.api_client_candidates)


def test_analyzer_verifies_bilyeo_flask_routes_and_session_auth():
    bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")

    verified_paths = {record.identifier for record in bundle.verified_contracts.api_endpoints}
    assert "/api/orders/all" in verified_paths
    assert "/api/auth/login" in verified_paths
    assert bundle.snapshot.repo_profile.auth_style == "session_cookie"

    login_record = next(
        record for record in bundle.verified_contracts.api_endpoints if record.identifier == "/api/auth/login"
    )
    assert login_record.details["path"] == "/api/auth/login"
    assert login_record.details["http_method"] == "POST"
    assert login_record.details["source_kind"] == "server_route"


def test_analyzer_rejects_bilyeo_client_server_order_mismatch_but_keeps_server_verified():
    bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")

    verified_paths = {record.identifier for record in bundle.verified_contracts.api_endpoints}
    assert "/api/orders/all" in verified_paths
    assert any(
        claim.identifier == "/api/orders"
        and "does not match verified server route" in claim.reason
        for claim in bundle.rejected_claims
    )


def test_analyzer_canonicalizes_semantic_endpoint_ids_to_flask_paths():
    bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    contracts = VerifiedContracts(
        api_endpoints=[
            ContractRecord(
                identifier="orders_all",
                kind="api_endpoint",
                location="backend/routes/order.py",
                owner="llm",
                details={},
                evidence_refs=["backend/routes/order.py"],
            ),
            ContractRecord(
                identifier="auth_login",
                kind="api_endpoint",
                location="backend/routes/auth.py",
                owner="llm",
                details={},
                evidence_refs=["backend/routes/auth.py"],
            ),
        ]
    )

    verified, rejected, ambiguities = analyzer_module._verify_contracts(
        root=ROOT / "bilyeo",
        framework_profile=bundle.framework_profile,
        candidate_set=bundle.candidate_set,
        contracts=contracts,
    )

    verified_paths = {record.identifier for record in verified.api_endpoints}
    assert "/api/orders/all" in verified_paths
    assert "/api/auth/login" in verified_paths
    assert not rejected
    assert "verified order api endpoint missing" not in ambiguities
