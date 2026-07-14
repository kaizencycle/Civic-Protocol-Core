---
epicon_id: EPICON_C-372_INFRA_cpc-deploy-drift-tripwire_v1
title: "CPC Post-Deploy Drift Tripwire"
cycle: "C-372"
status: "intent"
target_repo: "kaizencycle/Civic-Protocol-Core"
created_at: "2026-07-14T15:55:00Z"
version: 1
summary: "Post-deploy drift gate for civic-ledger-api — fires after Render deploy_succeeded, not on git push."
---

# EPICON C-372 — CPC Deploy Drift Tripwire

## EPICON-02 INTENT PUBLICATION

```intent
epicon_id: EPICON_C-372_INFRA_cpc-deploy-drift-tripwire_v1
ledger_id: mobius:kaizencycle
scope: infra
mode: normal
issued_at: 2026-07-14T15:55:00Z
expires_at: 2026-10-14T15:55:00Z
justification:
  VALUES INVOKED: integrity, maintainability, non-fabrication
  REASONING: Live civic-ledger-api was missing 6 routes including all canon reserve-block endpoints while main had them registered. Vault manifest proxy 404'd; July 12 anchor POST failed. Daily drift alarm existed but push-triggered probes false-fail during in-flight deploys. This intent adds post-deploy repository_dispatch gate with rollout patience and hardens daily alarm exit semantics.
  ANCHORS:
    - scripts/check_deploy_drift.py
    - scripts/expected_routes.json
    - deploy-shim/shim.py
    - docs/epicon/cycles/C-372/CPC_DEPLOY_DRIFT_TRIPWIRE.md
    - docs/epicon/cycles/C-371/REMEDIATION (terminal) reserve-block canon immortalization
  BOUNDARIES: CI/workflow and deploy-shim dispatch only. Does not provision Render Postgres or redeploy CPC.
  COUNTERFACTUAL: If GITHUB_DISPATCH_TOKEN is not configured on deploy-shim, gate remains manual via workflow_dispatch until custodian wires the token.
counterfactuals:
  - If rollout patience still false-fails during slow Render builds, increase ROLLOUT_ATTEMPTS in workflow.
  - If IP allowlist blocks GitHub Actions probes, exit 4 remains inconclusive (warn, not drift).
```
