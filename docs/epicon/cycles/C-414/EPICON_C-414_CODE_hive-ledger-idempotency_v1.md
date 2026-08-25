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

**Must merge with:** [mobius-hive PR #30](https://github.com/kaizencycle/mobius-hive/pull/30) —
client emits crypto-random `hive-op-<32 hex>` operation IDs persisted per logical
write in localStorage (not derivable from public action fields).

## Server changes (this repo)

- `hive_operation_keys` table + legacy PK migration in `ledger/app/db.py`
- Idempotency resolution in `ledger/app/main.py` (`_attest_hive_player_event`)
- Extended `EventResponse.idempotent` flag
- Composite primary key `(civic_id, operation_id)` prevents cross-citizen poisoning
- Rate limit applied inside `BEGIN IMMEDIATE` only after idempotency miss

## Boundaries

- No production ledger replay or duplicate cleanup
- No change to authenticated terminal/identity attest lanes
- Tests use isolated `LEDGER_DATA_DIR` temp directories only

## EPICON-02 INTENT PUBLICATION

```intent
epicon_id: EPICON_C-414_CODE_hive-ledger-idempotency_v1
ledger_id: mobius:kaizencycle
scope: infra
mode: normal
issued_at: 2026-08-25T16:45:00Z
expires_at: 2026-11-25T16:45:00Z
justification:
  VALUES INVOKED: Immutable ledger integrity; operator truth over duplicate citizen_history rows.
  REASONING: hive.player_event had rate limiting only — ambiguous client retries could duplicate citizen_history when the server accepted a write but the response was lost. operation_id maps one logical write to one event_id with payload fingerprint conflict detection; composite (civic_id, operation_id) prevents cross-citizen poisoning; legacy SQLite PKs migrate on connect.
  ANCHORS:
    - ledger/app/main.py
    - ledger/app/db.py
    - docs/epicon/cycles/C-414/EPICON_C-414_CODE_hive-ledger-idempotency_v1.md
    - kaizencycle/mobius-hive lib/hive-player-event.mjs (paired PR #30)
  BOUNDARIES: hive.player_event lane only. No execution authority, GI/MIC/MII mutation, production replay, or duplicate cleanup.
  COUNTERFACTUAL: If retry still creates duplicate events or idempotent retries receive 429 under concurrency, revert both paired PRs immediately.
counterfactuals:
  - Idempotent retry of the same operation_id returns the stored event without consuming the per-civic_id rate limit.
  - Same operation_id with a different payload for the same civic_id returns HTTP 409 fail-closed.
  - Concurrent identical writes serialize under BEGIN IMMEDIATE and resolve to one authoritative event.
  - If legacy hive_operation_keys tables retain operation_id-only PK after deploy, migration failed — block promotion until _ensure_hive_operation_keys_schema runs.
```
