"""C-339 ledger hardening regression tests."""

import os

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LEDGER_DATA_DIR", "/tmp/ledger_test_c339")

from ledger.app import main as main_module  # noqa: E402


client = TestClient(main_module.app)


class _DummyCursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _DummyConnection:
    def __init__(self, row=None):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query):
        if "SELECT timestamp FROM events" in query:
            return _DummyCursor(self._row)
        return _DummyCursor((1,))


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://identity.example/auth/introspect")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("bad status", request=request, response=response)

    def json(self):
        return self._payload


def test_ledger_responses_include_request_id_and_security_headers():
    response = client.get("/", headers={"X-Request-ID": "c339-request"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "c339-request"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")


def test_health_response_does_not_expose_backend_details(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "check_db_health",
        lambda: {"ok": True, "db": "connected", "url_type": "sqlite"},
    )
    monkeypatch.setattr(
        main_module,
        "get_db_connection",
        lambda: _DummyConnection(),
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "civic-ledger-api"}


def test_pulse_state_returns_cycle_gi_and_latest_attestation(monkeypatch):
    monkeypatch.setenv("CYCLE_ID", "C-339")
    monkeypatch.setenv("GI_STATE_JSON", '{"global_integrity": 0.97}')
    monkeypatch.setattr(
        main_module,
        "get_db_connection",
        lambda: _DummyConnection(("2026-06-11T16:16:00+00:00",)),
    )

    response = client.get("/pulse/state")

    assert response.status_code == 200
    assert response.json() == {
        "cycle": "C-339",
        "gi": 0.97,
        "attested_at": "2026-06-11T16:16:00+00:00",
    }


def test_verify_token_uses_short_ttl_cache(monkeypatch):
    calls = {"count": 0}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get(self, url, headers):
            calls["count"] += 1
            return _FakeResponse({"active": True, "civic_id": "civic-123"})

    if hasattr(main_module, "clear_token_cache"):
        main_module.clear_token_cache()
    monkeypatch.setattr(main_module, "IDENTITY_API_BASE", "https://identity.example")
    monkeypatch.setattr(main_module.httpx, "Client", FakeClient)

    first = main_module.verify_token("token-a", "identity")
    second = main_module.verify_token("token-a", "identity")

    assert first == {"active": True, "civic_id": "civic-123"}
    assert second == first
    assert calls["count"] == 1


def test_verify_token_returns_503_when_introspection_is_unavailable(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get(self, url, headers):
            raise httpx.ConnectError("offline")

    if hasattr(main_module, "clear_token_cache"):
        main_module.clear_token_cache()
    monkeypatch.setattr(main_module, "IDENTITY_API_BASE", "https://identity.example")
    monkeypatch.setattr(main_module.httpx, "Client", FakeClient)

    with pytest.raises(main_module.HTTPException) as exc:
        main_module.verify_token("token-b", "identity")

    assert exc.value.status_code == 503
    assert exc.value.detail == "Token introspection service unavailable"
