# C-293 Phase 8 — Canon / Ledger Alignment

**Date:** 2026-04-26  
**Cycle:** C-293  
**Scope:** Alignment between Mobius Canon Browser and Civic Ledger

---

## 1. Purpose

This document records how the Mobius Canon Browser (Terminal layer) relates to the Civic Protocol Core Ledger (durable event layer).

---

## 2. Separation of responsibilities

### Mobius Canon (Terminal)

- Read-only projection layer
- Displays:
  - Reserve Blocks
  - Seal hashes
  - Sentinel attestations
  - Missing quorum
  - Substrate pointers
  - Timeline events
- Does NOT:
  - mutate state
  - write attestations
  - execute rollback

### Civic Ledger (Core)

- Append-only event store
- Stores:
  - reflections
  - shield events
  - governance
  - MIC/GIC events
  - cycle events
- Guarantees:
  - immutability
  - hash chaining
  - verification

---

## 3. Relationship

```txt
Terminal Canon (read-only)
        ↓
Substrate Canon (protocol memory)
        ↓
Civic Ledger (event truth)
```

- The Canon Browser reads proof structures derived from Vault + Substrate.
- The Ledger stores raw civic events.
- Canon does not replace Ledger.
- Ledger does not interpret Canon.

---

## 4. Future integration

To fully align Canon and Ledger:

### 1. Seal anchoring

Each Reserve Block seal should optionally emit a ledger event:

```json
{
  "event_type": "reserve_block_sealed",
  "seal_id": "...",
  "seal_hash": "...",
  "prev_seal_hash": "...",
  "gi": 0.94
}
```

### 2. Attestation anchoring

Each Sentinel signature can be optionally anchored:

```json
{
  "event_type": "sentinel_attestation",
  "agent": "ATLAS",
  "seal_id": "...",
  "verdict": "pass",
  "signature": "..."
}
```

### 3. Incident anchoring

Rollback/incident flows should emit:

```json
{
  "event_type": "rollback_initiated",
  "reason": "integrity breach",
  "operator": "...",
  "seal_id": "..."
}
```

---

## 5. Canon rules enforced

- Canon displays proof.
- Ledger stores events.
- Proof must not mutate events.
- Events must not reinterpret proof.

---

## 6. Strategic implication

With Phase 8:

- Terminal = observability
- Substrate = memory
- Ledger = permanence

This separation prevents:

- fake history
- silent mutation
- unverifiable rollback

---

## 7. Savepoint note

This document records the architectural alignment at the moment the Canon Browser became operational.

Future phases should extend integration, not collapse boundaries.

We heal as we walk.
