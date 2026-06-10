# Mobius Deploy-Drift Sentinel — Routine Setup

**Builds on:** [C-332 deploy-drift alarm](../deploy-drift-alarm.md)
**CC0 Public Domain**

This is the operational recipe for wiring the C-332 drift checker
(`scripts/check_deploy_drift.py`) into a **Claude Code routine** that
monitors the live Civic Protocol Core Ledger after every deploy. The
routine is read-only: it probes the live deployment, compares it against
`origin/main`, and either reports "no regression" or opens a GitHub issue.
It never merges, commits, pushes, or edits files.

## 1. Routine prompt

Paste the block below into the **Instructions** box at
`claude.ai/code/routines` → New routine.

- Attach repo: `kaizencycle/Civic-Protocol-Core` (default branch `main`)
- Environment / network allowlist: `civic-protocol-core-ledger.onrender.com`,
  `mobius-identity-service.onrender.com`
- No write secrets needed — all probes are read-only.

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

## 2. Firing the routine after a Render deploy

The Claude Code routine fire endpoint:

```
POST https://api.anthropic.com/v1/claude_code/routines/{trigger_id}/fire
Headers:
  Authorization: Bearer {routine_token}          # shown ONCE at token creation — store immediately
  anthropic-beta: experimental-cc-routine-2026-04-01
  anthropic-version: 2023-06-01
  Content-Type: application/json
Body:
  {"text": "<freeform string of run-specific context>"}
```

Response: `{ "claude_code_session_id": "...", "claude_code_session_url": "..." }`.

**The wrinkle:** the `text` field is *freeform text*. If you send arbitrary
JSON, the routine receives it as a literal string — it is not parsed into
fields. Render's native deploy webhook posts its own fixed JSON envelope
(`{"event": "deploy", "data": {...}}`) to whatever URL you give it, and you
cannot tell Render to wrap that as `{"text": ...}`. So pointing Render's
webhook directly at `/fire` sends the wrong shape. Three ways to bridge it,
simplest first.

### Option A — Manual / CI curl (do this first)

Fire the routine by hand after a deploy, or from a GitHub Action step. No
shim, no Render webhook config. This is the right way to validate the
routine works before automating.

```bash
curl -X POST "https://api.anthropic.com/v1/claude_code/routines/$ROUTINE_TRIGGER_ID/fire" \
  -H "Authorization: Bearer $ROUTINE_TOKEN" \
  -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"text": "Manual post-deploy drift check for Civic-Protocol-Core ledger."}'
```

As a GitHub Action (`workflow_dispatch`, or after a deploy workflow):

```yaml
# .github/workflows/fire-drift-routine.yml
name: fire-drift-routine
on:
  workflow_dispatch:
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

### Option B — Tiny shim service (auto-fire on Render deploy)

A small endpoint that Render's deploy webhook POSTs to; it reshapes
Render's envelope into `{"text": ...}` and forwards to `/fire`. Deploy it as
its own small Render/Vercel service. Render webhook → shim → routine.

```python
# shim.py — receives Render deploy webhook, forwards to routine /fire
import os, httpx
from fastapi import FastAPI, Request, HTTPException

app = FastAPI(title="render-to-routine-shim")

ROUTINE_URL = (
    f"https://api.anthropic.com/v1/claude_code/routines/"
    f"{os.environ['ROUTINE_TRIGGER_ID']}/fire"
)
ROUTINE_TOKEN = os.environ["ROUTINE_TOKEN"]
SHIM_SECRET = os.environ.get("SHIM_SECRET")  # optional shared secret in the URL/header

@app.post("/render-deploy")
async def render_deploy(request: Request):
    if SHIM_SECRET and request.headers.get("x-shim-secret") != SHIM_SECRET:
        raise HTTPException(status_code=401, detail="bad shim secret")

    body = await request.json()
    # Render deploy webhook envelope: {"type":"deploy", "data":{"service":..., "status":...}}
    data = (body or {}).get("data", {})
    status = data.get("status") or body.get("type") or "unknown"
    service = (data.get("service") or {}).get("name", "civic-protocol-core-ledger")

    # Only fire on a SUCCESSFUL deploy — drift-checking a failed deploy is noise.
    if status not in ("deploy_succeeded", "live", "succeeded"):
        return {"skipped": True, "status": status}

    text = (
        f"Render deploy succeeded for {service} (status={status}). "
        f"Run the post-deploy drift + ledger-health check now."
    )

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            ROUTINE_URL,
            headers={
                "Authorization": f"Bearer {ROUTINE_TOKEN}",
                "anthropic-beta": "experimental-cc-routine-2026-04-01",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"text": text},
        )
    return {"fired": True, "status": status, "fire_status_code": r.status_code}
```

Render webhook config: Settings → Webhooks → add
`https://<shim-host>/render-deploy`, set `SHIM_SECRET` as a custom header if
enabled. Shim env vars: `ROUTINE_TRIGGER_ID`, `ROUTINE_TOKEN`, `SHIM_SECRET`.

### Option C — GitHub trigger (no API token, no shim)

If deploys are driven by pushes/merges to `main`, add a **GitHub trigger**
to the same routine (requires the Claude GitHub App on the repo). It fires
on `release` published or `push`/PR events and passes the event payload into
context automatically. No token to rotate, no shim to host. Trade-off: it
fires on the GitHub event, not on Render's *deploy-succeeded* signal, so it
may run slightly before the new build is live — the routine's own
UNRESOLVED retry absorbs a not-yet-live service.

## Recommended sequence

1. **Today:** create the routine, add an API trigger, generate + store the
   token, and fire it once with **Option A** (manual curl) against the
   deploy that just landed. Confirm an OK summary. This validates the whole
   loop with zero infrastructure.
2. **Next:** if automatic firing on every deploy is wanted, stand up the
   **Option B** shim — it gives the precise deploy-succeeded trigger.
3. Option C is the fallback if hosting the shim isn't worth it and firing on
   the GitHub event instead of the Render live signal is acceptable.

## Operational notes

- **Token shown once.** Store it immediately; generating a new one revokes
  the old.
- **No idempotency key.** A webhook retry creates *multiple* sessions. The
  shim firing only on `deploy_succeeded` keeps duplicates down — don't add
  aggressive webhook retries.
- **Daily run cap** per account/plan; `/fire` returns
  `429 rate_limit_error` with `Retry-After` when hit. A per-deploy +
  daily-schedule cadence stays well under.
- **Experimental beta header**
  (`experimental-cc-routine-2026-04-01`): shapes may change; the two prior
  header versions keep working, so pin the date and migrate deliberately.
