# C-379 Item 6 — Wallet DB fix runbook

**Status:** dashboard witness confirmed (2026-07-21) — hypothesis 1 TRUE  
**Service:** `mobius-mic-wallet-service` (`srv-d4r3b4c9c44c73bmh6ng`)

## Witness Table (dashboard check)

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Dashboard `DATABASE_URL` overrides repo SQLite intent | **TRUE** | Render console shows `DATABASE_URL` = `postgresql://…@dpg-d7deg2f41pts73a0djvg-a/…` (credentials redacted) |
| Hostname matches live `/health` error | **TRUE** | `db_error: failed to resolve host 'dpg-d7deg2f41pts73a0djvg-a'` @ 2026-07-21T17:46Z |
| Code hardcodes `dpg-` hostname | **STALE** | `mic-wallet/app/main.py` uses `os.getenv("DATABASE_URL", _DEFAULT_SQLITE_URL)` only |
| Postgres instance still exists | **FALSE** | DNS resolution failure — instance deleted/suspended (C-352 pattern recurrence) |

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
7. Confirm a test wallet write survives redeploy (not just health check)

## Repo change (this PR)

`render.yaml` mic-wallet `DATABASE_URL` aligned with identity service pattern (`sync: false` + comment). Blueprint no longer declares a literal SQLite URL that fights dashboard sync semantics — runtime falls back to `main.py` disk default when unset.

## Rollback

Re-set dashboard `DATABASE_URL` to the recorded Postgres value (will restore degraded state until a fresh Postgres is provisioned).

---

*"We heal as we walk." — Mobius Systems*
