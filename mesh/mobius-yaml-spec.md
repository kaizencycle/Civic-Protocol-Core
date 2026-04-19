# mobius.yaml — Mobius Neural Substrate node manifest

Every Mobius mesh repo may declare a root `mobius.yaml` describing node identity, ledger behavior, integrity tracking, and (optionally) an **MCP bridge** so the same file doubles as a discoverable MCP server manifest.

## Top-level key

All fields live under `mesh:`.

## `mesh` — core registration

| Field | Required | Description |
|-------|----------|-------------|
| `node_id` | yes | Stable identifier (e.g. `civic-protocol-core`) |
| `node_type` | yes | `service`, `app`, `library`, etc. |
| `substrate_ref` | yes | GitHub repo for constitutional substrate |
| `version` | yes | Semver for this manifest |
| `tier` | yes | Mesh tier (`contributor`, `observer`, …) |
| `covenant` | yes | e.g. `integrity` |
| `agent_affinity` | no | Agents with attestation or routing affinity |
| `ledger` | no | Feed URL, backend, ingest endpoint |
| `mii` | no | Mobius Integrity Index tracking |
| `epicon` | no | EPICON / intent-block policy |
| `mic` | no | MIC participation |

## `mesh.mcp` — MCP bridge (optional)

When present and `mcp.enabled: true`, AI clients treat this node as an MCP-capable surface: tools, transport URL, and integrity rules are declared here and aggregated into `mesh/mcp-discovery.json` (network index).

### Example

```yaml
mesh:
  node_id: "mobius-civic-ai-terminal"
  node_type: "app"
  substrate_ref: "kaizencycle/Mobius-Substrate"
  version: "1.0.0"
  tier: "contributor"
  covenant: "integrity"
  agent_affinity:
    - ZEUS
    - ATLAS
  ledger:
    enabled: true
    backend: "github-actions"
    feed_url: "https://mobius-civic-ai-terminal.vercel.app/api/epicon/feed"
    push_to_substrate: true
  mii:
    track: true
    baseline: 0.85
  epicon:
    intent_blocks_required: true
    push_on_merge: true
  mic:
    participate: true
    reward_type: "MIC_REWARD_V2"

  mcp:
    enabled: true
    server_url: "https://mobius-civic-ai-terminal.vercel.app/api/mcp"
    transport: "streamable-http"
    schema_version: "MCP-2025-03-26"
    integrity:
      require_gi_above: 0.5
      log_all_invocations: true
      invocation_agent: "HERMES"
      verification_agent: "ZEUS"
      mic_reward_on_invocation: false
    tools:
      - name: "get_integrity_snapshot"
        description: "Returns current Global Integrity state, GI score, mode, and active signals"
        endpoint: "/api/terminal/snapshot-lite"
        method: "GET"
        auth: "none"
        epicon_tag: "tool:integrity-read"
```

### Field reference — `mcp`

| Field | Required | Description |
|-------|----------|-------------|
| `mcp.enabled` | yes | If true, this node exposes an MCP server |
| `mcp.server_url` | yes | HTTPS URL of the MCP endpoint (streamable HTTP) |
| `mcp.transport` | yes | `streamable-http`, `sse`, or `stdio` |
| `mcp.schema_version` | no | MCP protocol label; default `MCP-2025-03-26` |
| `mcp.integrity.require_gi_above` | no | Minimum GI for tool calls; `0` = no gate |
| `mcp.integrity.log_all_invocations` | yes | If true, each invocation should produce an EPICON record |
| `mcp.integrity.invocation_agent` | no | Agent that classifies invocations (e.g. HERMES) |
| `mcp.integrity.verification_agent` | no | Agent verifying chains (e.g. ZEUS) |
| `mcp.integrity.mic_reward_on_invocation` | no | Future MIC mint hook |

### Field reference — `mcp.tools[]`

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Tool id (`snake_case`) |
| `description` | yes | Human/agent-readable purpose |
| `endpoint` | yes | HTTP path relative to app base **or** MCP URL when all tools share one streamable endpoint |
| `method` | yes | HTTP method for REST-shaped tools; MCP streamable nodes often use `POST` to `server_url` |
| `auth` | yes | `none`, `bearer`, or `api-key` |
| `auth_env` | if auth ≠ none | Env var holding the secret |
| `epicon_tag` | yes | Tag for EPICON records on invocation |
| `requires_gi_above` | no | Per-tool GI threshold (overrides node default for that tool) |

## Civic-Protocol-Core note

This repository’s ledger service implements MCP via **FastAPI** + `fastapi-mcp-router` at `POST /api/mcp` (see `ledger/app/routes/mcp_tools.py`). Vercel/Next.js nodes may use `mcp-handler` instead; the `mobius.yaml` shape is shared.
