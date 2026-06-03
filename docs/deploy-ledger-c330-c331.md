# Deploy runbook: Civic Ledger C-330 + C-331

**Repos:** `kaizencycle/Civic-Protocol-Core` (ledger), `kaizencycle/mobius-civic-ai-terminal` (Terminal)  
**Cycles:** C-330 (attestation / retry semantics), C-331 (ledger durability)  
**Live ledger URL:** `https://civic-protocol-core-ledger.onrender.com`  
**Live identity URL:** `https://mobius-identity-service.onrender.com`  
**Render service (Blueprint):** `civic-ledger-api` (dashboard: *Civic-Protocol-Core Ledger API*)

This runbook sequences the fixes that restore Reserve Block immortality end-to-end. **Deploy disk + identity env in one release** — do not set `IDENTITY_API_BASE` alone while the ledger still writes to `/tmp`.

---

## Verified: Mobius Identity introspection (2026-06-03)

CPC calls `GET {IDENTITY_API_BASE}/auth/introspect` with the same Bearer token as `/ledger/attest`. A 200 on `/` is not sufficient; introspection must respond correctly.

| Request | Expected | Live result |
|---------|----------|-------------|
| `GET /` | 200 | 200 |
| `GET /health` | 200 | 200 |
| `GET /auth/introspect` (no token) | reject | **403** `Not authenticated` |
| `GET /auth/introspect` (dummy bearer) | reject | **401** `Invalid token` |

