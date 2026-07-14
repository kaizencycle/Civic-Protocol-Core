# C-372 — CPC Deploy Drift Tripwire

**Cycle:** C-372  
**Repo:** `kaizencycle/Civic-Protocol-Core`  
**Trigger:** Reserve block canon immortalization failure (C-371) — live missing 6 routes including all canon endpoints.

---

## Problem

`check_deploy_drift.py` existed and runs daily, but:

- Exit 2 (cold start) / 4 (IP allowlist) **passed silently**
- No immediate gate on `main` pushes to `ledger/**`
- Drift persisted while vault manifest proxy 404'd for weeks

## Shipped mitigations

| Mechanism | File | Behavior |
|-----------|------|----------|
| Post-deploy drift gate | `.github/workflows/cpc-post-deploy-drift-gate.yml` | **`repository_dispatch` (`cpc-deploy-live`)** after Render deploy — not on `push`. Rollout patience retries drift up to ~15 min. Manual `workflow_dispatch` for immediate check. |
| Deploy shim dispatch | `deploy-shim/shim.py` | On `deploy_succeeded`, optionally dispatches `cpc-deploy-live` when `GITHUB_DISPATCH_TOKEN` is set |
| Canon smoke | drift gate workflow | After drift OK, curls manifest + verify (must 200) |
| Daily alarm hardening | `.github/workflows/deploy-drift-alarm.yml` | Exit 1 fails; exit 2/4 warn; exit 3+ preserved via `exit "$code"` |

## Operator checklist (Render — manual)

Render MCP is not available in cloud agent env. Custodian must:

1. **Create Render Postgres** (Oregon, same region as `civic-ledger-api`)
2. Set `DATABASE_URL` on `civic-ledger-api` service
3. **Manual deploy** current `main`
4. Wire **`GITHUB_DISPATCH_TOKEN`** on `deploy-drift-shim` (repo scope PAT) so post-deploy gate auto-fires
5. Verify: `python3 scripts/check_deploy_drift.py --url https://civic-protocol-core-ledger.onrender.com` → exit 0
6. **Vercel:** set `CPC_BASE_URL=https://civic-protocol-core-ledger.onrender.com`
7. **Replay anchors:** terminal `replay-canon-anchors` workflow or `node scripts/replay-canon-anchors.mjs`

---

*"We heal as we walk." — Mobius Systems*
