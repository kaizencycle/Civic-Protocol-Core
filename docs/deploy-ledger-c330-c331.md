# Deploy runbook: Civic Ledger C-330 + C-331

**Repos:** `kaizencycle/Civic-Protocol-Core` (ledger), `kaizencycle/mobius-civic-ai-terminal` (Terminal)  
**Cycles:** C-330 (attestation / retry semantics), C-331 (ledger durability)  
**Live ledger URL:** `https://civic-protocol-core-ledger.onrender.com`  
**Render service (Blueprint):** `civic-ledger-api` (dashboard name may differ; URL above is canonical)

This runbook sequences the three fixes that restore Reserve Block immortality end-to-end. Do them in order; skipping a step leaves the system looking healthy in the Terminal while the ledger stays empty or attestations keep failing.

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

## Phase 1 — Merge and deploy CPC (C-331)

### 1.1 Merge PR #32

Merge `cursor/c331-ledger-persistence-b3f4` into `main` and let Render auto-deploy (or trigger manual deploy).

Blueprint must include:

```yaml
disk:
  name: ledger-data
  mountPath: /var/lib/ledger
  sizeGB: 1
envVars:
  - key: LEDGER_DATA_DIR
    value: /var/lib/ledger
```

### 1.2 Render dashboard checks

On the **civic-protocol-core-ledger** (or `civic-ledger-api`) service:

1. **Disk** — `ledger-data` mounted at `/var/lib/ledger` (created on first Blueprint apply).
2. **Environment** — `LEDGER_DATA_DIR=/var/lib/ledger` (override any stale `/tmp/ledger_data` from an old dashboard value).
3. **Do not set** `LEDGER_ALLOW_EPHEMERAL` in production (that disables the fail-fast guard).

If deploy **fails to start** with:

```text
Ledger data dir is ephemeral in production: '/tmp/ledger_data' ...
```

the disk mount or `LEDGER_DATA_DIR` is still wrong. Fix dashboard env, redeploy.

### 1.3 Expected: empty ledger after first durable deploy

Previous `/tmp` data is **gone** (ephemeral). After C-331:

- `GET /health` → `200`, ledger DB reachable
- `GET /ledger/stats` → `total_events: 0` until reattest runs

**This is expected**, not a failed migration.

### 1.4 Verify persistence (smoke)

After deploy, from any machine:

```bash
LEDGER_URL="https://civic-protocol-core-ledger.onrender.com"

curl -sS "$LEDGER_URL/health" | jq .

curl -sS "$LEDGER_URL/ledger/stats" | jq '.total_events, .events_by_lab'
```

Redeploy once without writing data; `total_events` should **not** reset to 0 if persistence is correct.

---

## Phase 2 — Set identity introspection (C-330 unblock)

Attestations with `lab_source=terminal` or `identity` call:

```http
GET {IDENTITY_BASE}/auth/introspect
Authorization: Bearer <same token as attest>
```

Set **one** of these on the **ledger** Render service (both are read; first non-empty wins):

| Variable | Example |
|----------|---------|
| `IDENTITY_API_BASE` | `https://mobius-identity.onrender.com` |
| `IDENTITY_SERVICE_URL` | same (alias) |

Use the Mobius Identity service base URL — **no** trailing path, **no** `/auth/introspect` suffix.

### 2.1 Verify the 400 message (post-#31 deploy)

Without a valid token, a misconfigured env should return a **clear** 400 (not the old generic string):

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

- **Before** `IDENTITY_API_BASE` is set: `detail` should mention `IDENTITY_API_BASE` (PR #31).
- **After** it is set: expect `401` (bad token) or `200` (valid token), not config `400`.

If you still see `No API base configured for terminal`, the **deployed** image is older than PR #31 — redeploy from current `main`.

---

## Phase 3 — Terminal reattest (drain the queue)

No Terminal deploy is required for C-331 if #552 is already live. The existing retry / reattest cron will:

1. Retry seals that failed with config-class 400s (C-330: not marked `permanently-failed`).
2. POST `/ledger/attest` once CPC has durable storage + identity base.

### 3.1 Terminal env (confirm)

| Variable | Purpose |
|----------|---------|
| `CIVIC_LEDGER_URL` | `https://civic-protocol-core-ledger.onrender.com` |
| `IDENTITY_SERVICE_EMAIL` / `IDENTITY_SERVICE_PASSWORD` | Service account (OPT-6); see `docs/operations/MOBIUS_SERVICE_ACCOUNT_RUNBOOK.md` |

### 3.2 What to watch

- **Vault headline** — should move from `⚠ 3/177 attested to Substrate` toward full attestation as the queue drains (hourly cron cadence).
- **Ledger** — `total_events` increases on `GET /ledger/stats`.
- **Logs** — CPC should not log ephemeral-storage warnings; Terminal should not spike new `permanently-failed` for 400 config errors.

### 3.3 After the queue clears

In the Terminal reattest cron, remove the **`LEGACY_SEAL_KV_RESET_IDS`** array (49 entries) once those seals have successfully re-immortalized — it was a bridge for stuck KV state during the incident.

---

## Rollback and escape hatches

| Situation | Action |
|-----------|--------|
| Local / preview on `/tmp` | `LEDGER_ALLOW_EPHEMERAL=true` (never in production) |
| Must temporarily run without disk | Not recommended; data loss on restart. Prefer fixing disk + `LEDGER_DATA_DIR`. |
| Roll back C-331 code | Old behavior returns (ephemeral ledger); do not roll back if seals have been re-written to durable disk unless you accept data on disk. |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|----------------|-----|
| `event_count: 0`, `data_dir: /tmp/...` | C-331 not deployed or env override | Disk + `LEDGER_DATA_DIR=/var/lib/ledger` |
| Old 400 `No API base configured for terminal` | Stale deploy | Redeploy `main` (PR #31+) |
| New 400 names `IDENTITY_API_BASE` | Env unset | Set `IDENTITY_API_BASE` or `IDENTITY_SERVICE_URL` |
| Deploy crash on startup | Ephemeral path in prod | Fix `LEDGER_DATA_DIR`; remove mistaken `LEDGER_ALLOW_EPHEMERAL` |
| Vault OK, ledger empty forever | Only `DATABASE_URL` set | Core ledger uses disk path, not Postgres |
| Seals stuck `permanently-failed` | Pre–C-330 Terminal | Ensure Terminal #552 deployed; reset per Terminal ops |

---

## Follow-up (tracked, not this runbook)

- **Postgres port of `db.py`** — unify core ledger + vault on `database.py` engine (`?` → `%s`, `INSERT OR REPLACE` → `ON CONFLICT`, etc.) across 8 modules. Persistent disk remains the floor until that ships.
- **Substrate / mesh registry** — separate change if service discovery for attest paths needs hardening.

---

## Quick checklist

- [ ] PR #32 merged; Render disk provisioned
- [ ] `LEDGER_DATA_DIR=/var/lib/ledger` on ledger service
- [ ] Deploy healthy; no ephemeral startup abort
- [ ] `IDENTITY_API_BASE` or `IDENTITY_SERVICE_URL` set to Mobius Identity base
- [ ] Attest 400/401 behavior matches PR #31 (not old generic message)
- [ ] Terminal `CIVIC_LEDGER_URL` correct
- [ ] `total_events` grows after cron cycles
- [ ] Vault headline approaches 177/177
- [ ] Remove `LEGACY_SEAL_KV_RESET_IDS` after cleanup

*Observable → Attributed → Agreed → Enforced.*
