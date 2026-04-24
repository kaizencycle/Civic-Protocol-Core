"""Tests for C-290 seal reconciliation endpoints."""

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["LEDGER_DATA_DIR"] = "/tmp/ledger_test_seal_reconciliation"

from ledger.app.db import get_db_connection  # noqa: E402
from ledger.app.main import app  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_seal_tables():
    with get_db_connection() as conn:
        conn.execute("DELETE FROM seal_records")
        conn.execute("DELETE FROM events WHERE event_type = 'seal_reconciliation_finalized'")
        conn.commit()


def _seed_payload(status: str = "quarantined"):
    return {
        "seal": {
            "seal_id": "seal-C-288-001",
            "sequence": 1,
            "cycle_at_seal": "C-288",
            "sealed_at": "2026-04-21T17:02:39.381Z",
            "reserve": 50,
            "gi_at_seal": 0.74,
            "mode_at_seal": "compat",
            "source_entries": 12,
            "deposit_hashes": ["d1", "d2"],
            "prev_seal_hash": None,
            "seal_hash": "3e0c2403c291a4f54a8d6b5111a64278bfc23eb5e92e5e5d6e41b044dbcdaf92",
            "status": status,
            "attestations": {
                "ZEUS": {"verdict": "flag", "rationale": "timeout"},
                "ATLAS": {"verdict": "flag", "rationale": "timeout"},
            },
        },
        "quarantine_reason": "attestation_timeout",
    }


def test_seed_and_list_quarantine():
    seeded = client.post("/api/seal/reconcile", json=_seed_payload())
    assert seeded.status_code == 200
    data = seeded.json()
    assert data["ok"] is True

    listed = client.get("/api/seal/quarantine")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(x["seal_id"] == "seal-C-288-001" for x in items)


def test_reattest_timeout_remains_quarantined_then_fails_permanent_after_three_attempts():
    client.post("/api/seal/reconcile", json=_seed_payload())

    for i in range(3):
        res = client.post("/api/seal/reattest", json={"seal_id": "seal-C-288-001"})
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        if i < 2:
            assert body["item"]["status"] == "quarantined"
        else:
            assert body["item"]["status"] == "failed_permanent"


def test_finalize_requires_reattest_passed_and_is_idempotent():
    seal_id = "seal-C-288-pass"
    payload = _seed_payload(status="re_attesting_passed")
    payload["seal"]["seal_id"] = seal_id
    payload["seal"]["attestations"] = {
        "ZEUS": {"verdict": "pass", "rationale": "ok"},
        "ATLAS": {"verdict": "pass", "rationale": "ok"},
    }
    seeded = client.post("/api/seal/reconcile", json=payload)
    assert seeded.status_code == 200

    first = client.post("/api/seal/finalize", json={"seal_id": seal_id})
    assert first.status_code == 200
    assert first.json()["item"]["status"] == "finalized"

    second = client.post("/api/seal/finalize", json={"seal_id": seal_id})
    assert second.status_code == 200
    assert second.json()["already_finalized"] is True
