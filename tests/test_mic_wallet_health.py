"""C-360 / C-379: MIC wallet database URL resolution and health."""

import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
MIC_MAIN = REPO_ROOT / "mic-wallet" / "app" / "main.py"
MODULE_NAME = "mic_wallet_main_health_test"


def _load_mic_app(*, fresh: bool = True):
    if fresh and MODULE_NAME in sys.modules:
        del sys.modules[MODULE_NAME]
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MIC_MAIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def test_mic_wallet_health_reports_write_probe(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/mic_wallet.db")
    app = _load_mic_app().app
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "mobius-mic-wallet"
    assert payload["db_ok"] is True
    assert payload["db_write_ok"] is True
    assert payload["db_connected"] is True
    assert payload["disk_mounted"] is False
    assert payload["data_dir"] == "/var/lib/mic-wallet"


def test_resolve_database_url_fail_closed_when_disk_mount_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIC_WALLET_ALLOW_EPHEMERAL", raising=False)

    def _no_disk(path: str) -> bool:
        return False

    monkeypatch.setattr("os.path.isdir", _no_disk)
    module = _load_mic_app()
    assert module.resolve_database_url() == "sqlite:////var/lib/mic-wallet/mic_wallet.db"


def test_resolve_database_url_allows_ephemeral_only_when_flag_set(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MIC_WALLET_ALLOW_EPHEMERAL", "1")

    def _no_disk(path: str) -> bool:
        return False

    monkeypatch.setattr("os.path.isdir", _no_disk)
    module = _load_mic_app()
    assert module.resolve_database_url() == "sqlite:///./mic_wallet.db"


def test_resolve_database_url_uses_disk_sqlite_when_mounted(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def _disk_only(path: str) -> bool:
        return path == "/var/lib/mic-wallet"

    monkeypatch.setattr("os.path.isdir", _disk_only)
    module = _load_mic_app()
    assert module.resolve_database_url() == "sqlite:////var/lib/mic-wallet/mic_wallet.db"


def test_resolve_database_url_honors_mic_wallet_data_dir(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MIC_WALLET_DATA_DIR", "/data/custom-wallet")

    def _custom_disk(path: str) -> bool:
        return path == "/data/custom-wallet"

    monkeypatch.setattr("os.path.isdir", _custom_disk)
    module = _load_mic_app()
    assert module.resolve_database_url() == "sqlite:////data/custom-wallet/mic_wallet.db"


def test_resolve_database_url_explicit_disk_sqlite_fail_closed_without_mount(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "sqlite:////var/lib/mic-wallet/mic_wallet.db",
    )
    monkeypatch.delenv("MIC_WALLET_ALLOW_EPHEMERAL", raising=False)

    def _no_disk(path: str) -> bool:
        return False

    monkeypatch.setattr("os.path.isdir", _no_disk)
    module = _load_mic_app()
    assert module.resolve_database_url() == "sqlite:////var/lib/mic-wallet/mic_wallet.db"
