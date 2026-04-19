"""OAA memory proof seal API and mesh ingest bridge."""

import json
import os
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.setdefault("MOBIUS_MESH_TOKEN", "test-mesh-secret")
os.environ.setdefault("OAA_MEMORY_API_TOKEN", "oaa-test-token")
os.environ["LEDGER_DATA_DIR"] = "/tmp/ledger_test_oaa"

from ledger.app.main import app  # noqa: E402

client = TestClient(app)


def _oaa_body(h: str | None = None):
    return {
        "type": "OAA_MEMORY_ENTRY_V1",
        "agent": "ECHO",
        "cycle": "C-286",
        "key": f"vault:status:{uuid.uuid4().hex[:8]}",
        "intent": "vault update",
        "hash": h or uuid.uuid4().hex,
        "previous_hash": None,
        "timestamp": "2026-04-19T17:00:00Z",
    }


def test_oaa_memory_unauthorized():
    r = client.post("/api/oaa/memory", json=_oaa_body())
    assert r.status_code == 401


def test_oaa_memory_seal_and_lookup():
    body = _oaa_body()
    r = client.post(
        "/api/oaa/memory",
        json=body,
        headers={"Authorization": "Bearer oaa-test-token"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["inserted"] is True

    g = client.get(f"/api/oaa/memory/{body['hash']}")
    assert g.status_code == 200
    assert g.json()["entry"]["agent"] == "ECHO"


def test_mesh_ingest_oaa_batch():
    with patch(
        "ledger.app.routes.mesh.load_mesh_registry",
        return_value=({"nodes": []}, False),
    ):
        entry = _oaa_body()
        r = client.post(
            "/mesh/ingest",
            json=[entry],
            headers={
                "Authorization": "Bearer test-mesh-secret",
                "X-MNS-Node": "oaa-api-library",
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["oaa_memory"]["stored"] == 1

    g = client.get(f"/api/oaa/memory/{entry['hash']}")
    assert g.status_code == 200


def test_mesh_ingest_oaa_wrong_node():
    with patch(
        "ledger.app.routes.mesh.load_mesh_registry",
        return_value=({"nodes": [{"node_id": "other", "tier": "observer"}]}, True),
    ):
        r = client.post(
            "/mesh/ingest",
            json=[_oaa_body()],
            headers={
                "Authorization": "Bearer test-mesh-secret",
                "X-MNS-Node": "other",
            },
        )
    assert r.status_code == 400
