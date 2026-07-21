# C-379 Item 6 — mic-wallet DB DNS mismatch (Tier 2 diagnostic)

**Cycle:** C-379  
**Type:** Fix / Infra (diagnostic-only — no fix shipped in this ticket)  
**Repo:** `kaizencycle/Civic-Protocol-Core`  
**Backlog origin:** [Mobius-Substrate `OPTIMIZATIONS_C-379_20-items.md`](https://github.com/kaizencycle/Mobius-Substrate/blob/main/docs/epicon/cycles/C-379/OPTIMIZATIONS_C-379_20-items.md) item 6 — escalated from Tier 1 to Tier 2 on 2026-07-21 after live evidence ruled out cold-start spin-down.

## Authority Provenance

Authority declared using `docs/templates/EPICON_FOUNDER_STANDING.md` v0.1 — custodian-issued diagnostic ticket; no production env or code changes in this document.

---

## 1. Summary

**What changed?**

Nothing yet — this is the diagnostic ticket. `mic-wallet` service is degraded: live `/health` reports `db_ok:false`, `db_write_ok:false`, `db_connected:false` with a DNS resolution failure against a Postgres hostname that does not appear anywhere in the repo's `render.yaml`.

**Why?**

Wallet balances currently cannot persist. Every deploy risk noted in the C-360 `render.yaml` comment ("without this, wallet balances reset every deploy") is live right now, except the failure mode is worse than a reset — writes are failing outright, not falling back to disk.

---

## 2. Risk Tier

- [x] **Tier 2** — Auth/ledger/integrity math (2 approvals incl. steward, benchmarks required)

Wallet balance persistence is MIC-ledger-adjacent (reward attestation → wallet write path per `tokenomics.yaml` `reward_accounting.outputs`), so this gets steward review even though the fix itself may end up being a one-line env var change.

---

## 3. EPICON Intent

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
    render.yaml declares DATABASE_URL as a hardcoded local SQLite path
    (sqlite:////var/lib/mic-wallet/mic_wallet.db), but the live service's own error
    message shows it attempting to resolve a Postgres hostname
    (dpg-d7deg2f41pts73a0djvg-a — Render's internal Postgres DNS naming convention).
    The file-declared value and the running value disagree. Until that's reconciled,
    every wallet write is failing, and any fix aimed at "restore the SQLite disk path"
    could be fighting a dashboard-level override that silently wins on every deploy.
  ANCHORS:
    - Live curl of mobius-mic-wallet-service.onrender.com/health, 2026-07-21T15:11:22Z:
      db_error: "failed to resolve host 'dpg-d7deg2f41pts73a0djvg-a'"
    - Civic-Protocol-Core/render.yaml mic-wallet block: DATABASE_URL hardcoded to sqlite path
    - mic-wallet/app/main.py: DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_SQLITE_URL)
    - C-360 comment in render.yaml: "without this, wallet balances reset every deploy"
  BOUNDARIES: >
    This ticket covers only the mic-wallet DB connectivity failure. It does not cover
    Reserve Block canon-lag (C-379 item 3) or ledger /health 404 (C-379 item 13).
  COUNTERFACTUAL: >
    If the Render dashboard env var group shows no Postgres override and the app code
    itself constructs that hostname from some other config, this escalates further —
    it's a code-level bug, not config drift, and the fix path in section 5 changes accordingly.
counterfactuals:
  - If tests fail, do not merge
  - If MII drops below 0.95, revert immediately
  - If the Render dashboard override theory is wrong, do not proceed with "clear override" — re-diagnose per Boundary/Counterfactual before touching production env vars
```

---

## 4. Diagnosis

**Observed (2026-07-21T15:11:22Z, warm request — not cold-start):**

```json
{
  "status": "degraded",
  "service": "mobius-mic-wallet",
  "db_ok": false,
  "db_write_ok": false,
  "db_connected": false,
  "db_error": "(psycopg.OperationalError) failed to resolve host 'dpg-d7deg2f41pts73a0djvg-a': [Errno -2] Name or service not known",
  "timestamp": "2026-07-21T15:11:22.578743"
}
```

**What this tells us:**

- The app is using `psycopg` (Postgres driver), not `sqlite3` — confirming it's not even attempting the SQLite path declared in `render.yaml`.
- `dpg-d7deg2f41pts73a0djvg-a` is Render's standard internal hostname pattern for a managed Postgres instance. At some point a Postgres `DATABASE_URL` was wired to this service — either via the Render dashboard (which can shadow file-declared values) or via an environment group shared with another service.
- The hostname fails to resolve at all — not "connection refused" or "auth failed" — which usually means the referenced Postgres instance has been **deleted or suspended**, not merely misconfigured.
- **C-352 recurrence check:** This DNS failure pattern matches the earlier C-352–C-358 saga where an expired Postgres instance caused a crash-loop on `mobius-mic-wallet-service`. Confirm whether `dpg-d7deg2f41pts73a0djvg-a` is the *same* expired instance resurfacing, not a new incident.

**Repo vs runtime mismatch:**

```yaml
# render.yaml (mic-wallet block) — file declares SQLite, no sync: false
- key: DATABASE_URL
  value: sqlite:////var/lib/mic-wallet/mic_wallet.db
```

```python
# mic-wallet/app/main.py — respects env if set; no hardcoded dpg- hostname in source
DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_SQLITE_URL).strip() or _DEFAULT_SQLITE_URL
```

No `dpg-` string appears in `mic-wallet/` source. If Postgres is in use at runtime, it is almost certainly coming from **runtime env** (dashboard override or env group), not from committed code.

**Two live hypotheses, in order of likelihood:**

1. **Dashboard override survives redeploys.** A Postgres `DATABASE_URL` was set in the Render dashboard at some earlier point (possibly during original C-352 wallet setup, before the SQLite disk fallback in C-360) and never cleared. Note: unlike identity service, mic-wallet's `DATABASE_URL` in `render.yaml` does **not** have `sync: false` — but dashboard values can still persist and take precedence depending on Render's env resolution order.
2. **The referenced Postgres instance was deleted/expired** and nothing updated the env var pointing to it — same root cause pattern as the C-352 wallet crash-loop, possibly a recurrence.

---

## 5. Proposed fix path (decision tree — stop at whichever resolves it)

> **This ticket deliberately stops at diagnosis.** Do not skip step 1. Clearing a dashboard override when hypothesis 2 (code-level construction) is actually correct wastes a deploy cycle on a service that's already degraded.

1. **Check the Render dashboard env var group for `mobius-mic-wallet` directly** (not just the repo file). Confirm whether `DATABASE_URL` is set there and what it points to. Record the current value before any change (rollback).
2. **If a Postgres URL is set in the dashboard:** decide intentionally —
   - **(a)** Clear it so the SQLite disk-backed default in `render.yaml` takes over (matches C-360 intent), **or**
   - **(b)** If Postgres was the actual intended backing store and `render.yaml` is stale, provision a fresh Postgres instance, point the dashboard var at it, and update `render.yaml` + comments so file and reality agree.
3. **If no override exists in the dashboard:** grep `mic-wallet/` and shared env groups for `dpg-` or Postgres URL construction in startup paths not visible from `render.yaml` alone.
4. **Either way, add a startup assertion** (follow-up PR): fail loudly on boot if `DATABASE_URL` doesn't match the intended backing store type (SQLite path vs Postgres URL), rather than surfacing only via degraded `/health` after the fact.

---

## 6. Integrity impact

| Field | Value |
|-------|-------|
| Estimated MII | 0.95 (diagnostic-only; no code shipped yet) |
| Risk level | Medium — wallet balance writes failing; MIC-integrity exposure |
| Systems affected | `mobius-mic-wallet` only |

**What could go wrong:** If the fix is "clear the dashboard override" but the app constructs the Postgres reference elsewhere, clearing does nothing and wastes a deploy cycle. Confirm dashboard state first.

---

## 7. Rollback plan

```bash
# If dashboard override is cleared and it breaks something further:
# re-set DATABASE_URL in Render dashboard to prior Postgres value (record it before clearing)
# No git revert needed if fix is dashboard-only, not code
```

---

## 8. Testing (for whoever implements the fix)

- [ ] Confirm dashboard env var state for `mobius-mic-wallet` (manual, Render console)
- [ ] After fix: `curl https://mobius-mic-wallet-service.onrender.com/health` → expect `db_ok:true`, `db_write_ok:true`, `db_connected:true`
- [ ] Confirm a test wallet write survives a redeploy (not just a live health check)
- [ ] If Postgres path chosen: confirm new instance isn't subject to the same expiration pattern that caused the original C-352 crash-loop

**Evidence:**

```text
2026-07-21T15:11:22Z — GET /health — 200 — degraded — db_error: failed to resolve host 'dpg-d7deg2f41pts73a0djvg-a'
```

---

## 9. Sentinel review

- [x] `review:atlas` — diagnosis methodology, hypothesis ordering
- [x] steward review — required per Tier 2 (MIC-ledger-adjacent write path)

**Notes for Sentinels:** Section 5 is a decision tree because the dashboard-vs-code root cause wasn't confirmed yet. Don't skip straight to "clear the override" without step 1's confirmation.

---

## 10. Dashboard witness (2026-07-21T17:46Z)

**Hypothesis 1 confirmed.** Render console for `mobius-mic-wallet-service` shows `DATABASE_URL` set to a Postgres URL with host `dpg-d7deg2f41pts73a0djvg-a` — matching live `/health` DNS error. Repo `render.yaml` declared SQLite; dashboard override wins at runtime.

**Chosen path:** **5.2(a)** — clear Postgres override; use SQLite on mounted disk per C-360 intent. See [WALLET_DB_FIX_RUNBOOK.md](./WALLET_DB_FIX_RUNBOOK.md).

| Step | Status |
|------|--------|
| Dashboard check | ✅ Confirmed (custodian, 2026-07-21) |
| Dashboard fix + redeploy | ✅ Complete |
| `/health` green | ✅ `db_ok:true` @ 2026-07-21T22:29:11Z (connectivity) |
| Write survives redeploy | ⏳ **BLOCKING** — required before full item 6 closeout (Codex P1) |

**Item 6: PARTIAL CLOSEOUT** — connectivity restored; durability verification pending.

> Codex P1: `/health` alone cannot certify persistent storage. Ephemeral fallback (pre-#98) could report green while balances reset on redeploy. Merge [#98](https://github.com/kaizencycle/Civic-Protocol-Core/pull/98) fail-closed + pass redeploy-survival test before full closure.

---

## Related

- C-379 federation scan witness: [Mobius-Substrate `FEDERATION_SCAN_WITNESS_TABLE.md`](https://github.com/kaizencycle/Mobius-Substrate/blob/main/docs/epicon/cycles/C-379/FEDERATION_SCAN_WITNESS_TABLE.md)
- C-360 disk decision: `render.yaml` mic-wallet block comment
- C-352 wallet crash-loop history (expired Postgres pattern)

*"We heal as we walk." — Mobius Systems*
