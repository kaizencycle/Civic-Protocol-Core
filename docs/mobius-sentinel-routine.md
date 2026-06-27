# Mobius Deploy-Drift Sentinel — Routine & Wiring

The sentinel is a Claude Code routine that fires after every Render deploy (or on a
schedule) and runs a structured health + drift probe against the live ledger. If
anything fails it opens a GitHub issue and stops — it never modifies code or config.

---

## Routine prompt (paste into claude.ai/code/routines → New routine → Instructions)

```
You are the Mobius deploy-drift sentinel for the Civic Protocol Core Ledger.
You MONITOR and REPORT ONLY. You never merge, commit, push, or modify code.

LIVE_URL = https://civic-protocol-core-ledger.onrender.com
REPO     = kaizencycle/Civic-Protocol-Core (branch main)

MODE A — If the API `text` field contains "DRIFT_CHECK_OUTPUT" with verbatim output
from scripts/check_deploy_drift.py (e.g. fired from GitHub Actions deploy-drift-alarm):
  - Parse that output only. Do NOT curl LIVE_URL and do NOT re-run the drift script.
  - Exit 0 in output → one-paragraph OK summary (include sha/ref from text if present).
  - Exit 1 / lines containing "DRIFT:" → apply the DEDUPE rule below; open an issue
    only if no open sentinel issue exists.
  - Exit 4 / "BLOCKED:" / "Host not in allowlist" → reply one paragraph only; NEVER
    open any issue (known environment limitation tracked in issue #75).
  - Exit 2 UNRESOLVED → note inconclusive; do not treat as drift; do not open issue.
  - Then STOP. MODE A does not run health/route/attest checks — GHA already probed live.

MODE B — If no DRIFT_CHECK_OUTPUT in `text`, run live checks (may be BLOCKED from cloud IP):

1. DRIFT CHECK
   From repo root, run:
     python3 scripts/check_deploy_drift.py --url $LIVE_URL
   Exit codes: 0 = OK, 1 = DRIFT, 2 = UNRESOLVED, 4 = BLOCKED (Render inbound
   IP allowlist rejected the probe with 403).
   If exit 2 (UNRESOLVED), wait 60s and run once more (cold-start tolerance).
   A second UNRESOLVED is reported as UNRESOLVED, NOT as drift.
   If exit 4 (BLOCKED) or any probe returns 403 "Host not in allowlist": STOP.
   Skip the remaining checks — they would also be blocked. Reply one paragraph:
   probe blocked by Render inbound IP allowlist, NOT drift; see issue #75.
   Do NOT open ANY issue — not a drift issue, not a "capability-gap report",
   not an infrastructure note. BLOCKED = reply only.

2. HEALTH + STORAGE (skip if step 1 exited 4)
   curl -sS $LIVE_URL/health
     - HTTP must be 200 and report db connected.
     - Note db_type (expect "sqlite" on the persistent disk today).
   curl -sS $LIVE_URL/ledger/stats
     - Record total_events. total_events: 0 is ACCEPTABLE if no attestation has
       run yet — note it, do not treat 0 alone as failure.

3. ROUTE SURFACE (skip if step 1 exited 4)
   GET $LIVE_URL/openapi.json — path count must be >= 24.
   Spot-check the routes that were missing during the C-332 stale-deploy:
     GET  /api/vault/global        -> expect 200
     POST /api/seal/reconcile {}   -> expect 422 (NOT 404)
     POST /api/epicon/ingest {}    -> expect 422 or 401 (NOT 404)

4. ATTEST PATH (skip if step 1 exited 4; reality-checked for the current build)
   POST $LIVE_URL/ledger/attest with an EMPTY JSON body {} and no Authorization:
     - EXPECT 422 (missing event_type / civic_id / lab_source).
     - The string "No API base configured for terminal" must NEVER appear.
       If it does, IDENTITY_API_BASE regressed — flag it.
   (Do not assert 401 here — a body-less request validates to 422 first. The
    401-vs-400 identity distinction only appears with a full body + token, which
    this read-only probe deliberately does not send.)

DECISION (MODE B):
- If ALL pass: reply with ONE paragraph — drift exit code, route count, db_type,
  total_events, and "no regression." Do nothing else.
- If BLOCKED (drift exit 4, or probes 403 "Host not in allowlist"): reply one
  paragraph and STOP. Never open an issue for BLOCKED — it is a known
  environment limitation tracked in issue #75, not a finding.
- If ANY step fails for a NON-BLOCKED reason (drift exit 1; health not 200;
  any spot-check 404; the "No API base configured" string appears;
  route count < 24):
  first apply the DEDUPE rule below, then (only if no open sentinel issue
  exists) open a GitHub issue in REPO titled:
    "[Mobius] Ledger deploy drift or regression — <UTC date>"
  Body: which check failed + the verbatim curl/script output for that check.
  Labels: exactly mobius-sentinel, ops.
  Then STOP.

ABSOLUTE RULES:
- DEDUPE: before opening ANY issue, search REPO open issues for the title prefix
  "[Mobius] Ledger deploy drift". If one exists, add a comment to the newest
  matching issue instead of opening a new one. ONE open sentinel issue maximum
  at any time. Never file the same finding twice.
- LABELS: when an issue is warranted, apply exactly: mobius-sentinel, ops.
  Do not invent or vary labels between runs.
- BLOCKED (exit 4 / 403 allowlist) NEVER produces an issue of any kind — no
  drift issue, no "capability-gap report", no ops note. Reply only.
- REPORT ONLY. Never merge, commit, push, edit files, or open a PR. Not even for
  an "obvious and small" fix. Open an issue and stop. A wrong unattended change to
  this repo is a canon-integrity event.
- Do not invent diagnoses beyond what the checks return.
- Treat a single UNRESOLVED as cold-start noise, never as drift.

SUCCESS (MODE B) = drift exit 0 AND health 200 AND route count >= 24 AND seal/attest behave
as specified above.

(Optional runtime context: the caller may pass Render deploy metadata, log snippets,
or DRIFT_CHECK_OUTPUT from GitHub Actions in the API `text` field.)
```

