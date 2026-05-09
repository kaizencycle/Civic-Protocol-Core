# Mobius CRON Engine Specification
**EPICON:** C-306 / AUREA / cron-engine-spec
**Status:** Phase 1 — Specification
**Owner:** ECHO (pulse), ATLAS (sentinel gate)
**CC0 Public Domain**

## What It Is

The Mobius CRON Engine is the unified heartbeat of the Substrate mesh. It runs as a long-lived Render worker, wakes on schedule, and orchestrates all agent activity through a single coherent pulse.

## Every 5 Minutes

1. HEARTBEAT        — write ts, cycle, GI to KV
2. SIGNAL_SWEEP     — read 40 instruments via /api/signals/micro
3. AGENT_ACTIVATION — apply deterministic activation conditions (PR-512)
4. BUDGET_GATE      — check daily LLM budget before any inference
5. VAULT_CHECK      — read vault state, check seal eligibility
6. QUORUM_STATE     — read current quorum attestations
7. JOURNAL_SYNC     — flush pending journal entries to substrate
8. ESCALATION_CHECK — evaluate degradation ladder
9. BROKER_TRIGGER   — call thought-broker only if escalation warrants
10. LEDGER_ATTEST   — write heartbeat event to Civic Ledger

## Phase Plan

| Phase | What | Status |
|-------|------|--------|
| 1 | Service Registry + Mesh Gap Map | ✅ This PR |
| 2 | Unified heartbeat endpoint on Terminal | 🔜 PR-512 |
| 3 | Agent lane wiring (ECHO, AUREA, ATLAS...) | 🔜 |
| 4 | Thought Broker bridge (escalation only) | 🔜 |
| 5 | Ledger seal path + replay decision | 🔜 |

## Escalation Ladder

NOMINAL     GI ≥ 0.85 · all agents reporting · vault healthy
↓ GI drops below 0.75
STRESSED    GI 0.70-0.85 · AUREA cautionary posture · Tier-1 agents activate
↓ GI drops below 0.70 OR signal errors > 20%
DEGRADED    GI < 0.70 · ATLAS sentinel activates · Tier-2 LLM calls
↓ quorum not achieved in 2 cycles
STALLED     vault seal blocked · ZEUS escalates · budget check
↓ stalled > 3 cycles
QUORUM_REQUIRED  thought-broker /v1/loop/start fires
↓ thought-broker consensus fails
QUARANTINED operator intervention required
↓ operator resolves
REPLAY      sealed block replayed from ledger history

## Thought Broker Activation Conditions

Only call `/v1/loop/start` when:

- gi_delta_drop_gt: 0.05
- quorum_stall_cycles_gt: 2
- seal_blocked_minutes_gt: 60
- agent_disagreement: true
- signal_error_rate_gt: 0.30
- tripwire_active: true

## Key Rule

The CRON Engine produces the heartbeat.
The Terminal displays the heartbeat.
The Ledger preserves the heartbeat.
The Substrate defines what the heartbeat means.

## Auth Requirements

- TERMINAL_URL
- CRON_SECRET
- CIVIC_LEDGER_URL
- SUBSTRATE_TOKEN
- THOUGHT_BROKER_URL
- BROKER_API_URL
- ANTHROPIC_API_KEY
- DAILY_LLM_BUDGET_USD
