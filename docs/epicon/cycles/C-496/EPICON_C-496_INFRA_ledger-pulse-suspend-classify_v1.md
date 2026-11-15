---
epicon_id: EPICON_C-496_INFRA_ledger-pulse-suspend-classify_v1
title: "Ledger pulse snapshot — Render suspend classification (JOB-33)"
cycle: "C-496"
status: "intent"
target_repo: "kaizencycle/Civic-Protocol-Core"
created_at: "2026-11-15T20:40:00Z"
version: 1
summary: "Classify Render platform suspend vs in-app degraded health in hourly mesh pulse snapshots without breaking consumer JSON shape."
---

# EPICON C-496 — Ledger pulse suspend classification

## Scope

- `scripts/ledger_pulse_probe.py` — validated HTTPS probes + classification metadata
- `.github/workflows/ledger-pulse-snapshot.yml` — use probe helper; validate `LEDGER_PUBLIC_URL`
- Tests and operator docs for JOB-33 (Render unsuspend); **no** production deploy, disk, DB, or unsuspend

Out of scope: unsuspending Render, ledger persistence repair, merge without EPICON + CI + ZEUS review.

## Evidence

- Live CPC: `x-render-routing: suspend`, HTML 503 (2026-11-15) — platform edge, not FastAPI `/health`
- [ledger/mesh-pulse-snapshot.json](../../../../ledger/mesh-pulse-snapshot.json) recorded generic HTTP 503 only
- JOB-33 ATLAS diagnosis: `HUMAN_PLATFORM_ACTION_REQUIRED`

## EPICON-02 INTENT PUBLICATION

```intent
epicon_id: EPICON_C-496_INFRA_ledger-pulse-suspend-classify_v1
ledger_id: mobius:kaizencycle
scope: infra
mode: normal
issued_at: 2026-11-15T20:40:00Z
expires_at: 2027-02-15T20:40:00Z
justification:
  VALUES INVOKED: integrity, observability, non-fabrication
  REASONING: The recurring ledger-pulse-snapshot workflow is an operational evidence contract. Generic 503 strings obscured Render account/service suspension (`x-render-routing: suspend`) versus in-app degraded JSON `/health`. This intent adds validated HTTPS probes, preserves prior endpoint JSON at the snapshot root, and adds additive classification fields. It does not unsuspend Render, mutate the durable ledger, or claim CPC recovery.
  ANCHORS:
    - docs/epicon/cycles/C-496/CPC_JOB33_ATLAS_DIAGNOSIS.md
    - docs/operations/C-496_CPC_RENDER_UNSUSPEND_RUNBOOK.md
    - ledger/mesh-pulse-snapshot.json
    - .github/workflows/ledger-pulse-snapshot.yml
    - scripts/ledger_pulse_probe.py
  BOUNDARIES: CI probe + snapshot JSON + tests + docs only. No Render dashboard changes, no disk recreate, no DATABASE_URL or LEDGER_DATA_DIR mutation, no production write canary, no merge authority.
  COUNTERFACTUAL: If CPC returns JSON 503 with ledger_db in detail, classification must be app_degraded — not render_suspend. If consumers relied only on nested `body`, this intent keeps endpoint fields at the prior root location.
counterfactuals:
  - If classification is wrong, revert probe helper and workflow wire-up; snapshot returns to prior generic error strings.
  - If LEDGER_PUBLIC_URL is mis-set to a non-HTTPS target, the workflow must fail closed before urlopen.
  - If Render is still suspended, snapshots remain unhealthy; human unsuspend is still required for R1 recovery.
```