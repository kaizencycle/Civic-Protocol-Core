#!/usr/bin/env bash
# Fire the Mobius Deploy-Drift Sentinel Claude Code routine (Option A).
# Requires ROUTINE_TRIGGER_ID and ROUTINE_TOKEN from claude.ai/code/routines → API trigger.

set -euo pipefail

: "${ROUTINE_TRIGGER_ID:?Set ROUTINE_TRIGGER_ID (API trigger id from routine UI)}"
: "${ROUTINE_TOKEN:?Set ROUTINE_TOKEN (bearer token shown once at creation)}"

TEXT="${1:-Manual post-deploy drift check for Civic-Protocol-Core ledger.}"

curl -fsS -X POST \
  "https://api.anthropic.com/v1/claude_code/routines/${ROUTINE_TRIGGER_ID}/fire" \
  -H "Authorization: Bearer ${ROUTINE_TOKEN}" \
  -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d "$(TEXT="$TEXT" python3 -c 'import json,os; print(json.dumps({"text": os.environ["TEXT"]}))')"

echo ""
