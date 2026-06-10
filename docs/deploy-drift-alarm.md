# Deploy-drift alarm (C-332)

The Civic Ledger must expose the same HTTP route surface in production as `origin/main`.
Silent drift (live behind main) caused Terminal calls to `/api/vault/*` and `/api/seal/*` to 404 for multiple cycles while the code on main was correct.

## Artifacts

| File | Role |
|------|------|
| `scripts/expected_routes.json` | Committed manifest (METHOD + path operations from OpenAPI) |
| `scripts/gen_route_manifest.py` | Regenerate manifest after route changes |
| `scripts/check_deploy_drift.py` | Probe a live URL and compare to the manifest |
| `.github/workflows/deploy-drift-alarm.yml` | Daily schedule + manual post-deploy gate |

## Local usage

```bash
# Regenerate manifest after adding/removing routes
LEDGER_ALLOW_EPHEMERAL=true DATABASE_URL='sqlite:////tmp/manifest.db' LEDGER_DATA_DIR=/tmp \
  python3 scripts/gen_route_manifest.py

# Probe production (or any deployment)
python3 scripts/check_deploy_drift.py \
  --url https://civic-protocol-core-ledger.onrender.com
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | OK — live serves every expected HTTP operation (METHOD + path) |
| 1 | DRIFT — reachable but missing operations (redeploy `main`) |
| 2 | UNRESOLVED — cold start or outage (inconclusive, not drift) |
| 3 | Usage / manifest I/O error |

## Post-deploy confirmation

After shipping current `main` to Render (Starter+, disk at `/var/lib/ledger`, `IDENTITY_API_BASE` set):

1. Run the **deploy-drift-alarm** workflow manually (or wait for the daily run).
2. Expect **OK** (exit 0) and `/health` with `data_dir: "/var/lib/ledger"`.
3. Until then, CI correctly reports **DRIFT** with the missing vault/seal/epicon routes.

## Mobius routine sentinel

For an always-on, read-only watcher (a Claude Code routine that runs this
checker plus health/route spot-checks after every deploy and opens an issue
on regression), see
[MOBIUS_DEPLOY_DRIFT_SENTINEL.md](operations/MOBIUS_DEPLOY_DRIFT_SENTINEL.md).
