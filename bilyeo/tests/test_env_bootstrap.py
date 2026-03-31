import importlib.util
import sys
from pathlib import Path


def _load_temp_config(tmp_path: Path):
    source_backend = Path(__file__).resolve().parents[1] / "backend"
    backend_root = tmp_path / "backend"
    backend_root.mkdir(parents=True)
    (backend_root / "config.py").write_text(
        (source_backend / "config.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    env_bootstrap_path = source_backend / "env_bootstrap.py"
    if env_bootstrap_path.exists():
        (backend_root / "env_bootstrap.py").write_text(
            env_bootstrap_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    sys.modules.pop("env_bootstrap", None)
    sys.path.insert(0, str(backend_root))
    try:
        spec = importlib.util.spec_from_file_location("temp_bilyeo_config", backend_root / "config.py")
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(backend_root))


def test_config_loads_host_root_dotenv(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text(
        "ORACLE_HOST=dotenv-host\nORACLE_PORT=1522\nORACLE_SERVICE_NAME=dotenvsvc\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ORACLE_HOST", raising=False)
    monkeypatch.delenv("ORACLE_PORT", raising=False)
    monkeypatch.delenv("ORACLE_SERVICE_NAME", raising=False)

    module = _load_temp_config(tmp_path)

    assert module.ORACLE_HOST == "dotenv-host"
    assert module.ORACLE_PORT == "1522"
    assert module.ORACLE_SERVICE_NAME == "dotenvsvc"
    assert module.ORACLE_DSN == "dotenv-host:1522/dotenvsvc"


def test_config_preserves_legacy_oracle_defaults_when_env_is_missing(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("ORACLE_HOST", raising=False)
    monkeypatch.delenv("ORACLE_PORT", raising=False)
    monkeypatch.delenv("ORACLE_SERVICE_NAME", raising=False)

    module = _load_temp_config(tmp_path)

    assert module.ORACLE_HOST == "DESKTOP-IMG07LN"
    assert module.ORACLE_PORT == "1521"
    assert module.ORACLE_SERVICE_NAME == "freepdb1"
    assert module.ORACLE_DSN == "DESKTOP-IMG07LN:1521/freepdb1"
