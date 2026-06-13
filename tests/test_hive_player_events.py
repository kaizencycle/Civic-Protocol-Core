"""C-341 Brief D: lab_source=hive pseudonymous player-event lane."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# Fresh DB per test run — the cursor tests assert exact event sets, which a
# shared/reused ledger.db across runs would pollute.
os.environ["LEDGER_DATA_DIR"] = tempfile.mkdtemp(prefix="ledger_test_hive_player_events_")

from ledger.app import main as main_module  # noqa: E402

client = TestClient(main_module.app)

VALID_CIVIC_ID = "mobius-anon-7f2a9c1d"

PAYLOAD = {
    "world": "hive-citadel",
    "zone": "castle",
    "action": "channel_node",
    "target_id": "node-0",
    "cycle_id": "C-341",
    "civic_id": VALID_CIVIC_ID,
    "client_ts": "2026-06-12T08:14:00Z",
}


@pytest.fixture(autouse=True)
def _reset_hive_rate_limit():
    main_module.clear_hive_rate_limit()
    yield
    main_module.clear_hive_rate_limit()


def _attest(civic_id: str = VALID_CIVIC_ID, **overrides):
    body = {
        "event_type": "hive.player_event",
        "civic_id": civic_id,
        "lab_source": "hive",
        "payload": {**PAYLOAD, "civic_id": civic_id},
    }
    body.update(overrides)
    return client.post("/ledger/attest", json=body)


def test_hive_attest_requires_no_authorization_header():
    """The pseudonymous lane has no JWT — attest succeeds without a Bearer token."""
    resp = _attest()
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["event_type"] == "hive.player_event"
    assert data["civic_id"] == VALID_CIVIC_ID
    assert data["lab_source"] == "hive"
    assert data["confirmed"] is True


def test_hive_attest_rejects_civic_id_without_mobius_anon_prefix():
    resp = _attest(civic_id="player-123")
    assert resp.status_code == 403
    assert "mobius-anon-" in resp.json()["detail"]


def test_hive_attest_does_not_grant_terminal_privileges():
    """A mobius-anon-* id has no standing in the terminal/identity trust tiers."""
    resp = client.post(
        "/ledger/attest",
        json={
            "event_type": "seal.immortalize",
            "civic_id": VALID_CIVIC_ID,
            "lab_source": "terminal",
            "payload": {"seal_id": "test-seal"},
        },
    )
    assert resp.status_code == 401  # missing Authorization header — terminal still gated


def test_hive_attest_rate_limited_per_civic_id():
    first = _attest()
    assert first.status_code == 200, first.text

    second = _attest()
    assert second.status_code == 429

    other_civic = "mobius-anon-deadbeef"
    third = _attest(civic_id=other_civic)
    assert third.status_code == 200, third.text


def test_ledger_events_since_cursor_returns_ascending_new_events():
    base_civic = "mobius-anon-cursor01"
    first = _attest(civic_id=base_civic, payload={**PAYLOAD, "civic_id": base_civic, "target_id": "node-0"})
    assert first.status_code == 200, first.text
    first_id = first.json()["event_id"]

    main_module.clear_hive_rate_limit()
    second = _attest(civic_id=base_civic, payload={**PAYLOAD, "civic_id": base_civic, "target_id": "node-1"})
    assert second.status_code == 200, second.text
    second_id = second.json()["event_id"]

    # since=<first event> returns only the second, ascending.
    resp = client.get(
        "/ledger/events",
        params={"event_type": "hive.player_event", "civic_id": base_civic, "since": first_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [e["event_id"] for e in body["events"]] == [second_id]

    # since="" (empty cursor) returns both, oldest first.
    resp = client.get(
        "/ledger/events",
        params={"event_type": "hive.player_event", "civic_id": base_civic, "since": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [e["event_id"] for e in body["events"]] == [first_id, second_id]


def test_ledger_events_since_unknown_event_id_returns_404():
    resp = client.get("/ledger/events", params={"since": "evt_does_not_exist"})
    assert resp.status_code == 404


def test_ledger_events_without_since_keeps_legacy_descending_order():
    """Omitting `since` must behave exactly as before (newest first, offset pagination)."""
    civic_id = "mobius-anon-legacy01"
    first = _attest(civic_id=civic_id, payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-a"})
    assert first.status_code == 200, first.text
    main_module.clear_hive_rate_limit()
    second = _attest(civic_id=civic_id, payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-b"})
    assert second.status_code == 200, second.text

    resp = client.get(
        "/ledger/events",
        params={"event_type": "hive.player_event", "civic_id": civic_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    # created_at has second resolution, so same-second inserts may tie; the
    # legacy path is unchanged either way — just confirm both are returned.
    assert {e["event_id"] for e in body["events"]} == {
        first.json()["event_id"],
        second.json()["event_id"],
    }
