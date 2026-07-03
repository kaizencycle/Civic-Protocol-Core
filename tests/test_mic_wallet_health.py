"""C-360: MIC wallet /health exposes db_write_ok probe."""

import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
MIC_MAIN = REPO_ROOT / "mic-wallet" / "app" / "main.py"


def _load_mic_app():
    spec = importlib.util.spec_from_file_location("mic_wallet_main", MIC_MAIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mic_wallet_main"] = module
    spec.loader.exec_module(module)
    return module.app


def test_mic_wallet_health_reports_write_probe(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/mic_wallet.db")
    app = _load_mic_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "mobius-mic-wallet"
    assert payload["db_ok"] is True
    assert payload["db_write_ok"] is True
    assert payload["db_connected"] is True
