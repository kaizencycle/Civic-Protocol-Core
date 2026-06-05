"""Unit and HTTP endpoint tests for Render → routine shim."""

import pytest
from starlette.testclient import TestClient

from scripts.render_routine_shim import app as shim_app

# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_deploy_status_from_data():
    body = {"type": "deploy", "data": {"status": "deploy_succeeded", "service": {"name": "ledger"}}}
    assert shim_app._deploy_status(body) == "deploy_succeeded"
    assert shim_app._service_name(body) == "ledger"


def test_skipped_status_not_in_success_set():
    body = {"data": {"status": "build_failed"}}
    assert shim_app._deploy_status(body) == "build_failed"
    assert shim_app._deploy_status(body) not in shim_app._SUCCESS_STATUSES


def test_deploy_status_fallbacks():
    assert shim_app._deploy_status({}) == "unknown"
    assert shim_app._deploy_status({"type": "deploy_succeeded"}) == "deploy_succeeded"
    assert shim_app._deploy_status({"event": "live"}) == "live"


def test_service_name_fallback():
    assert shim_app._service_name({}) == "civic-protocol-core-ledger"
    assert shim_app._service_name({"data": {"service": "my-svc"}}) == "my-svc"


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("SHIM_SECRET", raising=False)
    return TestClient(shim_app.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_skip_non_success_status(client):
    r = client.post("/render-deploy", json={"data": {"status": "build_failed"}})
    assert r.status_code == 200
    assert r.json() == {"skipped": True, "status": "build_failed"}


def test_skip_unknown_status(client):
    r = client.post("/render-deploy", json={})
    assert r.status_code == 200
    assert r.json()["skipped"] is True


def test_shim_secret_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("SHIM_SECRET", "my-secret")
    c = TestClient(shim_app.app)
    r = c.post("/render-deploy", json={"data": {"status": "deploy_succeeded"}})
    assert r.status_code == 401


def test_shim_secret_rejects_wrong_header(monkeypatch):
    monkeypatch.setenv("SHIM_SECRET", "my-secret")
    c = TestClient(shim_app.app)
    r = c.post(
        "/render-deploy",
        json={"data": {"status": "deploy_succeeded"}},
        headers={"x-shim-secret": "wrong"},
    )
    assert r.status_code == 401


def test_fire_on_success(monkeypatch):
    """On a deploy_succeeded event, shim POSTs to the routine /fire endpoint."""
    monkeypatch.delenv("SHIM_SECRET", raising=False)
    monkeypatch.setenv("ROUTINE_TRIGGER_ID", "test-trigger-id")
    monkeypatch.setenv("ROUTINE_TOKEN", "test-token")

    import httpx

    class _MockResponse:
        status_code = 200
        def json(self):
            return {"claude_code_session_url": "https://claude.ai/code/session_test"}
        def raise_for_status(self):
            pass

    class _MockAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def post(self, url, **kwargs):
            assert "test-trigger-id" in url
            assert kwargs["headers"]["Authorization"] == "Bearer test-token"
            assert "deploy_succeeded" in kwargs["json"]["text"]
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _MockAsyncClient())

    c = TestClient(shim_app.app)
    r = c.post(
        "/render-deploy",
        json={"data": {"status": "deploy_succeeded", "service": {"name": "ledger"}}},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["fired"] is True
    assert data["status"] == "deploy_succeeded"
    assert data["fire_status_code"] == 200
