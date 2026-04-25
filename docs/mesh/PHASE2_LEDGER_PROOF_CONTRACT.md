# Phase 2 — Ledger Proof Contract

## Purpose

Civic Protocol Core is the proof spine of Mobius.

Terminal is the pulse. Substrate is memory. Civic Protocol Core is proof.

## Rule

The ledger does not store the whole river.

It accepts proof-worthy events and rejects duplicate or noisy repeat pulses through idempotency.

## Accepted Proof Events

```txt
EPICON_ENTRY_V1
MIC_READINESS_V1
MIC_SEAL_V1
MIC_RESERVE_RECONCILIATION_V1
MIC_GENESIS_BLOCK
MOBIUS_PULSE_V1
OAA_MEMORY_ENTRY_V1
MESH_STATE_V1
HIVE_WORLD_PULSE_V1
WORLD_UPDATE_V1
```

## Not Directly Ledgered

```txt
raw HOT rows
unverified bulk journal spam
agent scratchpad loops
feature-branch world state
```

Those belong in Terminal HOT or Substrate memory first.

## Idempotency

Required fields:

```txt
node_id
event_type
cycle
source_hash
workflow_id
```

Duplicate policy:

```txt
ignore_existing_key
```

## Canon

Substrate remembers broadly.
Civic Ledger proves selectively.
Terminal remains the operator view.

We heal as we walk.
