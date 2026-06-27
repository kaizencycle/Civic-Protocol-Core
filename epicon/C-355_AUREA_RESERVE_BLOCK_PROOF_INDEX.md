# EPICON Entry — C-355 AUREA Reserve Block Proof Index

**Cycle:** C-355  
**Agent:** AUREA  
**Repository:** kaizencycle/Civic-Protocol-Core  
**Entry Type:** EPICON_ENTRY_V1  
**Protocol Extension:** Reserve Block Proof Index  
**Status:** Proposed for CPC canon review  

---

## Intent

AUREA records the C-355 protocol decision that Civic Protocol Core should anchor Reserve Block proofs without becoming the sole storage layer for full canon artifacts.

The system distinction is:

```txt
Hot database / KV / Redis = cache and projection
Reserve Block .dat files = portable canon artifacts
CPC ledger = proof spine and hash witness
Repository = distribution surface, not ultimate truth
```

This preserves the Bitcoin-like separation between hot state and canonical block artifacts while adapting it to Mobius civic proof flows.

---

## EPICON Payload

```json
{
  "event_type": "EPICON_ENTRY_V1",
  "cycle": "C-355",
  "agent": "AUREA",
  "title": "Reserve Block Proof Index for CPC",
  "intent": "Anchor Reserve Block hashes and replay pointers in Civic Protocol Core without collapsing full canon storage into CPC.",
  "decision": {
    "reserve_blocks_are_canon_artifacts": true,
    "hot_database_is_cache": true,
    "cpc_stores_hash_anchors_not_full_canon": true,
    "hash_algorithm": "sha256",
    "human_merge_required_for_canon": true
  },
  "new_event_types": [
    "RESERVE_BLOCK_SEALED_V1",
    "RESERVE_BLOCK_INDEX_SNAPSHOT_V1"
  ],
  "recommended_anchor_fields": [
    "cycle",
    "reserve_block_id",
    "block_hash",
    "prev_block_hash",
    "state_root",
    "attestation_root",
    "storage_uri",
    "byte_size",
    "codec",
    "compression",
    "signature_set",
    "sealed_at"
  ],
  "scope_boundary": {
    "cpc_must_store": [
      "hash anchors",
      "event metadata",
      "replay pointers",
      "attestation roots",
      "integrity status"
    ],
    "cpc_must_not_require": [
      "full reserve block payload residency",
      "single database authority",
      "single repository authority",
      "silent mutation of sealed artifacts"
    ]
  }
}
```

---

## Canon Rule

CPC proves canon.  
CPC does not need to contain all canon.

Reserve Blocks may be mirrored across GitHub releases, object storage, IPFS, local node disk, or citizen archives. The CPC ledger remains authoritative for proof anchors and replay verification.

---

## Validation Checklist

- [ ] `RESERVE_BLOCK_SEALED_V1` accepted as proof-worthy ledger event.
- [ ] `RESERVE_BLOCK_INDEX_SNAPSHOT_V1` accepted as proof-worthy index event.
- [ ] `.dat` artifact hash is computed over deterministic bytes.
- [ ] `prev_block_hash` links the chain.
- [ ] `state_root` and `attestation_root` are deterministic.
- [ ] CPC stores pointer + hash, not mandatory full payload.
- [ ] Human merge required before canon activation.

---

## AUREA Attestation

AUREA recommends C-355 as a safe additive protocol alignment.

No runtime mutation is required in this entry. This is an EPICON/protocol PR intended to bind the design before implementation.

**Follow-on:** C-356 KV sovereignty — [`docs/operations/MOBIUS_KV_SOVEREIGNTY.md`](../docs/operations/MOBIUS_KV_SOVEREIGNTY.md) (Upstash suspension → substrate fallbacks).

**Seal phrase:** Integrity before scale. Canon survives by being portable.
