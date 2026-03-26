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
from chatbot.src.onboarding_v2.models.analysis import (
    ContractRecord,
    EvidencePacket,
    VerifiedContracts,
)


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
    assert bundle.snapshot.domain_integration.login_endpoint == "/api/auth/login"

    login_record = next(
        record for record in bundle.verified_contracts.api_endpoints if record.identifier == "/api/auth/login"
    )
    assert login_record.details["path"] == "/api/auth/login"
    assert login_record.details["http_method"] == "POST"
    assert login_record.details["source_kind"] == "server_route"


def test_analyzer_discovers_bilyeo_product_list_route_from_empty_flask_decorator():
    bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")

    verified_paths = {record.identifier for record in bundle.verified_contracts.api_endpoints}

    assert "/api/products" in verified_paths
    assert bundle.snapshot.domain_integration.product_search_endpoint == "/api/products"


def test_analyzer_rejects_bilyeo_client_server_order_mismatch_but_keeps_server_verified():
    bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")

    verified_paths = {record.identifier for record in bundle.verified_contracts.api_endpoints}
    assert "/api/orders/all" in verified_paths
    assert any(
        claim.identifier == "/orders"
        and "does not match verified server route" in claim.reason
        for claim in bundle.rejected_claims
    )


def test_analyzer_does_not_promote_common_login_fallback_without_verified_endpoint():
    assert analyzer_module._resolve_endpoint_path(
        {"/api/orders/": "/api/orders/"},
        preferred=["/api/users/login/", "/api/auth/login"],
        fallbacks=["/api/users/login/", "/api/auth/login"],
    ) is None


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


def test_analyzer_canonicalizes_llm_style_flask_contract_labels():
    bundle = build_analysis_bundle(site="bilyeo", source_root=ROOT / "bilyeo")
    contracts = VerifiedContracts(
        database_entities=[
            ContractRecord(
                identifier="oracle.orders",
                kind="database_entity",
                location="backend/models/__init__.py",
                owner="llm",
                details={},
                evidence_refs=["backend/models/__init__.py"],
            )
        ],
        api_endpoints=[
            ContractRecord(
                identifier="POST /api/auth/login",
                kind="api_endpoint",
                location="backend/routes/auth.py",
                owner="llm",
                details={},
                evidence_refs=["backend/routes/auth.py"],
            ),
            ContractRecord(
                identifier="GET /api/orders/all",
                kind="api_endpoint",
                location="backend/routes/order.py",
                owner="llm",
                details={},
                evidence_refs=["backend/routes/order.py"],
            ),
        ],
        auth_components=[
            ContractRecord(
                identifier="flask_session_auth",
                kind="auth_component",
                location="backend/routes/auth.py",
                owner="llm",
                details={"mechanism": "Flask session cookie"},
                evidence_refs=["backend/routes/auth.py"],
            )
        ],
        tool_targets=[
            ContractRecord(
                identifier="order_management_routes",
                kind="tool_target",
                location="backend/routes/order.py",
                owner="llm",
                details={
                    "capabilities": [
                        "list all orders",
                        "cancel order",
                        "exchange order",
                        "refund order",
                    ]
                },
                evidence_refs=["backend/routes/order.py"],
            )
        ],
    )

    verified, rejected, ambiguities = analyzer_module._verify_contracts(
        root=ROOT / "bilyeo",
        framework_profile=bundle.framework_profile,
        candidate_set=bundle.candidate_set,
        contracts=contracts,
    )

    assert "orders" in {record.identifier for record in verified.database_entities}
    assert "/api/auth/login" in {record.identifier for record in verified.api_endpoints}
    assert "/api/orders/all" in {record.identifier for record in verified.api_endpoints}
    assert "chat_auth_bootstrap" in {record.identifier for record in verified.auth_components}
    assert "order_lookup" in {record.identifier for record in verified.tool_targets}
    assert "order_action" in {record.identifier for record in verified.tool_targets}
    assert not rejected
    assert "verified database entities missing" not in ambiguities
    assert "verified auth bootstrap contract missing" not in ambiguities
    assert "verified order lookup target missing" not in ambiguities
    assert "verified order action target missing" not in ambiguities


