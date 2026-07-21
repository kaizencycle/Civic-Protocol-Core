# C-379 Item 6 — Wallet DB fix runbook

**Status:** **PARTIAL CLOSEOUT** — connectivity + disk mount ✅ @ 2026-07-21T23:09:47Z; **durability redeploy-survival ⏳ BLOCKING**  
**Service:** `mobius-mic-wallet-service` (`srv-d4r3b4c9c44c73bmh6ng`)

## Witness Table (dashboard check)

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Dashboard `DATABASE_URL` overrides repo SQLite intent | **TRUE** | Render console shows `DATABASE_URL` = `postgresql://…@dpg-d7deg2f41pts73a0djvg-a/…` (credentials redacted) |
| Hostname matches live `/health` error | **TRUE** | `db_error: failed to resolve host 'dpg-d7deg2f41pts73a0djvg-a'` @ 2026-07-21T17:46Z |
| Code hardcodes `dpg-` hostname | **STALE** | `mic-wallet/app/main.py` uses `os.getenv("DATABASE_URL", _DEFAULT_SQLITE_URL)` only |
| Postgres instance still exists | **FALSE** | DNS resolution failure — instance deleted/suspended (C-352 pattern recurrence) |

## Witness update (2026-07-21T19:36Z) — phase 2

Postgres override cleared. New error:

```text
sqlite3.OperationalError: unable to open database file
```

| Claim | Verdict |
|-------|---------|
| Postgres DNS failure | **STALE** — override cleared |
| SQLite path unreachable | **TRUE** — disk mount missing or parent dir not writable |
| Dashboard should set explicit sqlite URL | **OPTIONAL** — prefer **unset** `DATABASE_URL`; let `resolve_database_url()` detect disk |

**Operator checks:**

1. Render → **mobius-mic-wallet-service** → **Disk** — confirm `mic-wallet-data` mounted at `/var/lib/mic-wallet`
2. If payment-failed banner is showing, disk may be unavailable — resolve billing first
3. **Delete** `DATABASE_URL` from dashboard entirely (not just change to sqlite) so code can auto-detect
4. Redeploy after [CPC fix PR] merges (`resolve_database_url` + `ensure_sqlite_parent_dir`, identity pattern)

---

## Operator steps (Render console)

> **Security:** The prior Postgres URL contained live credentials. Rotate or revoke that DB user if the instance is ever restored. Do not commit dashboard secrets to git.

1. Open **mobius-mic-wallet-service** → **Environment** → **Environment Variables**
2. **Record** current `DATABASE_URL` value elsewhere (rollback only — do not paste into public docs)
3. **Delete** `DATABASE_URL` entirely **OR** set to:
   ```
   sqlite:////var/lib/mic-wallet/mic_wallet.db
   ```
4. Confirm **disk** is mounted at `/var/lib/mic-wallet` (Settings → Disk)
5. **Manual Deploy** the service
6. Verify:
   ```bash
   curl -sS https://mobius-mic-wallet-service.onrender.com/health | jq '.status,.db_ok,.db_write_ok,.db_connected'
   ```
   Expect: `ok` / `true` / `true` / `true`
7. **BLOCKING before item 6 full closeout:** confirm a test wallet write survives manual redeploy (not just `/health`). Without this, ephemeral DB false-green is possible if disk is misconfigured ([#98](https://github.com/kaizencycle/Civic-Protocol-Core/pull/98) fail-closed mitigates going forward).

## Phase 3 — connectivity witness (2026-07-21T22:29Z) ✅

```json
{"status":"ok","db_ok":true,"db_write_ok":true,"db_connected":true}
```

Connectivity gate satisfied. Durability gate **open** until redeploy-survival test passes.

## Phase 4 — durability gate (BLOCKING) ⏳

1. Record a test wallet balance or earning event (note `user_id` / amount / timestamp)
2. Manual redeploy `mobius-mic-wallet-service`
3. Re-query balance — must match pre-redeploy
4. Only then mark item 6 **fully closed**

## Phase 5 — #98 fail-closed deploy (2026-07-21T22:47Z) — disk not mounted

Deploy logs after #98 merge:

```text
[DB] DATABASE_URL targets /var/lib/mic-wallet but mount missing — fail closed
[DB] Could not create SQLite parent dir /var/lib/mic-wallet: Permission denied
```

| Claim | Verdict |
|-------|---------|
| #98 fail-closed working | **TRUE** — correctly degraded, no ephemeral false-green |
| Disk mounted at `/var/lib/mic-wallet` | **FALSE** — `/health` `disk_mounted` uses `os.path.ismount()` (not plain `isdir`) |
| Root cause | `mic-wallet/render.yaml` lacked `disk:` block; service on `plan: free` cannot provision disks |

**Operator fix (Render console):**

1. **mobius-mic-wallet-service** → **Settings** → upgrade to **Starter** plan (disks require paid web tier)
2. **Disk** → Add disk `mic-wallet-data`, 1GB, mount `/var/lib/mic-wallet`
3. **Environment** → **Delete** `DATABASE_URL` (let code auto-detect disk)
4. Manual deploy → expect `disk_mounted:true` and `db_ok:true` in `/health`

> The 22:29Z green `/health` likely used ephemeral storage (pre-#98). #98 correctly refuses that path.

## Phase 6 — infrastructure recovery witness (2026-07-21T23:09Z) ✅

```json
{
  "status": "ok",
  "service": "mobius-mic-wallet",
  "db_ok": true,
  "db_write_ok": true,
  "db_connected": true,
  "db_error": null,
  "disk_mounted": true,
  "data_dir": "/var/lib/mic-wallet",
  "timestamp": "2026-07-21T23:09:47.103042"
}
```

| Gate | Verdict |
|------|---------|
| Connectivity | **PASS** |
| Disk mount (`ismount`) | **PASS** |
| Fail-closed (#98) | **PASS** |
| Blueprint disk (#99) | **PASS** |
| Starter plan (#100) | **PASS** |
| Federation disk plans (#101) | **PASS** |
| Write survives redeploy | **BLOCKING** — see Phase 4 |

---

`render.yaml` mic-wallet `DATABASE_URL` aligned with identity service pattern (`sync: false` + comment). Blueprint no longer declares a literal SQLite URL that fights dashboard sync semantics — runtime falls back to `main.py` disk default when unset.

## Rollback

Re-set dashboard `DATABASE_URL` to the recorded Postgres value (will restore degraded state until a fresh Postgres is provisioned).

---

*"We heal as we walk." — Mobius Systems*
