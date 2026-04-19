# Mobius MCP Bridge — Doctrine

## What it is

Every repo in the Mobius Neural Substrate that declares `mesh.mcp.enabled: true` in `mobius.yaml` is simultaneously:

1. A **mesh node** — producing EPICON entries, tracked by MII, linked to the Substrate constitutional record.
2. An **MCP server** — discoverable by AI agents that read `mesh/mcp-discovery.json` or `/.well-known/mcp.json`.
3. An **integrity-governed capability surface** — tool invocations can be gated on Global Integrity (GI), logged to the civic ledger, and (optionally) tied to MIC accounting.

## Why this matters

Without an explicit MCP bridge, ad-hoc HTTP calls from agents leave weak audit trails. With the bridge, **intent, tool name, and outcome** can be recorded as civic events (`mcp-invocation` rows in this repo’s `epicon_entries` when logging is enabled), so ZEUS-class verifiers can reason about agent behavior over time.

**Kaizen Turing Test (KTT)** framing: integrity of AI behavior should be observable over time. The MCP bridge is one instrumentation layer — not a replacement for human review, but a durable hook for measurement and correction.

## Signal flow (Civic-Protocol-Core / FastAPI)

```
AI Agent (Cursor, Claude, Codex, …)
    |
    | reads .well-known/mcp.json or mesh/mcp-discovery.json
    v
POST https://civic-protocol-core-ledger.onrender.com/api/mcp
    |  JSON-RPC (MCP streamable HTTP)
    v
fastapi-mcp_router → tools/call → Python tool handler
    |
    v
Optional GI gate (GI_STATE_JSON or gi_state.json)
    |
    v
Optional EPICON log row (epicon_entries, source=mcp-bridge)
```

## Constitutional constraints (defaults in this repo)

- **Read tools**: GI gate 0.0 at the node level; GI unknown does not block reads.
- **Write tool** (`post_epicon_entry`): GI gate **0.6** when GI is known; returns `gi_gate_blocked` otherwise.
- **Bearer**: If `AGENT_SERVICE_TOKEN` is set, `post_epicon_entry` requires `authorization: Bearer <token>` in the tool arguments JSON.

## Adding MCP to another repo

1. Add `mesh.mcp` to `mobius.yaml`.
2. Implement the MCP transport (`mcp-handler` on Next.js, or `fastapi-mcp-router` on FastAPI, or FastMCP, etc.).
3. Register or aggregate the node in `mesh/mcp-discovery.json` (Substrate-wide index) and keep `/.well-known/mcp.json` pointing at the canonical index URL.

## One-line canon

**The tools do not only execute — they can leave a ledger trail that proves they ran under known rules.**
