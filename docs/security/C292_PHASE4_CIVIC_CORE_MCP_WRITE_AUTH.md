# C-292 Phase 4 — Civic Core MCP Write Auth

## Scope

Phase 4 hardens Civic Protocol Core MCP ledger writes.

Read tools remain public.

Write-capable MCP tools now fail closed unless a valid write token is configured and supplied.

## Protected tool

```txt
post_epicon_entry
```

## Accepted write token env vars

```txt
AGENT_SERVICE_TOKEN
CIVIC_LEDGER_TOKEN
LEDGER_ADMIN_TOKEN
```

At least one must be configured before MCP ledger writes are enabled.

## Accepted tool input

```json
{
  "authorization": "Bearer <token>"
}
```

Token material is normalized before comparison:

```txt
- trims whitespace
- removes Bearer prefix
- unwraps quoted values
```

Comparison uses SHA-256 digests plus constant-time comparison.

## Fail-closed behavior

If no write token is configured:

```txt
write_auth_not_configured
```

If token is missing or invalid:

```txt
write_auth_required
```

GI gate still applies after auth:

```txt
GI >= 0.6 when GI is known
```

## Canon

Read tools may remain public.
Write tools must fail closed.
GI gates are not authentication.
Ledger proof begins with authorized writes.

We heal as we walk.
