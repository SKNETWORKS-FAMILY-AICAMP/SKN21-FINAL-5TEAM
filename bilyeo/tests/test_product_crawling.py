from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime
from pathlib import Path


def _load_product_crawling_module(monkeypatch):
    source_path = Path(__file__).resolve().parents[1] / "scripts" / "product_crawling.py"

    env_bootstrap = types.ModuleType("env_bootstrap")
    env_bootstrap.ensure_backend_env_loaded = lambda: None
    monkeypatch.setitem(sys.modules, "env_bootstrap", env_bootstrap)

    models = types.ModuleType("models")
    models.get_connection = lambda: None
    monkeypatch.setitem(sys.modules, "models", models)

    oracledb = types.ModuleType("oracledb")
    oracledb.DB_TYPE_CLOB = object()
    monkeypatch.setitem(sys.modules, "oracledb", oracledb)

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "boto3", boto3)

    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: None
    sync_api.Page = object
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

    playwright_stealth = types.ModuleType("playwright_stealth")

    class _Stealth:
        def apply_stealth_sync(self, page):
            del page

    playwright_stealth.Stealth = _Stealth
    monkeypatch.setitem(sys.modules, "playwright_stealth", playwright_stealth)

    spec = importlib.util.spec_from_file_location("test_bilyeo_product_crawling", source_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_seed_module(monkeypatch):
    source_path = Path(__file__).resolve().parents[1] / "scripts" / "seed.py"

    env_bootstrap = types.ModuleType("env_bootstrap")
    env_bootstrap.ensure_backend_env_loaded = lambda: None
    monkeypatch.setitem(sys.modules, "env_bootstrap", env_bootstrap)

    models = types.ModuleType("models")
    models.get_connection = lambda: None
    models.init_db = lambda: None
    monkeypatch.setitem(sys.modules, "models", models)

    faq_crawling = types.ModuleType("faq_crawling")
    faq_crawling.main = lambda: []
    monkeypatch.setitem(sys.modules, "faq_crawling", faq_crawling)

    product_crawling = types.ModuleType("product_crawling")
    product_crawling.main = lambda: {}
    monkeypatch.setitem(sys.modules, "product_crawling", product_crawling)

    werkzeug = types.ModuleType("werkzeug")
    security = types.ModuleType("werkzeug.security")
    security.generate_password_hash = lambda value: f"hashed:{value}"
    monkeypatch.setitem(sys.modules, "werkzeug", werkzeug)
    monkeypatch.setitem(sys.modules, "werkzeug.security", security)

    spec = importlib.util.spec_from_file_location("test_bilyeo_seed", source_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_crawled_products_writes_latest_and_timestamped_snapshot(tmp_path: Path, monkeypatch):
    module = _load_product_crawling_module(monkeypatch)
    captured_at = datetime(2026, 3, 30, 12, 34, 56)

    result = module.export_crawled_products(
        [
            {
                "name": "테스트 상품",
                "brand": "테스트 브랜드",
                "price": 15000,
                "description": "보습 크림",
                "category": "크림",
                "product_info": {"review": "촉촉해요"},
            }
        ],
        export_dir=tmp_path,
        captured_at=captured_at,
    )

    latest_path = tmp_path / "latest-products.json"
    snapshot_path = tmp_path / "products-20260330-123456.json"

    assert result["latest_path"] == str(latest_path)
    assert result["snapshot_path"] == str(snapshot_path)
    assert result["product_count"] == 1
    assert latest_path.exists()
    assert snapshot_path.exists()

    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert payload["site"] == "bilyeo"
    assert payload["captured_at"] == "2026-03-30T12:34:56"
    assert payload["product_count"] == 1
    assert payload["products"][0]["price"] == 15000
    assert payload["products"][0]["product_info"]["review"] == "촉촉해요"


def test_product_crawling_defaults_to_full_detail_crawl(monkeypatch):
    monkeypatch.delenv("BILYEO_FAST_SEED", raising=False)

    module = _load_product_crawling_module(monkeypatch)

    assert module.FAST_SEED is False


def test_seed_run_crawling_surfaces_product_export_metadata(monkeypatch):
    module = _load_seed_module(monkeypatch)
    events: list[str] = []

    monkeypatch.setattr(module, "faq_crawling_main", lambda: events.append("faq"))
    monkeypatch.setattr(
        module,
        "product_crawling_main",
        lambda: {
            "product_count": 3,
            "latest_path": "/tmp/latest-products.json",
            "snapshot_path": "/tmp/products-20260330-123456.json",
        },
    )

    result = module.run_crawling()

    assert events == ["faq"]
    assert result["product_count"] == 3
    assert result["latest_path"] == "/tmp/latest-products.json"
    assert result["snapshot_path"] == "/tmp/products-20260330-123456.json"


def test_seed_db_does_not_trigger_crawling(monkeypatch):
    module = _load_seed_module(monkeypatch)
    events: list[str] = []

    monkeypatch.setattr(module, "run_crawling", lambda: events.append("crawl"))

    class _Cursor:
        def execute(self, query, params=None):
            if "SELECT COUNT(*) FROM orders" in query:
                self._fetchone = (1,)
            elif "SELECT user_id, email FROM users ORDER BY user_id" in query:
                self._fetchall = [(1, "test@example.com")]
            elif "SELECT product_id, name, price, category FROM products" in query:
                self._fetchall = [(1, "상품", 1000, "스킨케어")]

        def fetchone(self):
            return self._fetchone

        def fetchall(self):
            return self._fetchall

        def close(self):
            return None

    class _Conn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(module, "get_connection", lambda: _Conn())
    monkeypatch.setattr(module, "init_db", lambda: None)

    module.seed_db()

    assert events == []


def test_seed_db_with_crawling_triggers_crawlers(monkeypatch):
    module = _load_seed_module(monkeypatch)
    events: list[str] = []

    monkeypatch.setattr(module, "run_crawling", lambda: events.append("crawl"))

    class _Cursor:
        def execute(self, query, params=None):
            if "SELECT COUNT(*) FROM orders" in query:
                self._fetchone = (1,)
            elif "SELECT user_id, email FROM users ORDER BY user_id" in query:
                self._fetchall = [(1, "test@example.com")]
            elif "SELECT product_id, name, price, category FROM products" in query:
                self._fetchall = [(1, "상품", 1000, "스킨케어")]

        def fetchone(self):
            return self._fetchone

        def fetchall(self):
            return self._fetchall

        def close(self):
            return None

    class _Conn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(module, "get_connection", lambda: _Conn())
    monkeypatch.setattr(module, "init_db", lambda: None)

    module.seed_db(with_crawling=True)

    assert events == ["crawl"]


def test_download_image_uses_defined_local_image_directory(tmp_path: Path, monkeypatch):
    module = _load_product_crawling_module(monkeypatch)

    assert hasattr(module, "IMAGE_SAVE_DIR")
    monkeypatch.setattr(module, "IMAGE_SAVE_DIR", str(tmp_path / "images"))

    class _Response:
        def read(self):
            return b"image-bytes"

    monkeypatch.setattr(module.urllib.request, "Request", lambda url, headers=None: (url, headers))
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda req, timeout=15: _Response())

    assert module.download_image("https://example.com/sample.jpg", "sample.jpg") is True
    assert (tmp_path / "images" / "sample.jpg").read_bytes() == b"image-bytes"
