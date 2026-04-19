"""Tests for MNS mesh routes on Civic Ledger API."""

import os
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("MOBIUS_MESH_TOKEN", "test-mesh-secret")
os.environ["LEDGER_DATA_DIR"] = "/tmp/ledger_test_mesh"

from ledger.app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_mesh_token_guard():
    yield


def test_mesh_ingest_unauthorized():
    r = client.post(
        "/mesh/ingest",
        json=[{"id": "x", "sha": "a", "title": "t"}],
        headers={"X-MNS-Node": "any"},
    )
    assert r.status_code == 401


def test_mesh_ingest_missing_node_header():
    r = client.post(
        "/mesh/ingest",
        json=[],
        headers={"Authorization": "Bearer test-mesh-secret"},
    )
    assert r.status_code == 403


def test_mesh_ingest_unregistered_when_registry_ok():
    with patch(
        "ledger.app.routes.mesh.load_mesh_registry",
        return_value=({"nodes": [{"node_id": "other", "tier": "observer"}]}, True),
    ):
        r = client.post(
            "/mesh/ingest",
            json=[{"id": f"e1-{uuid.uuid4().hex[:8]}", "sha": "abc", "title": "hello"}],
            headers={
                "Authorization": "Bearer test-mesh-secret",
                "X-MNS-Node": "unknown-node",
            },
        )
    assert r.status_code == 403


def test_mesh_ingest_allows_when_registry_fetch_failed():
    with patch(
        "ledger.app.routes.mesh.load_mesh_registry",
        return_value=({"nodes": []}, False),
    ):
        r = client.post(
            "/mesh/ingest",
            json=[{"id": f"e-fetch-fail-{uuid.uuid4().hex[:8]}", "sha": "abc", "title": "hello"}],
            headers={
                "Authorization": "Bearer test-mesh-secret",
                "X-MNS-Node": "orphan-node",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["stored"] >= 1


def test_mesh_ingest_stores_registered_node():
    with patch(
        "ledger.app.routes.mesh.load_mesh_registry",
        return_value=(
            {"nodes": [{"node_id": "substrate-test", "tier": "contributor"}]},
            True,
        ),
    ):
        r = client.post(
            "/mesh/ingest",
            json=[{"id": f"e-reg-{uuid.uuid4().hex[:8]}", "sha": "deadbeef", "title": "mesh push"}],
            headers={
                "Authorization": "Bearer test-mesh-secret",
                "X-MNS-Node": "substrate-test",
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["received"] == 1
    assert data["stored"] == 1
    assert "proof_hash" in data


def test_epicon_feed_schema():
    r = client.get("/epicon/feed")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["schema"] == "MNS_FEED_V1"
    assert j["node_id"] == "civic-protocol-core"
    assert "entries" in j


def test_mesh_nodes_schema():
    fake = {
        "mesh_version": "1.0",
        "nodes": [{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"}, {"node_id": "d"}],
    }
    with patch(
        "ledger.app.routes.mesh.load_mesh_registry", return_value=(fake, True)
    ):
        r = client.get("/mesh/nodes")
    assert r.status_code == 200
    j = r.json()
    assert j["schema"] == "MNS_REGISTRY_V1"
    assert j["node_count"] == 4
    assert len(j["nodes"]) == 4
