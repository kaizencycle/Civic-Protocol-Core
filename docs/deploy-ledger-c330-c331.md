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

If the service **crash-loops on deploy** with a persistence `RuntimeError`:

```text
Ledger data dir is ephemeral in production: '/tmp/ledger_data' ...
```

(or similar from `assert_persistent_storage()` in `ledger/app/db.py`), the disk did not attach or `LEDGER_DATA_DIR` still points at `/tmp`. Check the Render **disk mount** and env — **do not** set `LEDGER_ALLOW_EPHEMERAL` in production to bypass this; that only hides data loss.

### Post-deploy verification (step 2)

Persistence is confirmed by **two** signals, not `data_dir` alone:

1. **Service is up** — `/health` returns **200** (C-331 lifespan guard did not abort boot).
2. **`data_dir` is the mount path** — `"data_dir": "/var/lib/ledger"` (not `/tmp/ledger_data`).

`data_dir` alone is **not** enough: `get_data_dir()` in `db.py` probes writable paths in order (`LEDGER_DATA_DIR` → `/tmp/ledger_data` → `./data` → system temp). If the disk failed to attach but the env var is set, the probe can fall through and land on ephemeral storage — in production, `assert_persistent_storage()` should **refuse to start** instead of serving silently. A healthy 200 from `/health` plus `data_dir: /var/lib/ledger` means the guard passed and the resolved dir is the mount.

```bash
LEDGER_URL="https://civic-protocol-core-ledger.onrender.com"

curl -sS -o /dev/null -w "HTTP %{http_code}\n" "$LEDGER_URL/health"
curl -sS "$LEDGER_URL/health" | jq '.data_dir, .event_count, .db_accessible'

curl -sS "$LEDGER_URL/ledger/stats" | jq '.total_events'
```

- **Pass:** HTTP 200, `data_dir` = `/var/lib/ledger`, `db_accessible: true`.
- **Fail:** crash-loop / no 200 → disk or env; fix mount, redeploy.
- **`event_count: 0`** on first durable deploy is OK until reattest runs.

**Live pre-C-331 (reference):** `data_dir: /tmp/ledger_data`, `event_count: 0` — persistence + identity env not yet on production.

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
| 401 + `Token verification failed` | Identity env OK; see [three-way classification](#three-way-classification-step-4) |
| 200 | Valid token + ledger write succeeded |

Old deploys return 400 `No API base configured for terminal` — redeploy from current `main`.

---

## Token-type risk (after deploy)

After `IDENTITY_API_BASE` is set, the config 400 disappears. The next failures are **401** from CPC's `verify_token()` (`ledger/app/main.py`), which wraps upstream introspection errors:

```python
except httpx.HTTPError as e:
    raise HTTPException(401, f"Token verification failed: {str(e)}") from e
```

The **inner** Identity status (`403` vs `401`) is embedded in that string — classify mechanically from the verbatim `substrate_attestation_error`, not from CPC's outer 401 alone.

Introspection proving 403/401 on bad tokens proves the **server**; only a reattest proves the **Terminal token**.

### Three-way classification (step 4)

After deploy, trigger a seal or wait for reattest cron, then use **one** of:

- Vault headline moved toward full attestation **and** `/ledger/stats` `total_events` climbs, **or**
- Paste **`substrate_attestation_error` verbatim** (include the full `Token verification failed: ...` tail).

| # | Outcome | How to recognize | Next action |
|---|---------|------------------|-------------|
| **A** | **Success** | Headline → attested; `event_count` climbs | **Done** (CPC/Render) |
| **B** | **Missing bearer** | `401 Token verification failed: ...` and the embedded upstream body/status indicates **`403`** / **`Not authenticated`** | Terminal sent **no** (or empty) bearer. `getAgentBearerToken()` returns `''` when both `AGENT_SERVICE_TOKEN` and `RENDER_API_KEY` are unset; the client omits `Authorization` when the token is empty → Identity introspect returns **403 Not authenticated**. Fix: set **`AGENT_SERVICE_TOKEN`** (or the env your attest path uses) on the **Terminal** Vercel/Render service — not JWT minting. |
| **C** | **Wrong-type / invalid JWT** | `401 Token verification failed: ...` and the embedded upstream indicates **`401`** / **`Invalid token`** | Bearer reached introspection but is **not** a valid Mobius Identity JWT (static secret, wrong issuer, expired, etc.). Fix: **Terminal** — mint a real JWT via Identity `/auth/login` (or align token type with what introspection expects). |
| — | **Still config 400** | `detail` names `IDENTITY_API_BASE` or old generic terminal message | CPC deploy/env stale; identity base not live on ledger service |

**Mechanical tell:** search the verbatim error string for Identity's response — `403` / `Not authenticated` → **B**; `401` / `Invalid token` → **C**. Example shapes (wording may vary by httpx version):

```text
Token verification failed: Client error '403 Forbidden' for url '.../auth/introspect' ...
Token verification failed: Client error '401 Unauthorized' for url '.../auth/introspect' ...
```

---

## Phase 3 — Terminal reattest (drain the queue)

After CPC deploy, the existing retry / reattest cron (Terminal #552) should:

1. Retry seals that failed with config-class 400s (not `permanently-failed`).
2. POST `/ledger/attest` into the durable ledger.

### Terminal env (confirm)

| Variable | Purpose |
|----------|---------|
| `CIVIC_LEDGER_URL` | `https://civic-protocol-core-ledger.onrender.com` |
| `AGENT_SERVICE_TOKEN` (or `RENDER_API_KEY` fallback) | Must be **set** (non-empty) and, for terminal attest, a valid Identity JWT — see **B** vs **C** |
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
| Service crash-loop on deploy | Disk not mounted / ephemeral dir in prod | Fix disk mount; do **not** use `LEDGER_ALLOW_EPHEMERAL` |
| `data_dir` correct but no 200 | Boot aborted by guard | Same as crash-loop — check mount + env |
| 401 + inner **403** / Not authenticated | Empty/missing Terminal bearer | Set `AGENT_SERVICE_TOKEN` on Terminal (**B**) |
| 401 + inner **401** / Invalid token | Wrong token type | Terminal: mint Identity JWT (**C**) |
| Old generic 400 | Stale CPC deploy | Redeploy `main` |

---

## Follow-up

- **Postgres port of `db.py`** — unify core ledger + vault on `database.py` engine (separate PR).
- **Substrate / mesh registry** — separate if service discovery needs hardening.

---

## Quick checklist

- [ ] PR #32 merged; disk provisioned
- [ ] **One deploy:** `LEDGER_DATA_DIR=/var/lib/ledger` **and** `IDENTITY_API_BASE=https://mobius-identity-service.onrender.com`
- [ ] `/health` **200** and `data_dir: /var/lib/ledger` (both required)
- [ ] No deploy crash-loop (persistence guard passed)
- [ ] Identity introspect smoke (403 / 401) green on `mobius-identity-service`
- [ ] Trigger reattest / wait for cron
- [ ] **A** success, or verbatim `substrate_attestation_error` classified as **B** (missing env) or **C** (JWT mint)
- [ ] Remove `LEGACY_SEAL_KV_RESET_IDS` after cleanup

*Observable → Attributed → Agreed → Enforced.*
