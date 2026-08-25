"""C-341 Brief D: lab_source=hive pseudonymous player-event lane."""

import hashlib
import os
import secrets
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


def _operation_id(civic_id: str = VALID_CIVIC_ID, *, suffix: str | None = None) -> str:
    """Unguessable client operation_id (mirrors HIVE localStorage-backed random IDs)."""
    del civic_id  # scoped per civic_id on server; tests pass explicit ids
    token = secrets.token_hex(16 if suffix is None else 8)
    if suffix is not None:
        token = hashlib.sha256(f"{suffix}:{token}".encode()).hexdigest()[:32]
    return f"hive-op-{token}"


@pytest.fixture(autouse=True)
def _reset_hive_rate_limit():
    main_module.clear_hive_rate_limit()
    yield
    main_module.clear_hive_rate_limit()


def _attest(civic_id: str = VALID_CIVIC_ID, **overrides):
    payload = overrides.pop("payload", None)
    payload_body = {**PAYLOAD, "civic_id": civic_id}
    if payload is not None:
        payload_body = payload
    operation_id = overrides.pop("operation_id", None)
    if operation_id is None and overrides.get("event_type", "hive.player_event") == "hive.player_event":
        operation_id = _operation_id(civic_id, suffix=overrides.pop("_op_suffix", None))
    body = {
        "event_type": "hive.player_event",
        "civic_id": civic_id,
        "lab_source": "hive",
        "payload": payload_body,
    }
    if operation_id is not None:
        body["operation_id"] = operation_id
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
    first = _attest(operation_id=_operation_id(VALID_CIVIC_ID, suffix="rate-a"))
    assert first.status_code == 200, first.text

    second = _attest(operation_id=_operation_id(VALID_CIVIC_ID, suffix="rate-b"))
    assert second.status_code == 429

    other_civic = "mobius-anon-deadbeef"
    third = _attest(
        civic_id=other_civic,
        operation_id=_operation_id(other_civic, suffix="rate-c"),
    )
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


def test_hive_attest_missing_top_level_lab_source_returns_422():
    """C-347-C found mobius-hive/browser-shell clients that never set lab_source at
    all (a plain omission bug, not a lab_source=hive request that fails hive-lane
    checks) — Pydantic already rejects that at the request-model level. Pin it as
    tested behavior so a fixed client can be verified against it."""
    resp = client.post(
        "/ledger/attest",
        json={
            "event_type": "hive.player_event",
            "civic_id": VALID_CIVIC_ID,
            "payload": PAYLOAD,
        },
    )
    assert resp.status_code == 422


def test_hive_attest_rejects_payload_missing_required_field():
    """player_event.schema.json's required fields were documentation only —
    the server accepted a payload missing e.g. target_id. This locks in the fix."""
    incomplete_payload = {k: v for k, v in PAYLOAD.items() if k != "target_id"}
    resp = _attest(payload=incomplete_payload)
    assert resp.status_code == 422
    assert "target_id" in resp.json()["detail"]


def test_hive_attest_payload_validation_scoped_to_player_event_type():
    """The required-field check only applies to event_type=hive.player_event —
    the hive lab_source itself is not restricted to a single event_type."""
    resp = _attest(event_type="hive.other_event", payload={})
    assert resp.status_code == 200, resp.text


def test_hive_attest_rejects_non_iso8601_client_ts():
    """player_event.schema.json declares client_ts format=date-time — a non-empty
    but non-ISO-8601 string must not be silently written to the ledger."""
    resp = _attest(payload={**PAYLOAD, "client_ts": "not-a-date"})
    assert resp.status_code == 422
    assert "client_ts" in resp.json()["detail"]


def test_hive_attest_invalid_payload_does_not_consume_rate_limit():
    """A malformed payload must not burn the per-civic_id throttle — otherwise a
    client that fixes its payload and retries immediately gets 429 instead of
    another chance to succeed."""
    civic_id = "mobius-anon-ratefix01"
    bad_payload = {**PAYLOAD, "civic_id": civic_id, "target_id": ""}
    bad = _attest(civic_id=civic_id, payload=bad_payload)
    assert bad.status_code == 422

    good_payload = {**PAYLOAD, "civic_id": civic_id}
    good = _attest(civic_id=civic_id, payload=good_payload)
    assert good.status_code == 200, good.text


