# mobius.yaml — Node declaration contract (schema v1, C-286)

`mobius.yaml` at a repository root is the **declaration contract** for a Mobius node. It states **who** the node is, **what** it emits (pulse), **where** it publishes, **where** writes are accepted or delegated (ingest), **which lanes** it owns (`authoritative_for`), and optionally the **MCP** surface. It does **not** perform writes: the runtime path remains **hot state → writer/orchestrator → declared ingest target → durable ledger → optional feed mirror**.

## Top-level

| Key | Description |
|-----|-------------|
| `version` | Schema version string, e.g. `"1.0"` |
| `mesh` | Node identity, repository, discovery |
| `pulse` | What the node exposes for health / feeds / aggregation |
| `ingest` | What payloads it accepts or where it forwards writes |
| `mcp` | Optional MCP bridge (tools, URLs, integrity hints) |
| `policy` | Trust boundaries: canonical ledger, hashing, mirroring |

Legacy manifests nested everything under `mesh:` only. **v1** uses **top-level** `pulse`, `ingest`, `mcp`, and `policy` for clarity. Older keys may remain under `mesh` for backward compatibility (e.g. `substrate_ref`, `agent_affinity`).

---

## Canon (rules)

1. **Pulse** — what the node emits and exposes (URLs, lanes, `emits` flags).
2. **Ingest** — what the node accepts or where peers should POST durable payloads.
3. **`authoritative_for`** — prevents lane confusion; only list lanes this node owns.
4. **`ingest.mode: ledger_target`** — reserved for nodes that persist canonical writes (e.g. Civic-Protocol-Core).
5. **Operator nodes** (`tier: operator`) may run writers but **`policy.canonical_ledger_node`** must point at the ledger service, not themselves.
6. **`mobius.yaml` does not perform writes** — orchestrators read it and call declared URLs.

---

## `mesh`

| Field | Required | Description |
|-------|----------|-------------|
| `enabled` | yes | Whether this file participates in the mesh |
| `node_id` | yes | Stable identifier |
| `node_name` | yes | Human-readable name |
| `tier` | yes | `sentinel` \| `operator` \| `ledger` \| `client` \| `service` |
| `role` | yes | e.g. `protocol_cortex`, `operator_console`, `ledger_node`, `citizen_shell`, `service_node` |
| `repository` | yes | `full_name`, `default_branch` |
| `discovery` | no | `enabled`, `registry_participation` |

---

## `pulse`

| Field | Required | Description |
|-------|----------|-------------|
| `enabled` | yes | |
| `health_url` | recommended | Absolute URL to liveness |
| `feed_url` | recommended | EPICON / pulse feed |
| `snapshot_url` | optional | Operator snapshot (Terminal); may be empty for ledger-only nodes |
| `freshness_sla_seconds` | yes | Stale threshold for aggregators |
| `integrity_weight` | yes | Weight in network pulse rollups |
| `lanes` | yes | Vocabulary list (see below) |
| `authoritative_for` | yes | Capability strings this node owns |
| `emits` | yes | Booleans: `heartbeat`, `gi`, `mii`, `mic`, `vault`, `tripwire`, `anomalies` |

### Lane vocabulary (canonical)

`integrity`, `signals`, `tripwire`, `heartbeat`, `mic_readiness`, `vault`, `ledger`, `mesh`, `mcp`, `epicon`

---

## `ingest`

| Field | Required | Description |
|-------|----------|-------------|
| `enabled` | yes | |
| `mode` | yes | `ledger_target` \| `client_of_other_node` \| `aggregator_only` |
| `write_url` | if ledger or self-hosted ingest | Absolute URL for `POST` (e.g. `/mesh/ingest`) |
| `auth` | yes | `bearer` \| `none` \| `api-key` |
| `accepts` | for `ledger_target` | List of payload type strings (see vocabulary) |
| `targets` | for `client_of_other_node` | List of `{ node_id, write_url, purpose, auth?, accepts? }` |

### Payload vocabulary (v1)

- `EPICON_ENTRY_V1`
- `MIC_READINESS_V1`
- `MIC_SEAL_V1`
- `MIC_RESERVE_RECONCILIATION_V1`
- `MIC_GENESIS_BLOCK`
- `MOBIUS_PULSE_V1`
- (future) `MOBIUS_PULSE_V2`

Writers should attach `payload_type` (and a content `hash` per policy) before POSTing to a ledger ingest URL.

---

## `mcp` (optional)

When `mcp.enabled: true`, clients discover tools via `server_url` and optional `discovery_url` (e.g. `/.well-known/mcp.json`).

| Field | Description |
|-------|-------------|
| `server_url` | HTTPS MCP endpoint (streamable HTTP) |
| `discovery_url` | Well-known MCP JSON |
| `transport` | e.g. `streamable-http` |
| `schema_version` | MCP protocol label |
| `integrity` | GI gates, logging, agent hints |
| `tools` | Declared tool list (name, description, endpoint, method, auth, `epicon_tag`, …) |

See also `docs/09-MESH/MNS_MCP_BRIDGE.md` and `mesh/mcp-discovery.json`.

---

## `policy`

| Field | Description |
|-------|-------------|
| `write_truth_locally` | Whether this repo persists canonical truth |
| `mirror_feed_to_repo` | Whether `ledger/feed.json` (or equivalent) is mirrored in git |
| `canonical_ledger_node` | `node_id` of the durable ledger |
| `hash_algorithm` | e.g. `sha256` for pre-ingest payload hashing |

---

## Repository roles (split)

| Repo | Typical `tier` / `role` | Owns |
|------|-------------------------|------|
| **Mobius-Substrate** | `sentinel` / `protocol_cortex` | Mesh registry, spec, pulse aggregation, discovery |
| **mobius-civic-ai-terminal** | `operator` / `operator_console` | Hot runtime, heartbeat, GI/vault/MIC UI, MCP edge, **writer** |
| **Civic-Protocol-Core** | `ledger` / `ledger_node` | `/mesh/ingest`, persistence, `/epicon/feed`, ledger MCP |

---

## Civic-Protocol-Core note

This repo implements the **ledger** stack in **FastAPI** + SQLite: `POST /mesh/ingest`, `GET /epicon/feed`, `GET /health`, `POST /api/mcp`. The root `mobius.yaml` follows **v1** with `ingest.mode: ledger_target` and absolute Render URLs for operators and Substrate aggregators.