def test_analyzer_canonicalizes_food_llm_order_contracts_and_filters_noise():
    bundle = build_analysis_bundle(site="food", source_root=ROOT / "food")
    contracts = VerifiedContracts(
        api_endpoints=[
            ContractRecord(
                identifier="GET|POST /api/orders/",
                kind="backend_endpoint",
                location="backend/orders/urls.py",
                owner="llm",
                details={"handler": "order_list"},
                evidence_refs=["backend/orders/urls.py"],
            ),
            ContractRecord(
                identifier="GET|PUT|PATCH|DELETE /api/orders/<int:order_id>/",
                kind="backend_endpoint",
                location="backend/orders/urls.py",
                owner="llm",
                details={"handler": "order_detail"},
                evidence_refs=["backend/orders/urls.py"],
            ),
            ContractRecord(
                identifier="POST /api/orders/<int:order_id>/actions/",
                kind="backend_endpoint",
                location="backend/orders/urls.py",
                owner="llm",
                details={"handler": "order_action"},
                evidence_refs=["backend/orders/urls.py"],
            ),
        ],
        tool_targets=[
            ContractRecord(
                identifier="orders domain target",
                kind="domain_tool_target",
                location="backend/orders/views.py",
                owner="llm",
                details={
                    "api_surface": [
                        "/api/orders/",
                        "/api/orders/<int:order_id>/",
                        "/api/orders/<int:order_id>/actions/",
                    ]
                },
                evidence_refs=["backend/orders/views.py"],
            ),
            ContractRecord(
                identifier="Seed bootstrap imports: User, Product, Order, SessionToken",
                kind="seed_script",
                location="backend/seed/seed.py",
                owner="llm",
                details={},
                evidence_refs=["backend/seed/seed.py"],
            ),
        ],
    )

    verified, rejected, ambiguities = analyzer_module._verify_contracts(
        root=ROOT / "food",
        framework_profile=bundle.framework_profile,
        candidate_set=bundle.candidate_set,
        contracts=contracts,
    )

    verified_paths = {record.identifier for record in verified.api_endpoints}
    assert "/api/orders/" in verified_paths
    assert "/api/orders/{order_id}/" in verified_paths
    assert "/api/orders/{order_id}/actions/" in verified_paths

    verified_tool_ids = {record.identifier for record in verified.tool_targets}
    assert "order_lookup" in verified_tool_ids
    assert "order_action" in verified_tool_ids
    assert "backend/seed/seed.py" not in {record.location for record in verified.tool_targets}
    assert not any("seed" in record.identifier.lower() for record in verified.tool_targets)


def test_analyzer_discovers_rag_sources_without_manifest(tmp_path: Path):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend" / "src"
    scripts = tmp_path / "scripts"
    docs = tmp_path / "docs"
    backend.mkdir(parents=True)
    frontend.mkdir(parents=True)
    scripts.mkdir()
    docs.mkdir()

    (tmp_path / "site-manifest.json").write_text(
        '{"retrieval":{"faq_policy_source":{"type":"should_not_be_used"}}}',
        encoding="utf-8",
    )
    (backend / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )
    (docs / "returns.md").write_text(
        "# 반품 규정\n반품은 7일 이내 가능합니다.\n",
        encoding="utf-8",
    )
    (scripts / "faq_seed.json").write_text(
        '[{"question":"배송은 얼마나 걸리나요?","answer":"2일"}]',
        encoding="utf-8",
    )
    (scripts / "product_crawling.py").write_text(
        "def crawl():\n    image_url='https://cdn.example.com/item.jpg'\n    return image_url\n",
        encoding="utf-8",
    )
    (frontend / "api.js").write_text(
        "export async function listProducts(){ return fetch('/api/products'); }\n",
        encoding="utf-8",
    )

    bundle = build_analysis_bundle(site="demo-shop", source_root=tmp_path)

    assert bundle.workspace_profile.manifest_path is None
    assert bundle.snapshot.domain_integration.site_id_source == "cli_site_argument"
    assert any(source.path.endswith("faq_seed.json") for source in bundle.rag_sources.faq)
    assert any(source.path.endswith("returns.md") for source in bundle.rag_sources.policy)
    assert any(source.path.endswith("product_crawling.py") for source in bundle.rag_sources.discovery_image)

    image_source = next(
        source for source in bundle.rag_sources.discovery_image if source.path.endswith("product_crawling.py")
    )
    assert image_source.details["loader_candidates"][0] == "public_url_fetch"
    assert image_source.details["access_mode"] == "public_url"
    assert "verified order lookup target missing" in bundle.unresolved_ambiguities
    assert "verified order action target missing" in bundle.unresolved_ambiguities


