---
epicon_id: EPICON_C-414_CODE_hive-ledger-idempotency_v1
title: "C-414 CPC hive.player_event operation_id deduplication"
cycle: "C-414"
status: "intent"
target_repo: "kaizencycle/Civic-Protocol-Core"
created_at: "2026-08-25T16:45:00Z"
version: 1
summary: "Server-side idempotent dedup for hive.player_event via operation_id."
paired_dependency: "kaizencycle/mobius-hive — same EPICON, client operation_id emission"
---

# EPICON C-414 — CPC Hive Player Event Idempotency

## Scope

Add `operation_id` acceptance and deduplication for the pseudonymous
`lab_source=hive` / `event_type=hive.player_event` lane on `POST /ledger/attest`.

## Paired dependency

**Must merge with:** [mobius-hive PR (paired)](https://github.com/kaizencycle/mobius-hive) —
client emits stable random `hive-op-<32 hex>` operation IDs persisted per
logical write in localStorage (not derivable from public action fields).

## Server changes (this repo)

- `hive_operation_keys` table in `ledger/app/db.py`
- Idempotency resolution in `ledger/app/main.py` (`_attest_hive_player_event`)
- Extended `EventResponse.idempotent` flag
- Tests in `tests/test_hive_player_events.py`

## Boundaries

- No production ledger replay or duplicate cleanup
- No change to authenticated terminal/identity attest lanes
- Tests use isolated `LEDGER_DATA_DIR` temp directories only

## EPICON-02 INTENT PUBLICATION

```intent
epicon_id: EPICON_C-414_CODE_hive-ledger-idempotency_v1
ledger_id: kaizencycle
scope: core
mode: normal
issued_at: 2026-08-25T16:45:00Z
expires_at: 2026-11-25T16:45:00Z

justification:
  VALUES INVOKED: Immutable ledger integrity; retries must not fork history.
  REASONING: hive.player_event had rate limiting only — ambiguous client retries
  could duplicate citizen_history. operation_id maps one logical write to one
  event_id with payload fingerprint conflict detection.
  ANCHORS:
    - ledger/app/main.py
    - ledger/app/db.py
    - kaizencycle/mobius-hive lib/hive-player-event.mjs (paired)
  BOUNDARIES: hive.player_event lane only. No execution authority changes.
  COUNTERFACTUAL: If duplicates still possible on retry, revert both PRs.

counterfactuals:
  - Idempotent retry skips rate limit and returns stored event
  - Payload mismatch on reused operation_id → 409
  - Concurrent identical writes serialize via BEGIN IMMEDIATE
```
