---
epicon_id: EPICON_C-413_INFRA_cpc-route-manifest-drift_v1
title: "CPC route manifest sort-order reconciliation + identity warning disposition"
cycle: "C-413"
status: "intent"
target_repo: "kaizencycle/Civic-Protocol-Core"
created_at: "2026-08-24T14:00:00Z"
version: 1
summary: "Daily deploy-drift-alarm failed because expected_routes.json was hand-ordered, not because routes changed. Classify IDENTITY_API_BASE CI warning as expected isolation."
---

# EPICON C-413 — CPC Route Manifest Drift

## Scope

Diagnostic repair of the Civic Protocol Core **route manifest selftest** only:

- Re-sort `scripts/expected_routes.json` to match `scripts/gen_route_manifest.py` (lexicographic `METHOD /path`).
- Make `--check` explain additions, removals, and sort-only drift; refuse silent removals.
- Classify the `IDENTITY_API_BASE` import warning as **expected** CI isolation.
- Document that CI must not claim production identity health.

Out of scope: Render dashboard env, credential rotation, production Identity
probes, ledger writes, MIC, seals, deploys.

## Evidence

- Latest failing run: [deploy-drift-alarm #32642266293](https://github.com/kaizencycle/Civic-Protocol-Core/actions/runs/32642266293) (2026-08-23, `main`).
- `manifest-selftest` byte-diffed JSON and failed. `drift-check` was skipped.
- Set comparison of committed vs generated OpenAPI: **32 operations, 0 added, 0 removed, sort_only=true**.
- Hand-insert history: C-355/C-357 appended canon routes beside OAA entries instead of regenerating with `sorted()`.
- Identity warning: `ledger.app.main` RuntimeWarning when `IDENTITY_API_BASE` is unset. Selftest env has no Identity service by design.

Route reorder (same set):

| Committed (stale order) | Generated (`sorted()`) |
|-------------------------|------------------------|
| `GET /api/oaa/memory` before canon GETs | `GET /api/canon/reserve-blocks/*` before OAA GETs |
| `POST /api/canon/reserve-blocks/anchor` after `POST /api/oaa/memory` | `POST /api/canon/reserve-blocks/anchor` before `POST /api/epicon/ingest` |

## Risks

- Regenerating the committed list changes JSON order only; live-vs-manifest drift detection uses **sets**, so production drift semantics do not change.
- Catching the import warning during generation could hide a real misconfiguration if someone later sets a dummy `IDENTITY_API_BASE` in CI. `--check` classifies that case as **misconfigured** and still marks production identity **unattested**.
- Workflow path change classifies **EP-3**; intent must remain in the PR body.

## Counterfactual

- If a later OpenAPI change **adds or removes** a route, `--check` must fail with the named operations — not a sort-only message.
- If live Identity is actually down, this PR will not detect it; a dedicated read-only probe is still required.
- If `sorted()` order ever becomes locale-dependent (it is not: Unicode code points), pin an explicit key function.

## Rollback

Revert this PR. `expected_routes.json` returns to hand order; daily selftest fails again on sort; identity warning returns to unclassified stderr. No runtime ledger or Identity config is changed.

## EPICON-02 INTENT PUBLICATION

```intent
epicon_id: EPICON_C-413_INFRA_cpc-route-manifest-drift_v1
ledger_id: mobius:kaizencycle
scope: infra
mode: normal
issued_at: 2026-08-24T14:00:00Z
expires_at: 2026-11-22T14:00:00Z
justification:
  VALUES INVOKED: integrity, non-fabrication, observability
  REASONING: Daily deploy-drift-alarm has failed since canon routes were hand-inserted into expected_routes.json (C-355/C-357). Generated vs committed is a lexicographic sort of the same 32 operations — zero additions or removals. The IDENTITY_API_BASE RuntimeWarning during selftest is expected CI isolation because the job imports local OpenAPI without Identity credentials; CI must not claim production identity health. This intent regenerates the sorted manifest, explains add/remove/sort in --check, and records an explicit identity disposition.
  ANCHORS:
    - https://github.com/kaizencycle/Civic-Protocol-Core/actions/runs/32642266293
    - scripts/gen_route_manifest.py
    - scripts/expected_routes.json
    - .github/workflows/deploy-drift-alarm.yml
    - docs/epicon/cycles/C-413/EPICON_C-413_INFRA_cpc-route-manifest-drift_v1.md
  BOUNDARIES: Manifest selftest, generator --check, docs, and tests only. Does not deploy, change Render env, rotate credentials, call production Identity mutatively, write the Civic Ledger, issue MIC, or change seals.
  COUNTERFACTUAL: If OpenAPI later adds or removes a route, --check must name those operations and fail; a sort-only correction must not hide a real removal.
counterfactuals:
  - If --check reports a removal after this merge, do not regenerate until the missing route is confirmed intentional; revert this PR if the generator dropped a live operation.
  - If CI is given IDENTITY_API_BASE and operators read that as production identity health, treat it as misconfigured and keep health=unattested.
  - If live Identity is the actual incident, this PR is the wrong fix — add a read-only probe instead of silencing the warning.
```
