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

See [`docs/mobius-sentinel-routine.md`](../mobius-sentinel-routine.md) for the
canonical routine prompt. Copy the text block under **"Routine prompt"** and paste it
into the Instructions field when creating or updating the routine.

The routine runs four ordered checks (drift script, health/storage, route surface,
attest path) and either summarises a clean result in one paragraph or opens a GitHub
issue. It never modifies code or configuration.

**If the Render inbound IP allowlist blocks the routine’s cloud-session IPs** (exit 4
from `check_deploy_drift.py`), the probe is inconclusive — not drift. In that case
run probes from GitHub Actions (allowed IPs) via `.github/workflows/deploy-drift-alarm.yml`
and pass the output in the routine `text` field.

## Fire the routine (Option A — manual or GitHub Actions)

```bash
export ROUTINE_TRIGGER_ID=trig_...
export ROUTINE_TOKEN=sk-ant-oat01-...

# Fire with optional context string
./scripts/fire_deploy_drift_routine.sh "Manual post-deploy check"
```

GitHub Actions: `.github/workflows/deploy-drift-alarm.yml` (deterministic probe) and
`.github/workflows/fire-drift-routine.yml` (API `/fire` only).

## Render deploy → routine (Option B — shim)

Render’s deploy webhook posts a fixed JSON envelope; Claude’s `/fire` expects
`{"text": "..."}`. `deploy-shim/shim.py` bridges the two — it fires only on
`deploy_succeeded` / `live`. See `docs/mobius-sentinel-routine.md` for full setup.

## Option C — GitHub event trigger on the same routine

Fires on push/merge to `main`; no token or shim required. Fires on the GitHub event,
not on Render’s `deploy_succeeded` signal — the UNRESOLVED retry in the routine
absorbs a not-yet-live service.

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
