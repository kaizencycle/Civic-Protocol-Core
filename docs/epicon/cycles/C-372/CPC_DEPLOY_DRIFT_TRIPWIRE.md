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
| Post-deploy drift gate | `.github/workflows/cpc-post-deploy-drift-gate.yml` | On `main` push touching ledger; **fails on exit 1**; opens `deploy-drift` GitHub issue |
| Canon smoke | same workflow | After drift OK, curls manifest + verify (must 200) |
| Daily alarm hardening | `.github/workflows/deploy-drift-alarm.yml` | Exit 1 now fails with explicit canon-route message |

## Operator checklist (Render — manual)

Render MCP is not available in cloud agent env. Custodian must:

1. **Create Render Postgres** (Oregon, same region as `civic-ledger-api`)
2. Set `DATABASE_URL` on `civic-ledger-api` service
3. **Manual deploy** current `main`
4. Verify: `python3 scripts/check_deploy_drift.py --url https://civic-protocol-core-ledger.onrender.com` → exit 0
5. **Vercel:** set `CPC_BASE_URL=https://civic-protocol-core-ledger.onrender.com`
6. **Replay anchors:** terminal `replay-canon-anchors` workflow or `node scripts/replay-canon-anchors.mjs`

---

*"We heal as we walk." — Mobius Systems*
