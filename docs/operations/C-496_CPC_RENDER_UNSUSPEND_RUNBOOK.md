# C-496 — CPC Render unsuspend runbook (JOB-33)

Use when live CPC returns **HTML 503** with header `x-render-routing: suspend` (not in-app JSON `/health`).

## Symptoms

- `curl https://civic-protocol-core-ledger.onrender.com/health` → HTML “This service has been suspended.”
- `x-render-routing: suspend` on Render-hosted CPC URLs
- EPICON feed same failure
- Mesh pulse snapshot may show generic 503 until [ledger_pulse_probe.py](../../scripts/ledger_pulse_probe.py) ships

## Operator actions (Render dashboard)

1. **Account** — Resolve billing, suspension, or compliance holds on the Render workspace that owns CPC.
2. **Service** — Unsuspend or resume `civic-protocol-core-ledger` (blueprint name `civic-ledger-api` in [render.yaml](../../render.yaml)).
3. **Disk** — Confirm persistent disk `ledger-data` mounted at `/var/lib/ledger` (C-331). Do not delete or recreate the disk without lineage plan.
4. **Environment** — Confirm `LEDGER_DATA_DIR=/var/lib/ledger`. Remove stale overrides (e.g. `/tmp/ledger_data`). **Do not** set `LEDGER_ALLOW_EPHEMERAL` in production.
5. **Deploy** — If service was only suspended, resume may not require redeploy. If env/disk was wrong, fix then manual deploy once.

## Verification (after service is live)

```bash
LEDGER_URL="https://civic-protocol-core-ledger.onrender.com"

curl -sS -D- "$LEDGER_URL/health" -o /tmp/cpc-health.json | grep -E 'HTTP/|x-render-routing'
curl -sS "$LEDGER_URL/health" | jq .

curl -sS "$LEDGER_URL/epicon/feed?limit=10" | jq .

curl -sS "$LEDGER_URL/ledger/stats" | jq '.total_events'
```

**Success criteria:**

- HTTP **200** on `/health` and feed
- Response is **JSON**, not HTML
- `ledger_db.ok: true`, `data_dir` is `/var/lib/ledger`, `ephemeral_storage: false`
- `event_count` / `total_events` **≥ last known durable lineage** (from pre-outage witnesses — a lower count is **not** recovery)

## What this runbook does not do

- No production database repair, migration, or write canary
- No credential rotation (see JOB-35)
- No merge or deploy from JOB-33 diagnostic PR without separate human gates

## References

- [docs/deploy-ledger-c330-c331.md](../deploy-ledger-c330-c331.md)
- [docs/epicon/cycles/C-496/CPC_JOB33_ATLAS_DIAGNOSIS.md](../epicon/cycles/C-496/CPC_JOB33_ATLAS_DIAGNOSIS.md)