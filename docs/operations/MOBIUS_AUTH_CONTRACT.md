# Mobius Auth Contract
**EPICON:** C-306 / DAEDALUS / auth-contract
**CC0 Public Domain**

## Token Map

| Service | Token Name | Permission Level | Used By |
|---------|-----------|-----------------|---------|
| civic-ledger | SUBSTRATE_TOKEN | attest, write, seal | Terminal, CRON Engine |
| thought-broker | CRON_SECRET | loop/start, status | CRON Engine, Terminal |
| broker-api | API_KEY | deliberate, mii | CRON Engine |
| oaa-api-library | OAA_BEARER | sign, verify | Terminal, lab services |
| terminal (Vercel) | CRON_SECRET | internal cron trigger | Render worker |
| mic-gateway | GATEWAY_HMAC_SECRET | token routing | OAA hub |
| Terminal internal | x-internal-cron: 1 | internal route bypass | swarm cron |

## Rules

1. No service calls another service's write endpoint without a valid token
2. Read endpoints may be public (no auth)
3. CRON_SECRET must match on both caller and receiver
4. SUBSTRATE_TOKEN is Render-to-Render only — never exposed client-side
5. All LLM calls use ANTHROPIC_API_KEY scoped to Render worker only
6. Token rotation: quarterly or on any suspected exposure

## Missing / Unset (C-306)

- CIVIC_LEDGER_URL not set in Terminal Vercel env (CRITICAL)
- NEXT_PUBLIC_TERMINAL_URL not set in Terminal Vercel env (CRITICAL)
- SUBSTRATE_TOKEN verify set in Terminal Vercel env
