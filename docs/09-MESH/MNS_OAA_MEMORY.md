# OAA sovereign memory → Civic durable seal (C-286)

## Write path

```
KV / runtime (hot)
  → writer / orchestrator (e.g. Terminal)
  → OAA signed append journal (OAA-API-Library)
  → Civic Protocol Core durable seal
  → optional mesh / EPICON feed mirror
```

## Civic Protocol Core

- **`POST /api/oaa/memory`** — Bearer `OAA_MEMORY_API_TOKEN` (or `MOBIUS_MESH_TOKEN` fallback). Body: `OAA_MEMORY_ENTRY_V1` JSON. Stores append-only row in `oaa_memory_proofs`.
- **`GET /api/oaa/memory/{hash}`** — proof lookup by hash.
- **`GET /api/oaa/memory`** — list recent proofs (`source`, `key_prefix`, pagination).

## Mesh ingest bridge

`POST /mesh/ingest` with `X-MNS-Node: oaa-api-library` may send a batch of objects where each has `type: OAA_MEMORY_ENTRY_V1`. Those rows are persisted to `oaa_memory_proofs` (not `mesh_entries`). Other entries continue to use the mesh path.

## Rules

- OAA remains the **sovereign append journal**; Civic Core is the **durable verification / seal** target.
- OAA computes content hashes; Civic stores the declared hash for audit (re-hash verification can be added later).
