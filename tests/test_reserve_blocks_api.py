"""HTTP tests for /api/reserve-blocks (C-355)."""

import json
import os

from fastapi.testclient import TestClient

os.environ.setdefault("MOBIUS_MESH_TOKEN", "test-mesh-secret")
os.environ.setdefault("AGENT_SERVICE_TOKEN", "test-agent-service-token-c339")
os.environ["LEDGER_DATA_DIR"] = "/tmp/ledger_test_reserve_blocks"

from ledger.app.main import app  # noqa: E402

client = TestClient(app)


def test_reserve_block_index_empty():
    r = client.get("/api/reserve-blocks/index")
    assert r.status_code == 200
    body = r.json()
    assert body["total_blocks"] == 0
    assert body["blocks"] == []


def test_reserve_block_anchor_requires_auth():
    r = client.post(
        "/api/reserve-blocks/anchor",
        json={
            "block_id": "reserve-block-C355-001",
            "cycle": "C355",
            "sequence": 1,
            "gi_at_seal": 0.97,
            "mic_minted": 50.0,
            "quorum_met": True,
            "sealed_at": "2026-06-27T17:00:05Z",
        },
    )
    assert r.status_code == 401


def test_reserve_block_anchor_success():
    r = client.post(
        "/api/reserve-blocks/anchor",
        headers={"Authorization": "Bearer test-agent-service-token-c339"},
        json={
            "block_id": "reserve-block-C355-001",
            "cycle": "C355",
            "sequence": 1,
            "gi_at_seal": 0.97,
            "mic_minted": 50.0,
            "quorum_met": True,
            "sealed_at": "2026-06-27T17:00:05Z",
            "sha256": "abc123",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "anchored"
    assert body["block_id"] == "reserve-block-C355-001"