def test_build_analysis_bundle_merges_llm_contracts_with_deterministic_fallback(monkeypatch):
    def _fake_invoke_structured_stage(*, phase, response_model, fallback_payload, **kwargs):
        del kwargs
        if phase.startswith("contract-extraction"):
            return response_model.model_validate(
                {
                    "database_entities": [],
                    "api_endpoints": [
                        {
                            "identifier": "GET|POST /api/orders/",
                            "kind": "backend_endpoint",
                            "location": "backend/orders/urls.py",
                            "owner": "llm",
                            "details": {"handler": "order_list"},
                            "evidence_refs": ["backend/orders/urls.py"],
                        },
                        {
                            "identifier": "GET|PUT|PATCH|DELETE /api/orders/<int:order_id>/",
                            "kind": "backend_endpoint",
                            "location": "backend/orders/urls.py",
                            "owner": "llm",
                            "details": {"handler": "order_detail"},
                            "evidence_refs": ["backend/orders/urls.py"],
                        },
                        {
                            "identifier": "POST /api/orders/<int:order_id>/actions/",
                            "kind": "backend_endpoint",
                            "location": "backend/orders/urls.py",
                            "owner": "llm",
                            "details": {"handler": "order_action"},
                            "evidence_refs": ["backend/orders/urls.py"],
                        },
                    ],
                    "auth_components": [],
                    "tool_targets": [
                        {
                            "identifier": "orders domain target",
                            "kind": "domain_tool_target",
                            "location": "backend/orders/views.py",
                            "owner": "llm",
                            "details": {
                                "api_surface": [
                                    "/api/orders/",
                                    "/api/orders/<int:order_id>/",
                                    "/api/orders/<int:order_id>/actions/",
                                ]
                            },
                            "evidence_refs": ["backend/orders/views.py"],
                        }
                    ],
                }
            )
        return response_model.model_validate(fallback_payload)

    monkeypatch.setattr(analyzer_module, "invoke_structured_stage", _fake_invoke_structured_stage)

    bundle = build_analysis_bundle(
        site="food",
        source_root=ROOT / "food",
        ambiguity_retry_limit=0,
    )

    assert "chat_auth_bootstrap" in {
        record.identifier for record in bundle.verified_contracts.auth_components
    }
    assert "order_lookup" in {
        record.identifier for record in bundle.verified_contracts.tool_targets
    }
    assert "order_action" in {
        record.identifier for record in bundle.verified_contracts.tool_targets
    }
    assert "/api/orders/{order_id}/actions/" in {
        record.identifier for record in bundle.verified_contracts.api_endpoints
    }


def test_build_analysis_bundle_passes_tool_runtime_to_all_analysis_phases(monkeypatch):
    observed: list[tuple[str, object]] = []

    def _fake_invoke_structured_stage(*, phase, response_model, fallback_payload, tool_runtime=None, **kwargs):
        del kwargs
        observed.append((phase, tool_runtime))
        assert tool_runtime is not None
        list_tool = next(tool for tool in tool_runtime.tools if tool.name == "list_analysis_paths")
        route_inventory = list_tool.invoke({"category": "route_definitions"})
        assert any(path.endswith("backend/foodshop/urls.py") for path in route_inventory["paths"])
        return response_model.model_validate(fallback_payload)

    monkeypatch.setattr(analyzer_module, "invoke_structured_stage", _fake_invoke_structured_stage)

    bundle = build_analysis_bundle(
        site="food",
        source_root=ROOT / "food",
        ambiguity_retry_limit=0,
    )

    assert bundle.snapshot.repo_profile.site == "food"
    assert [phase for phase, _runtime in observed] == [
        "retrieval-plan",
        "read-queue-r0",
        "evidence-reading-r0",
        "contract-extraction-r0",
    ]


def test_analysis_tool_runtime_exposes_only_minimal_surface():
    candidate_set = analyzer_module._harvest_candidates(
        root=ROOT / "food",
        framework_profile=analyzer_module._build_framework_profile(root=ROOT / "food"),
    )
    workspace_profile = analyzer_module._build_workspace_profile(root=ROOT / "food")
    runtime = analyzer_module.build_analysis_tool_runtime(
        root=ROOT / "food",
        workspace_profile=workspace_profile,
        candidate_set=candidate_set,
    )

    assert {tool.name for tool in runtime.tools} == {"list_analysis_paths", "read_analysis_path"}
    read_tool = next(tool for tool in runtime.tools if tool.name == "read_analysis_path")
    result = read_tool.invoke({"path": "../secrets.py"})
    assert result["error"] == "path_not_allowed"


def test_sanitize_evidence_packets_dedupes_same_file_and_kind(tmp_path: Path):
    workspace = tmp_path / "workspace"
    target = workspace / "backend" / "orders" / "views.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def order_list(request):\n    return []\n", encoding="utf-8")

    packets = analyzer_module._sanitize_evidence_packets(
        packets=[
            EvidencePacket(
                packet_id="backend/orders/views.py",
                kind="backend_handler",
                path="backend/orders/views.py",
                summary="llm summary",
                owner="llm",
                evidence_refs=["backend/orders/views.py"],
            )
        ],
        fallback=[
            EvidencePacket(
                packet_id="backend_handler:backend/orders/views.py",
                kind="backend_handler",
                path="backend/orders/views.py",
                summary="fallback summary",
                owner="deterministic",
                evidence_refs=["backend/orders/views.py"],
            )
        ],
        root=workspace,
    )

    assert len(packets) == 1
    assert packets[0].summary == "llm summary"
