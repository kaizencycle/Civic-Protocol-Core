#!/usr/bin/env bash
# C-358 — Reset Terminal → Identity service account (ledger attest JWT).
# Prerequisite: Identity service must have writable DATABASE_URL (Render disk or Postgres).
# See render.yaml mobius-identity disk mount + docs/operations/MOBIUS_SERVICE_ACCOUNT_RUNBOOK.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EMAIL="${IDENTITY_SERVICE_EMAIL:-terminal@mobius-substrate.com}"
NAME="${IDENTITY_SERVICE_NAME:-Mobius Civic AI Terminal}"
IDENTITY_BASE="${IDENTITY_API_BASE:-https://mobius-identity-service.onrender.com}"
LEDGER_URL="${CIVIC_LEDGER_URL:-https://civic-protocol-core-ledger.onrender.com}"

PASSWORD_PROVIDED=false
if [[ -n "${IDENTITY_SERVICE_PASSWORD:-}" ]]; then
  PASSWORD_PROVIDED=true
else
  IDENTITY_SERVICE_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"
  echo "Generated IDENTITY_SERVICE_PASSWORD (${#IDENTITY_SERVICE_PASSWORD} chars)"
fi

export IDENTITY_SERVICE_EMAIL="$EMAIL"
export IDENTITY_SERVICE_PASSWORD
export IDENTITY_API_BASE="$IDENTITY_BASE"
export CIVIC_LEDGER_URL="$LEDGER_URL"

echo "==> Health check: $IDENTITY_BASE/health"
HEALTH="$(curl -sf --max-time 15 "$IDENTITY_BASE/health" || echo '{}')"
echo "$HEALTH" | jq . 2>/dev/null || echo "$HEALTH"

if echo "$HEALTH" | jq -e '.db_write_ok == false' >/dev/null 2>&1; then
  echo "ERROR: Identity db_write_ok=false — deploy persistent disk (C-358 render.yaml) before reset." >&2
  exit 1
fi

echo "==> Signup: $EMAIL"
set +e
SIGNUP_OUT="$(python3 scripts/provision_service_account.py signup \
  --email "$EMAIL" \
  --password "$IDENTITY_SERVICE_PASSWORD" \
  --name "$NAME" 2>&1)"
SIGNUP_CODE=$?
set -e
echo "$SIGNUP_OUT"

if [[ $SIGNUP_CODE -eq 2 ]]; then
  if [[ "$PASSWORD_PROVIDED" != "true" ]]; then
    echo "" >&2
    echo "ERROR: Account $EMAIL already exists but IDENTITY_SERVICE_PASSWORD was auto-generated." >&2
    echo "       Signup does not update an existing password hash." >&2
    echo "       Re-run with the current password:" >&2
    echo "         IDENTITY_SERVICE_PASSWORD='...' $0" >&2
    echo "       Or use a fresh email / delete the user in Identity DB before auto-generating." >&2
    exit 2
  fi
  echo "Account already exists — verifying login with supplied password..."
elif [[ $SIGNUP_CODE -ne 0 ]]; then
  echo "Signup failed (exit $SIGNUP_CODE). Fix Identity DB, then re-run." >&2
  exit "$SIGNUP_CODE"
fi

echo "==> Smoke: login → introspect → POST /ledger/attest"
python3 scripts/provision_service_account.py smoke \
  --email "$EMAIL" \
  --password "$IDENTITY_SERVICE_PASSWORD"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Set on Vercel (mobius-civic-ai-terminal → Production):      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo "IDENTITY_SERVICE_EMAIL=$EMAIL"
echo "IDENTITY_SERVICE_PASSWORD=$IDENTITY_SERVICE_PASSWORD"
echo "IDENTITY_API_BASE=$IDENTITY_BASE"
echo "CIVIC_LEDGER_URL=$LEDGER_URL"
echo ""
echo "Then redeploy Terminal and drain backlog:"
echo "  curl -X POST \"https://terminal.mobius-substrate.com/api/cron/reattest-seals\" \\"
echo "    -H \"Authorization: Bearer \$CRON_SECRET\""
