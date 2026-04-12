# CURRENT_CYCLE.md — C-278
> **Last verified:** 2026-04-12T01:10Z by ATLAS (kaizencycle)
> **Snapshot commit:** `9b828b4` — fix(journal): read cycle-scoped KV keys
> **Production URL:** https://mobius-civic-ai-terminal.vercel.app
> **Vercel project:** `prj_ru2eaIzY0nIamFIXEdUIuTjnefpn` · team `team_cEncfJHYpxuB6YiFQNwdOUB5`

---

## ⚠️ READ THIS FIRST — FOR ALL AGENTS (Cursor, Codex, Claude Code)

This file is the **ground truth** for the current state of the Terminal repo.
Before making any change, read this file in full.
If your task conflicts with a LOCKED entry, **stop and ask the operator**.
If your task describes fixing something in the EXPECTED EMPTY section, **do not proceed** — it is not a bug.

---

## ✅ LANE STATUS (as of last snapshot)

| Lane | State | Note |
|------|-------|------|
| signals | healthy | GAIA, HERMES-µ, THEMIS, DAEDALUS-µ all live |
| kvHealth | healthy | Upstash reachable, 240ms latency |
| agents | **healthy** | All 8 agents showing `status: active` via KV heartbeat |
| echo | healthy | 9 EPICONs rated and ledgered |
| journal | healthy | 2 EVE entries via substrate archive |
| sentiment | healthy | 6 domains live |
| promotion | healthy | 6 pending promotable |
| eve | healthy | C-278 in sync |
| integrity | stale/cached | GI 0.74, mode: yellow — cached, not degraded |
| epicon | empty | `kv: 0` — see EXPECTED EMPTY below |
| runtime | stale | Last commit 01:17Z — cron hasn't fired since |

---

## 🔒 LOCKED — DO NOT MODIFY WITHOUT OPERATOR APPROVAL

These behaviors are confirmed working. Any PR that touches these files **must**
explicitly state in the PR description why the change is safe.
If you are unsure, **stop**.

### 1. Journal KV key schema
- **File:** `app/api/agents/journal/route.ts`
- **What:** Route reads keys matching `journal:{AGENT}:{CYCLE}` (3 segments, uppercase agent, e.g. `journal:EVE:C-278`)
- **Fixed in:** PR #248
- **Why locked:** Agents write to this exact schema. Changing the reader breaks the entire journal lane.
- **DO NOT:** Change to `journal:all`, `journal:eve`, or any 2-segment schema. Do not reintroduce list-based `lrange` lookups.

### 2. ECHO → `epicon:feed` KV bridge
- **File:** `app/api/echo/ingest/route.ts`
- **What:** After ECHO rates EPICONs, it LPUSHes completed entries into the `epicon:feed` KV key and LTRIMs to 100
- **Fixed in:** PR #246
- **Why locked:** This is the only path for live KV EPICONs to reach the terminal feed.
- **DO NOT:** Remove the LPUSH/LTRIM step. Do not move it after an error boundary that could skip it.

### 3. Substrate GitHub auth header
- **File:** `lib/substrate/github-reader.ts`
- **What:** All GitHub API calls to `kaizencycle/Mobius-Substrate` include `Authorization: Bearer ${SUBSTRATE_GITHUB_TOKEN}`
- **Fixed in:** PR #246
- **Why locked:** The Mobius-Substrate repo requires auth. Removing the header causes silent 403 failures and empty journal archive reads.
- **DO NOT:** Remove the Authorization header. Do not change the repo path or branch without verifying the new path exists.

### 4. HERMES signal domain assignment
- **File:** `app/api/signals/micro/route.ts` (HERMES-µ section)
- **What:** HERMES-µ covers narrative signals: Hacker News, Wikipedia, Perplexity Sonar, GDELT. It does NOT fetch crypto prices.
- **Why locked:** ECHO owns crypto via CoinGecko. Duplicate CoinGecko calls in HERMES would create conflicting EPICONs with the same asset data attributed to different agents.
- **DO NOT:** Add CoinGecko, Binance, or any crypto price source to HERMES-µ. Do not move financial domain ownership from ECHO to HERMES.

### 5. Multi-agent journal aggregation
- **File:** `app/api/agents/journal/route.ts`
- **What:** When no `?agent=` param is provided, the route calls `kv.keys('journal:*')`, filters for 3-segment keys, fetches each, merges and deduplicates by `id`
- **Fixed in:** PR #247 (multi-agent fix)
- **Why locked:** Prior to this fix, the unfiltered route returned 0 entries. Reverting to list-based or single-key lookup breaks all-agents view.
- **DO NOT:** Replace `kv.keys('journal:*')` with a hardcoded list of agent names. Do not reintroduce `journal:all` as a primary key.

---

## ⏳ EXPECTED EMPTY — NOT A BUG, DO NOT FIX

