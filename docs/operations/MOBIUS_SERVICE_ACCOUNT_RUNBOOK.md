# Mobius Service Account Runbook (OPT-6)
**EPICON:** Branch C unblock — Terminal → CPC attestation  
**CC0 Public Domain**

## What this fixes

Canon Reserve Blocks show `ledger 401: Token verification failed` because the Terminal cron holds an invalid or missing Mobius Identity JWT. CPC introspects every `POST /ledger/attest` with `lab_source=terminal` at:

```http
GET {IDENTITY_API_BASE}/auth/introspect
Authorization: Bearer <same JWT as attest>
```

This runbook provisions a **dedicated service account** (robot identity) and wires **OPT-6** — login-backed JWT refresh — so attestations succeed without pasting a founder credential into Vercel.

## Three identities — do not conflate

| Role | Purpose | Where it lives | Privilege today |
|------|---------|----------------|-----------------|
| **Cold Founder** | Constitutional / MIC reserve | Offline, never in env | Human choice only — no enforcement yet |
| **Active Founder** | Day-to-day operator | Your login | Same JWT power as any account today |
| **Service Account** | Terminal → ledger attest | Secret manager credentials | Same JWT power today; attest-only by convention |

**Never** use a Founder Wallet or founder login as `AGENT_SERVICE_TOKEN`. If that secret leaks, blast radius is founder authority. The service account limits damage to revocable attestations.

> **Prerequisite gap:** Identity has no `role` or `scope` claims yet (`UserResponse` is `{id, email, name, civic_id, created_at}`). Tier separation is **credential blast-radius** until roles land (see [MOBIUS_AUTH_CONTRACT.md](./MOBIUS_AUTH_CONTRACT.md)).

## Phase 1 — Provision service account (one-time)

### 1.0 One-command reset (C-358)

After Identity has a **writable** `DATABASE_URL` (Render disk or Postgres):

```bash
cd Civic-Protocol-Core
pip install httpx
./scripts/reset_terminal_identity_account.sh
```

Default email: `terminal@mobius-substrate.com`. Script generates `IDENTITY_SERVICE_PASSWORD`, signs up (or reuses existing), smoke-tests `/ledger/attest`, and prints Vercel env lines.

### 1.1 Create the robot user

From Civic-Protocol-Core repo root:

```bash
export IDENTITY_SERVICE_PASSWORD="$(openssl rand -base64 32)"

python scripts/provision_service_account.py signup \
  --email terminal@mobius-substrate.com \
  --password "$IDENTITY_SERVICE_PASSWORD" \
  --name "Mobius Civic AI Terminal"
```

Store in your secret manager (Vercel → Settings → Environment Variables):

| Variable | Value | Notes |
|----------|-------|-------|
| `IDENTITY_API_BASE` | `https://mobius-identity-service.onrender.com` | No `/auth` suffix |
| `IDENTITY_SERVICE_EMAIL` | `terminal@mobius-substrate.com` | Service account only |
| `IDENTITY_SERVICE_PASSWORD` | *(generated)* | Never commit; rotate on exposure |
| `CIVIC_LEDGER_URL` | `https://civic-protocol-core-ledger.onrender.com` | CPC ledger |

### 1.2 Smoke test (local or CI)

```bash
export IDENTITY_SERVICE_EMAIL=terminal@mobius-substrate.com
export IDENTITY_SERVICE_PASSWORD='...'

# Reads IDENTITY_SERVICE_EMAIL/PASSWORD from env (or pass --email/--password)
python scripts/provision_service_account.py smoke
```

Success output includes `event_hash` from CPC. Verify ledger:

```bash
curl -sS "$CIVIC_LEDGER_URL/ledger/stats" | jq '.total_events'
```

### 1.3 Deprecate static `AGENT_SERVICE_TOKEN`

Short-term bridge: you may still set `AGENT_SERVICE_TOKEN` to a freshly minted JWT from login. **Durable path:** OPT-6 client mints JWT at runtime — do not rely on a pasted 30-day token.

## Phase 2 — Wire OPT-6 in Terminal

Copy or import the refresh client:

- **Node / Vercel:** [`sdk/js/identityClient.js`](../../sdk/js/identityClient.js)
- **Python workers:** [`sdk/python/identity_client.py`](../../sdk/python/identity_client.py)

### Terminal integration pattern

```javascript
import { IdentityTokenClient } from '@/lib/identityClient'; // copy from sdk/js

const identity = IdentityTokenClient.fromEnv();

export async function attestToSubstrate({ eventType, civicId, payload }) {
  const ledgerUrl = process.env.CIVIC_LEDGER_URL;
  return identity.attest(ledgerUrl, {
    eventType,
    civicId: civicId ?? 'mobius-civic-ai-terminal',
    payload,
    labSource: 'terminal',
  });
}
```

Call `getToken()` (or `attest()`) at the start of `/api/cron/reattest-seals` and `/api/cron/journal-canonize`. The client refreshes ~24h before JWT expiry (`IDENTITY_TOKEN_REFRESH_MARGIN_SECONDS`, default 86400).

### civic_id binding

Ledger allows `lab_source=terminal` with `civic_id` matching `mobius-*` even when the JWT's `civic_id` is the service account's `civic::…` id. Keep attest bodies on `mobius-civic-ai-terminal`.

## Phase 3 — Drain the attestation queue

After Terminal deploy with OPT-6 env vars:

1. Trigger reattest cron (or wait for hourly schedule).
2. Watch Canon UI: `substrate_pointer.event_hash` should populate.
3. Vault: `substrate_immortalized` increases; `ledger 401` errors stop.

Manual cron trigger (if `CRON_SECRET` set):

```bash
curl -sS -X POST "https://mobius-civic-ai-terminal.vercel.app/api/cron/reattest-seals" \
  -H "Authorization: Bearer $CRON_SECRET"
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Token verification failed` + introspect URL | Bad/expired JWT or wrong Identity base | Run `provision_service_account.py smoke`; confirm CPC `IDENTITY_API_BASE` |
| Creds set on Vercel but `identity_login_ok: false` | Identity DB wiped (Render SQLite without disk) or wrong password | Deploy Identity with persistent disk (`render.yaml` C-358); re-run signup; update `IDENTITY_SERVICE_PASSWORD` on Vercel |
| `503 Identity database write failed` on signup | `DATABASE_URL` not writable | Wire Render disk at `/var/lib/identity` or managed Postgres |
| `400 IDENTITY_API_BASE is not configured` | CPC env gap | Set on ledger Render service (see [deploy-ledger-c330-c331.md](../deploy-ledger-c330-c331.md)) |
| `400 Email already registered` on signup | Account exists | Use smoke/login only |
| Attest 403 civic_id | Wrong lab_source or civic_id | Use `lab_source: terminal`, `civic_id: mobius-civic-ai-terminal` |
| OAuth login ≠ Mobius Identity | Vercel/GitHub OAuth is separate | Must use `/auth/signup` or `/auth/login` on Identity service |

## What comes next (not this PR)

1. **Spec (C):** Ratify cold/active/service custody model for founders.
2. **Roles (B):** Add `role` / `scope` to Identity so service accounts are attest-only by enforcement.
3. **Fountain:** GI gate (~0.95) is separate from substrate attestation; blocks can immortalize before Fountain unlocks.

## Related

- [MOBIUS_AUTH_CONTRACT.md](./MOBIUS_AUTH_CONTRACT.md)
- [deploy-ledger-c330-c331.md](../deploy-ledger-c330-c331.md)
- Identity service: `identity/README.md`