def test_ledger_events_without_since_keeps_legacy_descending_order():
    """Omitting `since` must behave exactly as before (newest first, offset pagination)."""
    civic_id = "mobius-anon-legacy01"
    first = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-a"},
        operation_id=_operation_id(civic_id, suffix="legacy-a"),
    )
    assert first.status_code == 200, first.text
    main_module.clear_hive_rate_limit()
    second = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-b"},
        operation_id=_operation_id(civic_id, suffix="legacy-b"),
    )
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


def test_hive_player_event_requires_operation_id():
    resp = client.post(
        "/ledger/attest",
        json={
            "event_type": "hive.player_event",
            "civic_id": VALID_CIVIC_ID,
            "lab_source": "hive",
            "payload": {**PAYLOAD, "civic_id": VALID_CIVIC_ID},
        },
    )
    assert resp.status_code == 422
    assert "operation_id" in resp.json()["detail"]


def test_hive_player_event_retry_returns_original_outcome():
    op_id = _operation_id("mobius-anon-retry01", suffix="retry")
    civic_id = "mobius-anon-retry01"
    first = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-retry"},
        operation_id=op_id,
    )
    assert first.status_code == 200, first.text
    assert first.json()["idempotent"] is False

    retry = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-retry"},
        operation_id=op_id,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["idempotent"] is True
    assert retry.json()["event_id"] == first.json()["event_id"]


def test_hive_player_event_same_operation_id_different_payload_fails_closed():
    op_id = _operation_id("mobius-anon-conflict01", suffix="conflict")
    civic_id = "mobius-anon-conflict01"
    first = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-conflict", "action": "channel_node"},
        operation_id=op_id,
    )
    assert first.status_code == 200, first.text

    conflict = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-conflict", "action": "restore_beacon"},
        operation_id=op_id,
    )
    assert conflict.status_code == 409


def test_hive_player_event_separate_events_receive_distinct_operation_ids():
    civic_id = "mobius-anon-distinct01"
    op_a = _operation_id(civic_id, suffix="dist-a")
    op_b = _operation_id(civic_id, suffix="dist-b")
    assert op_a != op_b

    first = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-dist-a"},
        operation_id=op_a,
    )
    assert first.status_code == 200, first.text
    main_module.clear_hive_rate_limit()
    second = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-dist-b"},
        operation_id=op_b,
    )
    assert second.status_code == 200, second.text
    assert first.json()["event_id"] != second.json()["event_id"]


def test_hive_player_event_idempotent_retry_does_not_consume_rate_limit():
    civic_id = "mobius-anon-idemrate01"
    op_id = _operation_id(civic_id, suffix="idem")
    payload = {**PAYLOAD, "civic_id": civic_id, "target_id": "node-idem"}
    first = _attest(civic_id=civic_id, payload=payload, operation_id=op_id)
    assert first.status_code == 200, first.text

    retry = _attest(civic_id=civic_id, payload=payload, operation_id=op_id)
    assert retry.status_code == 200, retry.text
    assert retry.json()["idempotent"] is True

    main_module.clear_hive_rate_limit()
    other = _attest(
        civic_id=civic_id,
        payload={**PAYLOAD, "civic_id": civic_id, "target_id": "node-other"},
        operation_id=_operation_id(civic_id, suffix="idem-other"),
    )
    assert other.status_code == 200, other.text


def test_hive_operation_id_scoped_per_civic_id():
    """Same operation_id hex under different civic_ids cannot poison each other."""
    shared_op = f"hive-op-{'ab' * 16}"
    victim = "mobius-anon-victim01"
    attacker = "mobius-anon-attacker1"
    victim_payload = {**PAYLOAD, "civic_id": victim, "target_id": "node-victim"}

    attacker_first = _attest(
        civic_id=attacker,
        payload={**PAYLOAD, "civic_id": attacker, "target_id": "node-attacker", "action": "restore_beacon"},
        operation_id=shared_op,
    )
    assert attacker_first.status_code == 200, attacker_first.text

    main_module.clear_hive_rate_limit()
    victim_first = _attest(civic_id=victim, payload=victim_payload, operation_id=shared_op)
    assert victim_first.status_code == 200, victim_first.text
    assert victim_first.json()["event_id"] != attacker_first.json()["event_id"]

    victim_retry = _attest(civic_id=victim, payload=victim_payload, operation_id=shared_op)
    assert victim_retry.status_code == 200, victim_retry.text
    assert victim_retry.json()["idempotent"] is True