---

## Routine setup

1. Open [claude.ai/code/routines](https://claude.ai/code/routines) → **New routine**.
2. Attach repo **kaizencycle/Civic-Protocol-Core** (default branch `main`).
3. Paste the prompt above into the **Instructions** box.
4. **Environment / network allowlist:** `civic-protocol-core-ledger.onrender.com`,
   `mobius-identity-service.onrender.com`. No write secrets needed — all probes are
   read-only.
5. Add an **API trigger**. The token is shown **once** — store it immediately as
   `ROUTINE_TOKEN`. Copy the trigger ID as `ROUTINE_TRIGGER_ID`.

---

## Wiring options (how to fire the routine after a deploy)

**The wrinkle:** the `text` field is *freeform text*. If you send arbitrary JSON,
the routine receives it as a literal string — it does not parse it into fields.
Render's native deploy webhook posts its own fixed JSON envelope
(`{"event":"deploy","data":{...}}`) to whatever URL you configure — you cannot
tell Render to wrap that as `{"text":"..."}`. So pointing Render's webhook
directly at `/fire` sends the wrong shape. Three bridges:

### Option A — Manual or GitHub Actions (simplest; validate first)

Fire by hand or from a CI step. No shim, no Render webhook.

```bash
curl -X POST "https://api.anthropic.com/v1/claude_code/routines/$ROUTINE_TRIGGER_ID/fire" \
  -H "Authorization: Bearer $ROUTINE_TOKEN" \
  -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"text": "Manual post-deploy drift check for Civic-Protocol-Core ledger."}'
```

As a GitHub Action (runs after your deploy job, or on `workflow_dispatch`):

```yaml
# .github/workflows/fire-drift-routine.yml
name: fire-drift-routine
on:
  workflow_dispatch:
  # or: trigger after a deploy workflow completes
jobs:
  fire:
    runs-on: ubuntu-latest
    steps:
      - name: Fire Mobius deploy-drift routine
        env:
          ROUTINE_TRIGGER_ID: ${{ secrets.ROUTINE_TRIGGER_ID }}
          ROUTINE_TOKEN: ${{ secrets.ROUTINE_TOKEN }}
        run: |
          curl -fsS -X POST \
            "https://api.anthropic.com/v1/claude_code/routines/$ROUTINE_TRIGGER_ID/fire" \
            -H "Authorization: Bearer $ROUTINE_TOKEN" \
            -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
            -H "anthropic-version: 2023-06-01" \
            -H "Content-Type: application/json" \
            -d '{"text": "Post-deploy drift check fired from GitHub Actions for '"$GITHUB_SHA"'."}'
```

The workflow `.github/workflows/fire-drift-routine.yml` (already in repo) implements
this with `workflow_dispatch`. Set repo secrets `ROUTINE_TRIGGER_ID` and
`ROUTINE_TOKEN`; trigger the workflow manually or chain it after your deploy job.

The convenience script `scripts/fire_deploy_drift_routine.sh` wraps the same curl
call for local/manual invocation.

### Option B — Render → shim → routine (precise deploy-succeeded trigger)

A small service (`deploy-shim/shim.py`) bridges Render's deploy webhook to `/fire`.
It fires only on `deploy_succeeded` / `live`, so the sentinel runs after the new
build is provably live.

Render deploys this as the **`deploy-drift-shim`** service (`render.yaml`). Set
these env vars on that service:

| Env var | Value |
|---------|-------|
| `ROUTINE_TRIGGER_ID` | From the API trigger (step 5 above) |
| `ROUTINE_TOKEN` | Bearer token shown once at trigger creation |
| `SHIM_SECRET` | Optional shared secret (sent as `x-shim-secret` header) |

Then in Render dashboard → civic-ledger-api → **Settings → Webhooks**, add:
`https://<deploy-drift-shim-host>/render-deploy`

Optionally pass the secret as a custom header `x-shim-secret: <SHIM_SECRET>`.

### Option C — GitHub event trigger (no shim, no API token)

Install the Claude GitHub App on the repo and add a **GitHub trigger** to the
routine (fires on `push` to `main` or `release` published). The event payload is
passed automatically — no token to rotate, no shim to host. Trade-off: fires when
GitHub receives the push, not when Render reports `deploy_succeeded`, so the
sentinel may run slightly before the new build is live. The UNRESOLVED retry in the
routine prompt absorbs a not-yet-live service.

---

## Recommended sequence

1. **Today**: create the routine, add an API trigger, fire once with the Option A
   curl command against the deploy that just landed. Confirm you get a clean summary.
   This validates the whole loop with zero infrastructure.
2. **Next**: if you want it automatic on every deploy, stand up Option B (the shim
   is already deployed in `render.yaml`) for a precise deploy-succeeded trigger.
3. Option C is the fallback if you'd rather avoid hosting the shim and can tolerate
   firing on the GitHub event instead of the Render live signal.

---

## Operational notes

| Topic | Detail |
|-------|--------|
| Token shown once | Store immediately — generating a new token revokes the old one |
| No idempotency | A webhook retry fires multiple sessions; firing only on `deploy_succeeded` keeps duplicates low |
| Rate limits | `/fire` returns `429` with `Retry-After` when the daily cap is hit |
| Beta header | `anthropic-beta: experimental-cc-routine-2026-04-01` — pin the date and migrate deliberately |
| UNRESOLVED (exit 2) | Cold start or outage — inconclusive, not drift. Single retry after 60s; second UNRESOLVED is reported as UNRESOLVED |
| BLOCKED (exit 4) | Render inbound IP allowlist rejected the probe (403). The script exits 4; this is not drift. Run probes from GitHub Actions (allowed IP) or adjust Render inbound rules |

---

## Drift script exit codes

| Code | Meaning |
|------|---------|
| 0 | OK — live matches manifest |
| 1 | DRIFT — missing operations |
| 2 | UNRESOLVED — cold start or outage (inconclusive) |
| 3 | USAGE/IO — bad manifest path or parse error |
| 4 | BLOCKED — Render inbound IP allowlist rejected the probe (inconclusive, not drift) |

---

## Repo artifacts

| File | Role |
|------|------|
| `scripts/check_deploy_drift.py` | Drift probe: compares live OpenAPI to committed manifest |
| `scripts/expected_routes.json` | Committed route manifest (26 operations, 24 paths) |
| `scripts/gen_route_manifest.py` | Regenerate manifest after intentional route changes |
| `scripts/fire_deploy_drift_routine.sh` | Option A convenience wrapper (manual/local) |
| `deploy-shim/shim.py` | Option B: Render deploy webhook → routine `/fire` |
| `deploy-shim/requirements.txt` | Shim dependencies |
| `.github/workflows/fire-drift-routine.yml` | Option A: manual/CI routine fire via `workflow_dispatch` |
| `.github/workflows/deploy-drift-alarm.yml` | Daily local drift check (no routine needed) |
| `render.yaml` | Deploys `deploy-drift-shim` alongside the ledger |
