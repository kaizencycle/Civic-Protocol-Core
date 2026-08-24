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
| `.github/workflows/fire-drift-routine.yml` | Manual/CI fire of the Mobius sentinel routine |
| `deploy-shim/shim.py` | Render webhook → routine `/fire` bridge (Option B) |

See [`docs/mobius-sentinel-routine.md`](mobius-sentinel-routine.md) for the full routine
prompt, Render shim wiring, and operational notes.

## Local usage

```bash
# Check committed manifest against current OpenAPI (CI selftest)
LEDGER_ALLOW_EPHEMERAL=true DATABASE_URL='sqlite:////tmp/manifest.db' LEDGER_DATA_DIR=/tmp \
  python3 scripts/gen_route_manifest.py --check

# Regenerate manifest after adding/removing routes, then commit
LEDGER_ALLOW_EPHEMERAL=true DATABASE_URL='sqlite:////tmp/manifest.db' LEDGER_DATA_DIR=/tmp \
  python3 scripts/gen_route_manifest.py

# Probe production (or any deployment)
python3 scripts/check_deploy_drift.py \
  --url https://civic-protocol-core-ledger.onrender.com
```

`--check` reports additions, removals, and sort-only drift separately. A removal
is never treated as a quiet JSON reorder: the tool prints `REFUSING silent route
removal` and exits 1. Operations are stored in lexicographic `METHOD /path` order.

## IDENTITY_API_BASE during CI selftest

`manifest-selftest` imports `ledger.app.main` without `IDENTITY_API_BASE`. The
import-time RuntimeWarning is **expected CI isolation**, not production identity
drift:

| Signal | Disposition |
|--------|-------------|
| Warning while `IDENTITY_API_BASE` unset in GitHub Actions | **expected** |
| Warning while unset outside CI (local regen) | **degraded** for *this process* only |
| `IDENTITY_API_BASE` set in CI selftest | **misconfigured** (looks like health without a probe) |

CI **does not attest production identity health**. A passing selftest means the
committed OpenAPI list matches local code. Live Identity (`/auth/introspect`)
is a Render-env concern and remains unattested by this workflow until a
dedicated read-only probe exists.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | OK — live serves every expected HTTP operation (METHOD + path) |
| 1 | DRIFT — reachable but missing operations (redeploy `main`) |
| 2 | UNRESOLVED — cold start or outage (inconclusive, not drift) |
| 3 | Usage / manifest I/O error |
| 4 | BLOCKED — Render inbound IP allowlist rejected the probe (inconclusive, not drift) |

## Post-deploy confirmation

After shipping current `main` to Render (Starter+, disk at `/var/lib/ledger`, `IDENTITY_API_BASE` set):

1. Run the **deploy-drift-alarm** workflow manually (or wait for the daily run).
2. Expect **OK** (exit 0) and `/health` with `data_dir: "/var/lib/ledger"`.
3. Until then, CI correctly reports **DRIFT** with the missing vault/seal/epicon routes.

When `ROUTINE_TRIGGER_ID` and `ROUTINE_TOKEN` repo secrets are set, the workflow
fires the Mobius sentinel routine with `DRIFT_CHECK_OUTPUT` (MODE A) before applying
the drift gate — so DRIFT (exit 1) still reaches the routine for issue filing.

## Mobius routine sentinel

For an always-on, read-only watcher (a Claude Code routine that runs this
checker plus health/route spot-checks after every deploy and opens an issue
on regression), see
[MOBIUS_DEPLOY_DRIFT_SENTINEL.md](operations/MOBIUS_DEPLOY_DRIFT_SENTINEL.md).
