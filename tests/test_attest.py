"""Contract tests for /ledger/attest and identity/terminal token verification."""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LEDGER_DATA_DIR", "/tmp/ledger_test_attest")

from ledger.app import main as main_module  # noqa: E402
from ledger.app.main import verify_token  # noqa: E402

client = TestClient(main_module.app)


def test_verify_token_terminal_without_identity_api_base():
    """lab_source=terminal with empty IDENTITY_API_BASE must name the server env gap."""
    original = main_module.IDENTITY_API_BASE
    main_module.IDENTITY_API_BASE = ""
    try:
        with pytest.raises(main_module.HTTPException) as exc:
            verify_token("test-token", "terminal")
        assert exc.value.status_code == 400
        assert "IDENTITY_API_BASE" in exc.value.detail
        assert "lab_source='terminal'" in exc.value.detail
    finally:
        main_module.IDENTITY_API_BASE = original


def test_attest_terminal_without_identity_api_base():
    """POST /ledger/attest must return 400 naming IDENTITY_API_BASE when unset on server."""
    original = main_module.IDENTITY_API_BASE
    main_module.IDENTITY_API_BASE = ""
    try:
        resp = client.post(
            "/ledger/attest",
            json={
                "event_type": "seal.immortalize",
                "civic_id": "mobius-civic-ai-terminal",
                "lab_source": "terminal",
                "payload": {"seal_id": "test-seal"},
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 400
        assert "IDENTITY_API_BASE" in resp.json()["detail"]
    finally:
        main_module.IDENTITY_API_BASE = original
