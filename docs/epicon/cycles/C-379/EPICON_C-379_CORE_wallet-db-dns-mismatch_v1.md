# EPICON_C-379_CORE_wallet-db-dns-mismatch_v1

**Cycle:** C-379  
**Scope:** core  
**Status:** diagnostic (open)  
**Ticket:** [TICKET_item-6_wallet-db-dns-mismatch.md](./TICKET_item-6_wallet-db-dns-mismatch.md)

## Intent publication

```intent
epicon_id: EPICON_C-379_CORE_wallet-db-dns-mismatch_v1
ledger_id: kaizencycle
scope: core
mode: normal
issued_at: 2026-07-21T15:20:00Z
expires_at: 2026-07-28T15:20:00Z
justification:
  VALUES INVOKED: integrity, transparency, durability
  REASONING: >
    render.yaml declares SQLite; live /health shows Postgres DNS failure on
    dpg-d7deg2f41pts73a0djvg-a. File and runtime disagree. Diagnostic ticket only —
    confirm Render dashboard env before any fix.
  ANCHORS:
    - docs/epicon/cycles/C-379/TICKET_item-6_wallet-db-dns-mismatch.md
    - mic-wallet/app/main.py (os.getenv DATABASE_URL, no hardcoded dpg-)
    - render.yaml mic-wallet DATABASE_URL sqlite path
  BOUNDARIES: mic-wallet DB connectivity only; not ledger /health or canon-lag.
  COUNTERFACTUAL: If no dashboard override, re-diagnose code/env-group paths before clearing vars.
counterfactuals:
  - If tests fail on implementation PR, do not merge
  - If MII drops below 0.95, revert immediately
```
