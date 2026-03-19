import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.run_generator import generate_run_bundle


def test_generate_run_bundle_creates_manifest_from_analysis(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "products").mkdir(parents=True)
    (source_root / "backend" / "orders").mkdir(parents=True)
    (source_root / "frontend" / "src").mkdir(parents=True)

    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )
    (source_root / "backend" / "products" / "urls.py").write_text(
        'path("api/products/", include("products.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "backend" / "orders" / "urls.py").write_text(
        'path("api/orders/", include("orders.urls"))\n',
        encoding="utf-8",
    )
    (source_root / "frontend" / "src" / "App.js").write_text(
        "function App() { return <Chatbot />; }\n",
        encoding="utf-8",
    )

    run_root = generate_run_bundle(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        run_id="food-run-001",
        agent_version="test-v1",
    )

    manifest_path = run_root / "manifest.json"
    assert manifest_path.exists()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "food-run-001"
    assert payload["site"] == "food"
    assert payload["agent_version"] == "test-v1"
    assert payload["analysis"]["auth"]["login_entrypoints"] == ["backend/users/views.py:login"]
    assert payload["analysis"]["product_api"] == ["/api/products/"]
    assert payload["analysis"]["backend_strategy"] == "django"
    assert payload["analysis"]["frontend_strategy"] == "react"
    assert "frontend/src/App.js" in payload["analysis"]["frontend_mount_targets"]
    assert payload["status"] == "generated"


def test_generate_run_bundle_persists_explicit_onboarding_credentials(tmp_path: Path):
    source_root = tmp_path / "food"
    generated_root = tmp_path / "generated"

    (source_root / "backend" / "users").mkdir(parents=True)
    (source_root / "backend" / "users" / "views.py").write_text(
        "def login(request):\n    return None\n\ndef me(request):\n    return None\n",
        encoding="utf-8",
    )

    run_root = generate_run_bundle(
        site="food",
        source_root=source_root,
        generated_root=generated_root,
        run_id="food-run-credentials",
        agent_version="test-v1",
        onboarding_credentials={"username": "demo", "password": "secret"},
    )

    payload = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert payload["credentials"] == {"username": "demo", "password": "secret"}
