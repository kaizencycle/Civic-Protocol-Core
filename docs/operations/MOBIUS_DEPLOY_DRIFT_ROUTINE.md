# Mobius Deploy-Drift Sentinel — Claude Code Routine

Operational doc for the read-only Claude Code routine that probes the live Civic
Protocol Core Ledger after deploys. Canon rule: **monitor and report only** — never
merge, commit, push, or open PRs from the routine.

## Network topology (read first)

Render **inbound IP rules** allowlist who may call your web service from the public
internet. Disallowed clients get **HTTP 403** with a body like `Host not in allowlist`
(see [Render inbound IP rules](https://render.com/docs/inbound-ip-rules)).

**Claude Code routine cloud sessions** use Anthropic-managed egress IPs. Those IPs are
**not** stable and usually **cannot** be allowlisted on Render. If the routine curls
the ledger directly, you will see persistent 403s — **not deploy drift**, not cold
start. Issue [#40](https://github.com/kaizencycle/Civic-Protocol-Core/issues/40) is
this failure mode.

| Runner | Can curl live ledger? | Role |
|--------|------------------------|------|
| Claude routine (cloud) | Often **no** (403 allowlist) | Interpretation + issues when given GHA output |
| GitHub Actions `deploy-drift-alarm` | Usually **yes** | Deterministic drift script |
| Your laptop / Terminal / Render health | **yes** (if allowed) | Manual verification |

**Recommended architecture:** GHA runs `check_deploy_drift.py` → on exit `1` (DRIFT),
fire the routine via API with the **verbatim script output** in `text`. The routine
**parses that output** and opens an issue — it does not need to curl the ledger.

Do **not** widen inbound rules to `0.0.0.0/0` unless you intend a public API. If the
ledger is intentionally IP-restricted, keep it restricted and run probes only from
allowed networks (GHA static IP, office CIDR, same Render private network).

## Create the routine

1. Open [claude.ai/code/routines](https://claude.ai/code/routines) → **New routine**.
2. Attach repo **kaizencycle/Civic-Protocol-Core** (default branch `main`).
3. **Environment / network allowlist:** `civic-protocol-core-ledger.onrender.com`,
   `mobius-identity-service.onrender.com` (only matters if the routine curls live).
4. Add an **API trigger**; generate and store the bearer token immediately (shown once).
5. Paste the **Instructions** block below into the prompt field.

## Instructions (paste into routine)

```
You are the Mobius deploy-drift sentinel for the Civic Protocol Core Ledger.
You MONITOR and REPORT ONLY. You never merge, commit, push, or modify code.

LIVE_URL = https://civic-protocol-core-ledger.onrender.com
REPO     = kaizencycle/Civic-Protocol-Core (branch main)

MODE A — If the API `text` field contains a section "DRIFT_CHECK_OUTPUT" with
verbatim output from scripts/check_deploy_drift.py (e.g. fired from GitHub Actions):
  - Parse that output only. Do NOT curl LIVE_URL.
  - Exit 0 in output → one-paragraph OK summary.
  - Exit 1 / lines containing "DRIFT:" → open issue "[Mobius] Ledger deploy drift — <UTC date>".
  - Exit 4 / "BLOCKED:" / "Host not in allowlist" → one paragraph: sentinel blocked,
    not drift; do NOT open a drift issue (reference #40).
  - Exit 2 UNRESOLVED → note inconclusive; do not treat as drift.

MODE B — If no DRIFT_CHECK_OUTPUT in `text`, run live checks (may fail from cloud IP):

1. DRIFT CHECK
     python3 scripts/check_deploy_drift.py --url $LIVE_URL
   Exit codes: 0 OK, 1 DRIFT, 2 UNRESOLVED, 4 BLOCKED (Render inbound IP allowlist).
   If exit 4: STOP. Reply one paragraph — probe blocked, NOT drift, see issue #40.
     Do NOT open a drift/regression issue.
   If exit 2: wait 60s, run once more. Second UNRESOLVED → inconclusive, NOT drift.

2. HEALTH + STORAGE (skip if step 1 exited 4)
   curl -sS $LIVE_URL/health → 200, db connected; note db_type.
   curl -sS $LIVE_URL/ledger/stats → record total_events (0 alone is OK).

3. ROUTE SURFACE
   GET $LIVE_URL/openapi.json — paths >= 24.
   GET /api/vault/global → 200; POST /api/seal/reconcile {} → 422 not 404;
   POST /api/epicon/ingest {} → 422 or 401 not 404.

4. ATTEST PATH
   POST $LIVE_URL/ledger/attest {} no Authorization → 422.
   "No API base configured" must NEVER appear.

DECISION (MODE B only):
- ALL pass → one paragraph OK; no issue.
- drift exit 1 OR spot-check 404 OR route count < 24 OR identity regression string:
  open "[Mobius] Ledger deploy drift or regression — <UTC date>" with verbatim output.
- 403 body contains "allowlist" / drift exit 4: BLOCKED — no drift issue.

ABSOLUTE RULES: REPORT ONLY. No commits, PRs, or file edits. No invented diagnoses.
```

## Fire the routine (Option A — manual or GitHub Actions)

```bash
export ROUTINE_TRIGGER_ID=trig_...
export ROUTINE_TOKEN=sk-ant-oat01-...

# Prefer: pass GHA drift output (MODE A)
DRIFT_OUT="$(python3 scripts/check_deploy_drift.py --url https://civic-protocol-core-ledger.onrender.com 2>&1)" || true
./scripts/fire_deploy_drift_routine.sh "DRIFT_CHECK_OUTPUT:
$DRIFT_OUT"

# Or context-only (MODE B — may hit 403 from cloud)
./scripts/fire_deploy_drift_routine.sh "Manual post-deploy check"
```

GitHub Actions: `.github/workflows/deploy-drift-alarm.yml` (deterministic probe) and
`.github/workflows/fire-drift-routine.yml` (API `/fire` only).

## Render deploy → routine (Option B — shim)

Render’s deploy webhook posts a fixed JSON envelope; Claude’s `/fire` expects
`{"text": "..."}`. Use `scripts/render_routine_shim/app.py` only after GHA drift
passes, or teach the shim to call GHA — do not assume the routine can curl the ledger.

## Option C — GitHub trigger on the same routine

Fires on merge/PR; still subject to MODE B network limits unless you chain GHA output.

## Drift script exit codes

| Code | Meaning |
|------|---------|
| 0 | OK — live matches manifest |
| 1 | DRIFT — missing operations |
| 2 | UNRESOLVED — cold start / outage |
| 3 | USAGE/IO — bad manifest |
| 4 | BLOCKED — Render inbound IP allowlist (403); **not drift** |

## Related automation

| Mechanism | Role |
|-----------|------|
| `.github/workflows/deploy-drift-alarm.yml` | Canonical live probe (GitHub runner) |
| `.github/workflows/fire-drift-routine.yml` | Fire routine with secrets |
| `scripts/check_deploy_drift.py` | Drift + allowlist detection |

## Operational notes

- Close [#40](https://github.com/kaizencycle/Civic-Protocol-Core/issues/40) when the
  routine uses MODE A or GHA-only probes — production was not proven broken.
- Routine `/fire` token shown once; no idempotency on retries.
- Beta header: `experimental-cc-routine-2026-04-01`.