That 403/401 pattern confirms introspection is wired and validating tokens. It does **not** prove the Terminal sends a token Identity will accept (see [Token-type risk](#token-type-risk-after-deploy) below).

```bash
IDENTITY="https://mobius-identity-service.onrender.com"
curl -sS "$IDENTITY/health"
curl -sS "$IDENTITY/auth/introspect"                    # → 403
curl -sS -H "Authorization: Bearer dummy" "$IDENTITY/auth/introspect"  # → 401
```

---

## Background: two database layers

| Layer | Module | Storage | Env vars |
|-------|--------|---------|----------|
| **Vault** | `ledger/app/database.py` (SQLAlchemy) | PostgreSQL when set, else ephemeral SQLite | `DATABASE_URL` |
| **Core ledger** | `ledger/app/db.py` (raw sqlite3) | **File** at `{LEDGER_DATA_DIR}/ledger.db` | `LEDGER_DATA_DIR` only |

`/ledger/attest`, mesh ingest, epicon, and seal reconciliation all write through **db.py**. Setting `DATABASE_URL` alone does **not** persist events. C-331 adds a Render **persistent disk** and points `LEDGER_DATA_DIR` at it.

---

## Prerequisites

| PR / change | Repo | Status |
|-------------|------|--------|
| Terminal: no false `permanently-failed` on config 400s | mobius-civic-ai-terminal #552 | Merged (C-330) |
| Honest `IDENTITY_API_BASE` 400 + startup warning | Civic-Protocol-Core #31 | Merged |
| Persistent disk + fail-fast guard | Civic-Protocol-Core #32 | **Merge before deploy** |

---

## Single deploy (recommended): disk + identity together

On **Civic-Protocol-Core Ledger API** → Environment, set **both** before one deploy:

```bash
LEDGER_DATA_DIR=/var/lib/ledger
IDENTITY_API_BASE=https://mobius-identity-service.onrender.com
```

(`IDENTITY_SERVICE_URL` is an alias — only one needs to be set. No trailing slash; CPC strips it.)

Blueprint must also declare the disk (PR #32):

```yaml
disk:
  name: ledger-data
  mountPath: /var/lib/ledger
  sizeGB: 1
```

**Why one deploy:** Setting `IDENTITY_API_BASE` while `LEDGER_DATA_DIR` is still `/tmp` removes the config 400 but immortalizes into ephemeral storage — every attest is lost on the next restart. Merge PR #32 (disk + guard) or manually add disk + env, then deploy once.

### Render dashboard checks

1. **Disk** — `ledger-data` at `/var/lib/ledger`.
2. **Environment** — `LEDGER_DATA_DIR=/var/lib/ledger` (override stale `/tmp/ledger_data`).
3. **Environment** — `IDENTITY_API_BASE=https://mobius-identity-service.onrender.com`.
4. **Do not set** `LEDGER_ALLOW_EPHEMERAL` in production.

If deploy **fails to start**:

```text
Ledger data dir is ephemeral in production: '/tmp/ledger_data' ...
```

fix disk mount + `LEDGER_DATA_DIR`, redeploy.

### Post-deploy verification (step 2)

```bash
LEDGER_URL="https://civic-protocol-core-ledger.onrender.com"

curl -sS "$LEDGER_URL/health" | jq .
# Expect: data_dir "/var/lib/ledger" (NOT /tmp/ledger_data)
# event_count may be 0 until reattest — that's OK on first durable deploy

curl -sS "$LEDGER_URL/ledger/stats" | jq '.total_events'
```

**Live pre-C-331 (reference):** `data_dir: /tmp/ledger_data`, `event_count: 0` — confirms persistence + identity env are not yet applied on production.

### Attest smoke (config vs token errors)

```bash
curl -sS -X POST "$LEDGER_URL/ledger/attest" \
  -H "Authorization: Bearer test-token" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "seal.immortalize",
    "civic_id": "mobius-civic-ai-terminal",
    "lab_source": "terminal",
    "payload": {"seal_id": "smoke-test"}
  }' | jq .
```

| Response | Meaning |
|----------|---------|
| 400 + `IDENTITY_API_BASE` in detail | Identity env still unset (PR #31 message) |
| 401 + `Token verification failed` | Identity env OK; bearer is not a valid Identity JWT |
| 200 | Valid token + ledger write succeeded |

Old deploys return 400 `No API base configured for terminal` — redeploy from current `main`.

---

## Token-type risk (after deploy)

After `IDENTITY_API_BASE` is set, the config 400 disappears. The next failure mode is **401** if the Terminal's attest bearer (often `AGENT_SERVICE_TOKEN`) is not a **Mobius Identity JWT** issued by `mobius-identity-service` (e.g. static API key, wrong issuer, expired token).

Introspection proving 403/401 on bad tokens does not prove the Terminal token is valid — only a live attest or reattest cron run does.

### Read the error class (step 4)

| Outcome | Next action |
|---------|-------------|
| Vault headline moves toward full attestation; `event_count` climbs | **Done** for CPC/Render |
| `substrate_attestation_error` / logs show `401 Token verification failed` | Fix on **Terminal**: mint JWT via Identity `/auth/login` (or align token type with what CPC introspects). Not a Render env change |
| Still config 400 | `IDENTITY_API_BASE` not on deployed service or stale image |

Paste `substrate_attestation_error` or note headline change after deploy to classify immediately.

---

## Phase 3 — Terminal reattest (drain the queue)

After CPC deploy, the existing retry / reattest cron (Terminal #552) should:

1. Retry seals that failed with config-class 400s (not `permanently-failed`).
2. POST `/ledger/attest` into the durable ledger.

### Terminal env (confirm)

| Variable | Purpose |
|----------|---------|
| `CIVIC_LEDGER_URL` | `https://civic-protocol-core-ledger.onrender.com` |
| Bearer used for attest | Must be valid Identity JWT if `lab_source=terminal` |
| Other tokens | `docs/operations/MOBIUS_AUTH_CONTRACT.md` |

### What to watch

- **Vault headline** — e.g. `⚠ 3/177` → toward full attestation (hourly cadence).
- **Ledger** — `total_events` on `/ledger/stats`.
- **No new** `permanently-failed` from config 400s (C-330).

### After the queue clears

Remove **`LEGACY_SEAL_KV_RESET_IDS`** (49 entries) from the reattest cron once those seals have re-immortalized.

---

## Rollback and escape hatches

| Situation | Action |
|-----------|--------|
| Local / preview on `/tmp` | `LEDGER_ALLOW_EPHEMERAL=true` (never in production) |
| Roll back C-331 after reattest | Avoid — durable disk may hold real events |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|----------------|-----|
| `data_dir: /tmp/...` | C-331 not deployed | Disk + `LEDGER_DATA_DIR` in **same** deploy as identity |
| 401 after identity set | Token not Identity JWT | Terminal: mint / rotate JWT |
| Old generic 400 | Stale CPC deploy | Redeploy `main` |
| Deploy crash on startup | Ephemeral `LEDGER_DATA_DIR` | Fix mount + env |
| Headline stuck, 401 in logs | `AGENT_SERVICE_TOKEN` ≠ Identity JWT | Terminal auth path |

---

## Follow-up

- **Postgres port of `db.py`** — unify core ledger + vault on `database.py` engine (separate PR).
- **Substrate / mesh registry** — separate if service discovery needs hardening.

---

## Quick checklist

- [ ] PR #32 merged; disk provisioned
- [ ] **One deploy:** `LEDGER_DATA_DIR=/var/lib/ledger` **and** `IDENTITY_API_BASE=https://mobius-identity-service.onrender.com`
- [ ] `/health` shows `data_dir: /var/lib/ledger`
- [ ] Identity introspect smoke (403 / 401) already green on `mobius-identity-service`
- [ ] Trigger reattest / wait for cron
- [ ] Headline + `event_count` improve **or** classify 401 → Terminal JWT fix
- [ ] Remove `LEGACY_SEAL_KV_RESET_IDS` after cleanup

*Observable → Attributed → Agreed → Enforced.*
