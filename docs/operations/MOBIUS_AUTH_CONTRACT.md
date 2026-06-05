# Mobius Auth Contract
**EPICON:** C-306 / DAEDALUS / auth-contract  
**CC0 Public Domain**

## Identity tiers (custody model)

Three roles — **not** interchangeable:

| Role | Purpose | Secret location | CPC attest? |
|------|---------|-----------------|-------------|
| Cold Founder | Constitutional / MIC reserve | Offline only — **never** in env | No |
| Active Founder | Human operator | Your login session | No (human actions only) |
| Service Account | Terminal → ledger machine attest | `IDENTITY_SERVICE_EMAIL` + `IDENTITY_SERVICE_PASSWORD` | Yes |

The Terminal cron must use a **service account** JWT minted via `/auth/login` (OPT-6 refresh client). Do **not** paste a founder wallet or founder login token into Vercel.

> Identity has no `role`/`scope` enforcement yet — tier separation is blast-radius and convention until a roles PR ships. See [MOBIUS_SERVICE_ACCOUNT_RUNBOOK.md](./MOBIUS_SERVICE_ACCOUNT_RUNBOOK.md).

## Token Map

| Service | Token / credential | Permission Level | Used By |
|---------|-------------------|------------------|---------|
| Mobius Identity | `IDENTITY_SERVICE_EMAIL` + `IDENTITY_SERVICE_PASSWORD` | Login → JWT (30d); refresh via OPT-6 | Terminal attest cron |
| civic-ledger | Identity JWT (`lab_source=terminal`) | attest via introspect | Terminal → `POST /ledger/attest` |
| civic-ledger (internal) | `AGENT_SERVICE_TOKEN` | MCP write, vault ingest | Ledger MCP tools (static bearer) |
| thought-broker | CRON_SECRET | loop/start, status | CRON Engine, Terminal |
| broker-api | API_KEY | deliberate, mii | CRON Engine |
| oaa-api-library | OAA_BEARER | sign, verify | Terminal, lab services |
| terminal (Vercel) | CRON_SECRET | internal cron trigger | Render worker |
| mic-gateway | GATEWAY_HMAC_SECRET | token routing | OAA hub |
| Terminal internal | x-internal-cron: 1 | internal route bypass | swarm cron |

Legacy name `SUBSTRATE_TOKEN` referred to a static ledger bearer — **superseded** for Terminal attest by Mobius Identity JWT + introspect.

## Rules

1. No service calls another service's write endpoint without a valid token
2. Read endpoints may be public (no auth)
3. CRON_SECRET must match on both caller and receiver
4. Founder credentials never live in Vercel env — service account only for machine attest
5. All LLM calls use ANTHROPIC_API_KEY scoped to Render worker only
6. Rotate service account password on suspected exposure; OPT-6 re-mints JWT automatically

## Terminal env checklist (Branch C)

```
IDENTITY_API_BASE          → https://mobius-identity-service.onrender.com
IDENTITY_SERVICE_EMAIL     → dedicated service account (not founder)
IDENTITY_SERVICE_PASSWORD  → secret manager only
CIVIC_LEDGER_URL           → https://civic-protocol-core-ledger.onrender.com
CRON_SECRET                → Vercel cron auth
```

Provision and smoke: [MOBIUS_SERVICE_ACCOUNT_RUNBOOK.md](./MOBIUS_SERVICE_ACCOUNT_RUNBOOK.md)