These states look broken but are not. Creating PRs for them is wasted effort and risks regression.

### `sources.kv: 0` on EPICON feed
- **Why:** The ECHO → `epicon:feed` bridge was just deployed (PR #246). The bridge only populates on new ECHO ingest cycles. The first post-deploy ingest will populate it.
- **What to do:** Nothing. Wait for next ECHO ingest or trigger `/api/echo/ingest` manually.
- **What NOT to do:** Do not add seed data, do not rewrite the bridge, do not change the key name.

### `sources.kv: 0` on journal
- **Why:** Old `journal:AGENT:CYCLE` keys in Upstash expired (5-day TTL). The reader is correct. Agents will write new keys on next synthesis run.
- **What to do:** Trigger `/api/eve/synthesize` or `/api/cron/watchdog` to generate fresh journal entries.
- **What NOT to do:** Do not change the key schema. Do not add genesis/seed journal entries via code.

### `epicon: empty` lane in terminal snapshot
- **Why:** Same as `sources.kv: 0` above. The lane reads `epicon:feed`. No KV entries yet post-deploy.
- **What to do:** Wait for first ECHO ingest cycle.
- **What NOT to do:** Do not change the lane's fallback logic to show GitHub commits as "committed EPICONs."

### `integrity: stale` / `runtime: stale`
- **Why:** The integrity GI state is cached from the last heartbeat (01:07Z). The runtime shows last GitHub commit time. Both go stale when no agent or cron has fired recently.
- **What to do:** Nothing. These refresh automatically when the next heartbeat or cron runs.
- **What NOT to do:** Do not add artificial freshness timestamps. Do not change the staleness threshold without operator approval.

### DAEDALUS self-ping HTTP 401
- **Why:** The self-ping hits a protected endpoint. This is a known low-priority issue with the auth middleware.
- **Priority:** Low. Logged. Will be addressed in a future cycle.
- **What NOT to do:** Do not create a PR that disables auth on the self-ping endpoint. Do not suppress the error in the signal output — it should remain visible.

---

## 🔧 ACTIVE WORK — C-278

Tasks currently in scope. Do not duplicate.

- [ ] Trigger fresh EVE synthesis → write `journal:EVE:C-278` KV key (operator action, not code)
- [ ] Confirm `ANTHROPIC_API_KEY` is set in Vercel env for agent synthesis routes
- [ ] Resolve DAEDALUS self-ping 401 (low priority — do not block other work on this)
- [ ] Wire agent synthesis cron to run on schedule (not currently firing reliably)

---

## 🏗️ INFRASTRUCTURE MAP

### Vercel (Terminal)
- **Repo:** `kaizencycle/mobius-civic-ai-terminal`
- **Deploy:** Vercel, auto-deploy on merge to `main`
- **KV:** Upstash Redis — env vars `KV_REST_API_URL` + `KV_REST_API_TOKEN`
- **Substrate:** `kaizencycle/Mobius-Substrate` — requires `SUBSTRATE_GITHUB_TOKEN`

### Render (Backend services)
- **Ledger API:** `civic-protocol-core-ledger.onrender.com` — FastAPI + Postgres (`mobius-db`)
- **MIC Wallet:** `mobius-mic-wallet-service.onrender.com` — FastAPI + Postgres
- **Identity:** `mobius-identity-service.onrender.com` — FastAPI + Postgres
- **Database:** `mobius-db` — Render PostgreSQL 18, Virginia
- **Note:** Render free tier spins down on inactivity. First request after spin-down takes ~50s. This is expected — do not add retry logic that masks the spin-up delay.

### Signal ownership (DO NOT REASSIGN)
| Domain | Agent | Sources |
|--------|-------|---------|
| FINANCIAL | ECHO | CoinGecko (BTC, ETH, SOL) |
| ENVIRON | GAIA | Open-Meteo, USGS, NASA EONET |
| NARRATIVE | HERMES-µ | Hacker News, Wikipedia, Perplexity Sonar, GDELT |
| CIVIC | EVE / THEMIS | Federal Register, data.gov |
| INFRASTR | DAEDALUS-µ | GitHub API, npm Registry, self-ping |
| INSTITUTIONAL | JADE | data.gov, FRED (future) |

---

## 📋 PR CHECKLIST REFERENCE

Every PR to this repo must answer these questions before merge:

1. Did I read `AGENTS.md`, `BUILD.md`, and this file before starting?
2. Does this PR touch any LOCKED file/behavior listed above?
   - If yes: state explicitly why the change is safe.
   - If no: confirm in the PR description.
3. Does this PR "fix" anything in the EXPECTED EMPTY section?
   - If yes: stop. It is not a bug.
4. Did `pnpm build` pass?
5. Did I check `/api/terminal/snapshot` after deploy?

---

*This file must be updated whenever a lane changes state, a lock is added or removed, or a cycle advances. Operator: kaizencycle. Agent: ATLAS.*
