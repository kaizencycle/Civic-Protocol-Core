# Mobius Deploy-Drift Sentinel — Claude Code Routine

Operational doc for the read-only Claude Code routine that probes the live Civic
Protocol Core Ledger after deploys. Canon rule: **monitor and report only** — never
merge, commit, push, or open PRs from the routine.

## Create the routine

1. Open [claude.ai/code/routines](https://claude.ai/code/routines) → **New routine**.
2. Attach repo **kaizencycle/Civic-Protocol-Core** (default branch `main`).
3. **Environment / network allowlist:** `civic-protocol-core-ledger.onrender.com`,
   `mobius-identity-service.onrender.com`. No write secrets needed.
4. Add an **API trigger**; generate and store the bearer token immediately (shown once).
5. Paste the **Instructions** block below into the prompt field.

## Instructions (paste into routine)

```
You are the Mobius deploy-drift sentinel for the Civic Protocol Core Ledger.
You MONITOR and REPORT ONLY. You never merge, commit, push, or modify code.

LIVE_URL = https://civic-protocol-core-ledger.onrender.com
REPO     = kaizencycle/Civic-Protocol-Core (branch main)

Run these checks in order and collect verbatim output for each:

1. DRIFT CHECK
   From repo root, run:
     python3 scripts/check_deploy_drift.py --url $LIVE_URL
   Exit codes: 0 = OK, 1 = DRIFT, 2 = UNRESOLVED.
   If exit 2 (UNRESOLVED), wait 60s and run once more (cold-start tolerance).
   A second UNRESOLVED is reported as UNRESOLVED, NOT as drift.

2. HEALTH + STORAGE
   curl -sS $LIVE_URL/health
     - HTTP must be 200 and report db connected.
     - Note db_type (expect "sqlite" on the persistent disk today).
   curl -sS $LIVE_URL/ledger/stats
     - Record total_events. total_events: 0 is ACCEPTABLE if no attestation has
       run yet — note it, do not treat 0 alone as failure.

3. ROUTE SURFACE
   GET $LIVE_URL/openapi.json — path count must be >= 24.
   Spot-check the routes that were missing during the C-332 stale-deploy:
     GET  /api/vault/global        -> expect 200
     POST /api/seal/reconcile {}   -> expect 422 (NOT 404)
     POST /api/epicon/ingest {}    -> expect 422 or 401 (NOT 404)

4. ATTEST PATH (reality-checked for the current build)
   POST $LIVE_URL/ledger/attest with an EMPTY JSON body {} and no Authorization:
     - EXPECT 422 (missing event_type / civic_id / lab_source).
     - The string "No API base configured for terminal" must NEVER appear.
       If it does, IDENTITY_API_BASE regressed — flag it.
   (Do not assert 401 here — a body-less request validates to 422 first. The
    401-vs-400 identity distinction only appears with a full body + token, which
    this read-only probe deliberately does not send.)

DECISION:
- If ALL pass: reply with ONE paragraph — drift exit code, route count, db_type,
  total_events, and "no regression." Do nothing else.
- If ANY step fails (drift exit 1; health not 200; any spot-check 404;
  the "No API base configured" string appears; route count < 24):
  open a GitHub issue in REPO titled:
    "[Mobius] Ledger deploy drift or regression — <UTC date>"
  Body: which check failed + the verbatim curl/script output for that check.
  Then STOP.

ABSOLUTE RULES:
- REPORT ONLY. Never merge, commit, push, edit files, or open a PR. Not even for
  an "obvious and small" fix. Open an issue and stop. A wrong unattended change to
  this repo is a canon-integrity event.
- Do not invent diagnoses beyond what the checks return.
- Treat a single UNRESOLVED as cold-start noise, never as drift.

SUCCESS = drift exit 0 AND health 200 AND route count >= 24 AND seal/attest behave
as specified above.

(Optional runtime context: the caller may pass Render deploy metadata or log
snippets in the API `text` field — incorporate it into the issue body if present.)
```

## Fire the routine (Option A — manual or GitHub Actions)

```bash
export ROUTINE_TRIGGER_ID=trig_...   # from routine API trigger UI
export ROUTINE_TOKEN=sk-ant-oat01-... # shown once at token creation

./scripts/fire_deploy_drift_routine.sh
# or with context:
./scripts/fire_deploy_drift_routine.sh "Post-deploy check for commit abc123"
```

GitHub Actions workflow: `.github/workflows/fire-drift-routine.yml` (requires repo
secrets `ROUTINE_TRIGGER_ID` and `ROUTINE_TOKEN`).

## Render deploy → routine (Option B — shim)

Render’s deploy webhook posts a fixed JSON envelope; Claude’s `/fire` endpoint
expects `{"text": "..."}`. A small shim reshapes and forwards:

- **Code:** `scripts/render_routine_shim/app.py`
- **Run:** `uvicorn scripts.render_routine_shim.app:app --host 0.0.0.0 --port $PORT`
- **Env:** `ROUTINE_TRIGGER_ID`, `ROUTINE_TOKEN`, optional `SHIM_SECRET`
- **Webhook URL:** `https://<shim-host>/render-deploy` (optional header `x-shim-secret`)

Only fires on successful deploy statuses (`deploy_succeeded`, `live`, `succeeded`).

## Option C — GitHub trigger on the same routine

Add a **GitHub event** trigger on the routine (PR opened / release published). No API
token or shim; may run slightly before Render is live — the routine’s UNRESOLVED
retry absorbs cold start.

## API reference (Anthropic)

```
POST https://api.anthropic.com/v1/claude_code/routines/{trigger_id}/fire
Headers:
  Authorization: Bearer {routine_token}
  anthropic-beta: experimental-cc-routine-2026-04-01
  anthropic-version: 2023-06-01
  Content-Type: application/json
Body:
  {"text": "<freeform context>"}
```

Response: `claude_code_session_url` for the run transcript.

## Related automation in this repo

| Mechanism | Role |
|-----------|------|
| `.github/workflows/deploy-drift-alarm.yml` | Deterministic drift script (daily + manual); no LLM |
| `.github/workflows/fire-drift-routine.yml` | Fires Claude routine after you wire secrets |
| `scripts/check_deploy_drift.py` | Source of truth for route manifest compare |

The routine adds **interpretation + GitHub issues**; the workflow is the cheap
always-on gate.

## Operational notes

- Token is shown **once**; regenerate revokes the old token.
- No idempotency on `/fire` — webhook retries create duplicate sessions.
- Daily routine run caps apply per plan; per-deploy + daily schedule stays under limits.
- Pin beta header `experimental-cc-routine-2026-04-01`; migrate when Anthropic ships a new dated header.
