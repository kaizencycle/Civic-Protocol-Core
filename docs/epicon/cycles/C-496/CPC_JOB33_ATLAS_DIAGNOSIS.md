# C-496 JOB-33 — CPC durable ledger diagnosis (ATLAS)

**Cycle:** C-496 · **Job:** JOB-33 · **Steward:** ATLAS · **Reviewer:** ZEUS  
**Repository:** [kaizencycle/Civic-Protocol-Core](https://github.com/kaizencycle/Civic-Protocol-Core)  
**Notion:** [JOB-33](https://app.notion.com/p/41993f6e20a18190b327c3b7bdf87216)  
**Captured (UTC):** 2026-11-15T16:52Z · **Captured (America/New_York):** 2026-11-15 11:52 AM EST

---

## 1. Preflight state

| Check | Result |
|-------|--------|
| Repository | `kaizencycle/Civic-Protocol-Core` — workspace matches remote |
| Branch (start) | `main` @ `6fbace1` — clean working tree |
| Remotes | `origin` → GitHub |
| Overlapping open PRs | **None** |
| `AGENTS.md` | **Absent** (not in scope to invent) |
| `BUILD.md` | **Absent** |
| PR template | **Absent** — use [CONTRIBUTING.md](../../../../CONTRIBUTING.md) + Mobius PR format |
| Docs read | [README.md](../../../../README.md), [DEPLOYMENT.md](../../../../DEPLOYMENT.md), [mobius.yaml](../../../../mobius.yaml), [render.yaml](../../../../render.yaml), [docs/deploy-ledger-c330-c331.md](../../../deploy-ledger-c330-c331.md) |

---

## 2. Root-cause classification

| Category | Applies |
|----------|---------|
| **Platform / account suspension** | **YES — primary** |
| Application startup or runtime failure | No evidence (traffic does not reach app) |
| Persistent-disk mount or path failure | Not observable while suspended |
| Database initialization or migration failure | Not observable while suspended |
| Health-route failure (in-app JSON 503) | No — would return JSON `detail`, not HTML |
| EPICON projection/ingestion failure | No — same platform block |
| Networking or dependency failure | No — Render edge returns explicit `suspend` |

**Verdict:** `HUMAN_PLATFORM_ACTION_REQUIRED` — restore Render service/account; **no repository deploy fixes the outage.**

---

## 3. Evidence inspected

**Live probes (copies under agent artifacts `c496-job33/`):**

| Endpoint | HTTP | `x-render-routing` | Body |
|----------|------|-------------------|------|
| `/health` | 503 | `suspend` | HTML “This service has been suspended.” |
| `/epicon/feed?limit=10` | 503 | `suspend` | Same HTML |

**Related scope:** `mobius-mic-wallet-service.onrender.com/health` → 503 `suspend`.

**Committed pulse before this job:** [ledger/mesh-pulse-snapshot.json](../../../../ledger/mesh-pulse-snapshot.json) — generic `HTTP Error 503` only (misleading vs `render_suspend`).

**Code paths reviewed (not exercised in prod while suspended):**

- [ledger/app/main.py](../../../../ledger/app/main.py) `/health` — 503 only when vault or ledger SQLite probe fails; returns JSON.
- [ledger/app/routes/epicon.py](../../../../ledger/app/routes/epicon.py) — EPICON feed/query.
- [ledger/app/db.py](../../../../ledger/app/db.py) — `LEDGER_DATA_DIR`, `assert_persistent_storage`, `get_db_connection`.
- [scripts/render_start_ledger.py](../../../../scripts/render_start_ledger.py) — uvicorn entry.
- [.github/workflows/ledger-pulse-snapshot.yml](../../../../.github/workflows/ledger-pulse-snapshot.yml) — hourly public probe.

---

## 4. Persistence and database-path findings

| Item | Production expectation |
|------|------------------------|
| Render disk | `ledger-data` |
| Mount path | `/var/lib/ledger` |
| Env | `LEDGER_DATA_DIR=/var/lib/ledger` |
| Core ledger file | `/var/lib/ledger/ledger.db` (sqlite3 in `db.py`) |
| Vault layer | Separate SQLAlchemy layer via optional `DATABASE_URL` — **does not** store core attest events |

**Startup guards:** FastAPI lifespan calls `assert_persistent_storage(DATA_DIR)` — refuses ephemeral dirs in production ([C-331 deploy runbook](../../../deploy-ledger-c330-c331.md)).

**Silent empty DB risk:** `CREATE TABLE IF NOT EXISTS` on first connect can initialize an empty ledger on a **new** writable path. After unsuspend, operators must confirm `data_dir`, `ephemeral_storage: false`, and **event count ≥ last known lineage** — a lower count is an incident.

**This job did not** read production disk identity or event count (service unreachable).

---

## 5. Files changed

| Path | Change |
|------|--------|
| [scripts/ledger_pulse_probe.py](../../../../scripts/ledger_pulse_probe.py) | Classify `render_suspend` vs `app_degraded` vs `ok` |
| [tests/test_ledger_pulse_probe.py](../../../../tests/test_ledger_pulse_probe.py) | Focused classification tests |
| [.github/workflows/ledger-pulse-snapshot.yml](../../../../.github/workflows/ledger-pulse-snapshot.yml) | Use probe helper in snapshot job |
| [docs/operations/C-496_CPC_RENDER_UNSUSPEND_RUNBOOK.md](../../../operations/C-496_CPC_RENDER_UNSUSPEND_RUNBOOK.md) | Operator checklist |
| This document | JOB-33 evidence packet for ZEUS |

---

## 6. Tests run and exact results

```text
python3 tests/test_persistence_guard.py
  PASS: 6/6 checks passed

python3 -m pytest tests/test_get_data_dir.py tests/test_persistence_guard.py \
  tests/test_c339_ledger_hardening.py tests/test_route_manifest.py -q
  24 passed, 2 warnings in 0.56s

python3 -m pytest tests/test_ledger_pulse_probe.py -q
  (run on branch before push)
```

---

## 7. Draft PR or proposed patch

Branch: `cursor/c496-job33-render-suspend-diagnostic-8197`  
**Draft PR** — diagnostic only; does not unsuspend Render or deploy ledger fixes.

---

## 8. Remaining risks

- Ledger **lineage unproven** until `/health` and `/ledger/stats` return JSON after unsuspend.
- Terminal GI 0.64 / `gi_verified:false` may persist until CPC is live — do not average conflicting GI projections.
- JOB-34 (OAA), JOB-36 (federation map) remain blocked on R1 recovery.
- Pulse snapshots may continue showing suspend until platform recovery (after merge: snapshots label `render_suspend` explicitly).

---

## 9. Human action required

See [C-496_CPC_RENDER_UNSUSPEND_RUNBOOK.md](../../../operations/C-496_CPC_RENDER_UNSUSPEND_RUNBOOK.md).

**Summary:** Log into Render → unsuspend / restore billing for `civic-protocol-core-ledger` (`civic-ledger-api` in blueprint) → confirm disk `ledger-data` at `/var/lib/ledger` → verify with curls (JSON 200, event count not regressed). **Do not** set `LEDGER_ALLOW_EPHEMERAL` or point `LEDGER_DATA_DIR` at `/tmp` in production.

---

## 10. Explicit confirmation

| Gate | Value |
|------|-------|
| merged | **no** |
| deployed | **no** |
| database mutated | **no** |
| execution authority granted | **no** |

*ATLAS badge authorizes this bounded diagnosis and proposal only — not production, merge, deployment, or durable-data mutation.*