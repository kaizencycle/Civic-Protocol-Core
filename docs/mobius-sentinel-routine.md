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

MODE A — If the API `text` field contains a section "DRIFT_CHECK_OUTPUT" with
verbatim output from scripts/check_deploy_drift.py (e.g. fired from GitHub Actions):
  - Parse that output only. Do NOT curl LIVE_URL.
  - Exit 0 in output → one-paragraph OK summary.
  - Exit 1 / lines containing "DRIFT:" → open issue "[Mobius] Ledger deploy drift — <UTC date>".
  - Exit 4 / "BLOCKED:" / "Host not in allowlist" → one paragraph: sentinel blocked,
    not drift; do NOT open a drift issue (reference issue #40).
  - Exit 2 UNRESOLVED → note inconclusive; do not treat as drift.

MODE B — If no DRIFT_CHECK_OUTPUT in `text`, run live checks (may fail from cloud IP):

1. DRIFT CHECK
   From repo root, run:
     python3 scripts/check_deploy_drift.py --url $LIVE_URL
   Exit codes: 0 OK, 1 DRIFT, 2 UNRESOLVED, 4 BLOCKED (Render inbound IP allowlist).
   If exit 4: STOP. Reply one paragraph — probe blocked by Render inbound IP allowlist,
     NOT drift; see issue #40. Do NOT open a drift/regression issue.
   If exit 2: wait 60s, run once more. Second UNRESOLVED → inconclusive, NOT drift.

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
- If ANY step fails (drift exit 1; health not 200; any spot-check 404;
  the "No API base configured" string appears; route count < 24):
  open a GitHub issue in REPO titled:
    "[Mobius] Ledger deploy drift or regression — <UTC date>"
  Body: which check failed + the verbatim curl/script output for that check.
  Then STOP.
- Exit 4 (BLOCKED) or 403 body containing "allowlist": BLOCKED — NOT drift.
  Reply one paragraph; do NOT open a drift issue.

ABSOLUTE RULES:
- REPORT ONLY. Never merge, commit, push, edit files, or open a PR. Not even for
  an "obvious and small" fix. Open an issue and stop. A wrong unattended change to
  this repo is a canon-integrity event.
- Do not invent diagnoses beyond what the checks return.
- Treat a single UNRESOLVED as cold-start noise, never as drift.
- Treat exit 4 / Render 403 allowlist blocks as BLOCKED, never as drift.

SUCCESS (MODE B) = drift exit 0 AND health 200 AND route count >= 24 AND seal/attest
behave as specified above.

(Optional runtime context: the caller may pass Render deploy metadata, log snippets,
or DRIFT_CHECK_OUTPUT from GitHub Actions in the API `text` field.)
```

---

## Routine setup

1. Go to **claude.ai/code/routines → New routine**.
2. Attach repo **kaizencycle/Civic-Protocol-Core** (default branch `main`).
3. Paste the prompt above into the **Instructions** box.
4. Network allowlist: `civic-protocol-core-ledger.onrender.com`,
   `mobius-identity-service.onrender.com`. No write secrets needed — all probes
   are read-only.
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

The workflow `.github/workflows/fire-drift-routine.yml` implements this with
`workflow_dispatch`. Set repo secrets `ROUTINE_TRIGGER_ID` and `ROUTINE_TOKEN`,
then trigger the workflow manually or chain it after your deploy job.

**MODE A pass-through (recommended when GitHub Actions IPs can reach Render):**
`.github/workflows/deploy-drift-alarm.yml` now captures the drift check output
and fires the routine with a `DRIFT_CHECK_OUTPUT` section in the `text` field —
so the routine processes the pre-computed result (MODE A) instead of re-running
the probe from a cloud IP that Render may block. Set `ROUTINE_TRIGGER_ID` and
`ROUTINE_TOKEN` repo secrets; the fire step is skipped if the secrets are absent.

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
sentinel may run slightly before the new build is live. The UNRESOLVED retry in
the routine prompt absorbs a not-yet-live service.

---

## Recommended sequence

1. **Validate now**: create the routine, add an API trigger, fire once with the
   Option A curl command against the deploy that just landed. Confirm you get a
   clean summary.
2. **Automate**: stand up Option B (the shim is already deployed in `render.yaml`)
   for a precise deploy-succeeded trigger.
3. Option C is the fallback if you want to avoid hosting the shim.

---

## Operational notes

| Topic | Detail |
|-------|--------|
| Token shown once | Store immediately — generating a new token revokes the old one |
| No idempotency | A webhook retry fires multiple sessions; firing only on `deploy_succeeded` keeps duplicates low |
| Rate limits | `/fire` returns `429` with `Retry-After` when the daily cap is hit |
| Beta header | `anthropic-beta: experimental-cc-routine-2026-04-01` — pin the date and migrate deliberately |
| Drift vs. UNRESOLVED | Exit 1 = real drift (redeploy main). Exit 2 = cold start or outage (inconclusive). Exit 4 = Render inbound IP allowlist blocked the probe (also inconclusive — NOT drift; see issue #40) |
| Cloud IP block | Claude Code routine cloud sessions use unstable egress IPs that Render's allowlist often rejects with 403. Use MODE A (pass GHA `DRIFT_CHECK_OUTPUT`) or run the `deploy-drift-alarm` GHA workflow for reliable probing |
| MODE A wiring | `deploy-drift-alarm.yml` captures drift output and fires the routine with `DRIFT_CHECK_OUTPUT` in `text` when `ROUTINE_TRIGGER_ID`/`ROUTINE_TOKEN` secrets are set — the routine then processes the pre-computed result rather than re-probing from a blocked cloud IP |

---

## Repo artifacts

| File | Role |
|------|------|
| `scripts/check_deploy_drift.py` | Drift probe: compares live OpenAPI to committed manifest |
| `scripts/expected_routes.json` | Committed route manifest (26 operations, 24 paths) |
| `scripts/gen_route_manifest.py` | Regenerate manifest after intentional route changes |
| `deploy-shim/shim.py` | Option B shim: Render webhook → routine `/fire` |
| `deploy-shim/requirements.txt` | Shim dependencies |
| `.github/workflows/fire-drift-routine.yml` | Option A: manual/CI routine fire |
| `.github/workflows/deploy-drift-alarm.yml` | Daily local drift check (no routine needed) |
| `render.yaml` | Deploys `deploy-drift-shim` alongside the ledger |
