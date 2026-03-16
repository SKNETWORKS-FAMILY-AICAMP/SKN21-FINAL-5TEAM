import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ecommerce.backend.app import main as backend_main


def test_should_preload_heavy_models_once_per_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(backend_main, "_MODEL_PRELOAD_MARKER", tmp_path / "marker.flag", raising=False)

    assert backend_main._should_preload_heavy_models_once_per_reload_session() is True
    assert backend_main._should_preload_heavy_models_once_per_reload_session() is True
