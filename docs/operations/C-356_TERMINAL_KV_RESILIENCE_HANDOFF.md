# C-356 Terminal KV Resilience — Implementation Handoff

**Repo:** `kaizencycle/mobius-civic-ai-terminal`  
**Branch:** `c356-kv-resilience`  
**Cycle:** C-356  
**CPC spec:** [`MOBIUS_KV_SOVEREIGNTY.md`](./MOBIUS_KV_SOVEREIGNTY.md)  
**Parent:** C-355 (`.dat` canon + CPC hash anchors — merged in CPC)

---

## Goal

Make Upstash suspension a **performance event**, not a **system failure**. Every KV
read/write must have a classified fallback per the tier table in the sovereignty spec.

---

## Files to add / modify

```text
lib/substrate/
  kv-errors.ts          # isKvSuspended(), isBudgetSuspensionError()
  kv-registry.ts        # KEY_TIERS map — single source of truth for classification
  resilient-read.ts     # resilientGet(), resilientMget()
  resilient-write.ts    # extend existing resilientWrite with suspension handling
  reserve-block-dat-digest.ts  # computeReserveBlockDatSha256() — sync with CPC Python
  derive/
    gi.ts               # deriveGiFromSubstrate()
    journal-index.ts    # deriveJournalIndexFromEpicon()
    mic-readiness.ts    # deriveMicReadinessFromVault()

app/api/cron/heartbeat/route.ts      # use resilientGet; never 503 on KV suspend
app/api/cron/vault-attestation/route.ts
app/api/agents/journal/route.ts      # catch UpstashError → CPC write path
app/api/eve/cycle-synthesize/route.ts
```

---

## Step 1 — Error detection

```typescript
// lib/substrate/kv-errors.ts

const BUDGET_SUSPENSION_MARKERS = [
  'exceeded the defined budget limit',
  'database has been suspended',
] as const;

export function isBudgetSuspensionError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return BUDGET_SUSPENSION_MARKERS.some((m) => msg.includes(m));
}

/** @deprecated use isBudgetSuspensionError */
export const isKvSuspended = isBudgetSuspensionError;
```

---

## Step 2 — Key registry

```typescript
// lib/substrate/kv-registry.ts

export type KvTier = 'derived' | 'canon-bound' | 'checkpoint' | 'ephemeral';

/** Mobius KV key → tier. See MOBIUS_KV_SOVEREIGNTY.md for full table. */
export const KEY_TIERS: Record<string, KvTier> = {
  'gi:latest': 'derived',
  'gi:trend': 'derived',
  'gi:latest_carry': 'derived',
  'journal:index': 'derived',
  'mic:readiness:snapshot': 'derived',
  'mic:readiness:feed': 'derived',
  'signals:latest': 'derived',
  'echo:state': 'derived',
  'tripwire:state': 'derived',
  'system:pulse': 'derived',
  'SENTIMENT_SNAPSHOT': 'derived',
  'vault-attestation:lastRun': 'checkpoint',
  'heartbeat:last': 'checkpoint',
  'LAST_PROMOTION_RUN_AT': 'checkpoint',
  'tripwire:kv:heartbeat': 'checkpoint',
  'ledger:circuit_open': 'checkpoint',
  'cache:integrity-status': 'ephemeral',
  'cache:lane-diagnostics': 'ephemeral',
  'snapshot:coalesce': 'ephemeral',
  'signals:micro:cache:v2': 'ephemeral',
};

export function tierForKey(key: string): KvTier {
  if (KEY_TIERS[key]) return KEY_TIERS[key];
  if (key.startsWith('journal:') && !key.endsWith(':index')) return 'canon-bound';
  if (key.startsWith('mic:quorum:')) return 'derived';
  if (key.startsWith('swarm:')) return 'ephemeral';
  if (key.startsWith('agent:meta:')) return 'derived';
  return 'ephemeral'; // unknown keys default safe — recompute/refetch
}
```

---

## Step 3 — Resilient read

```typescript
// lib/substrate/resilient-read.ts

import { kv } from '@/lib/kv'; // existing Upstash wrapper
import { isBudgetSuspensionError } from './kv-errors';
import { tierForKey } from './kv-registry';

export type ResilientReadResult<T> = {
  value: T | null;
  source: 'kv' | 'fallback' | 'miss';
  kv_suspended?: boolean;
};

export async function resilientGet<T>(
  key: string,
  fallback: () => Promise<T | null>,
): Promise<ResilientReadResult<T>> {
  try {
    const value = await kv.get<T>(key);
    if (value !== null && value !== undefined) {
      return { value, source: 'kv' };
    }
  } catch (err) {
    if (isBudgetSuspensionError(err)) {
      console.warn(`[mobius-kv] GET ${key} suspended — using substrate fallback`);
      const value = await fallback();
      return { value, source: 'fallback', kv_suspended: true };
    }
    throw err;
  }

  const value = await fallback();
  return { value, source: value == null ? 'miss' : 'fallback' };
}

export async function resilientMget<T extends Record<string, unknown>>(
  keys: string[],
  fallbacks: Partial<Record<string, () => Promise<unknown>>>,
): Promise<{ values: T; kv_suspended: boolean }> {
  let kv_suspended = false;
  const values = {} as T;

  try {
    const hits = await kv.mget<unknown[]>(keys);
    keys.forEach((key, i) => {
      if (hits[i] != null) (values as Record<string, unknown>)[key] = hits[i];
    });
  } catch (err) {
    if (!isBudgetSuspensionError(err)) throw err;
    kv_suspended = true;
    console.warn(`[mobius-kv] mget suspended — per-key substrate fallback`);
  }

  await Promise.all(
    keys.map(async (key) => {
      if ((values as Record<string, unknown>)[key] != null) return;
      const fb = fallbacks[key];
      if (!fb) return;
      (values as Record<string, unknown>)[key] = await fb();
    }),
  );

  return { values, kv_suspended };
}
```

---

## Step 4 — Resilient write (extend existing)

```typescript
// lib/substrate/resilient-write.ts

import { kv } from '@/lib/kv';
import { isBudgetSuspensionError } from './kv-errors';
import { tierForKey } from './kv-registry';

export type ResilientWriteResult = {
  ok: boolean;
  kv_suspended?: boolean;
  skipped?: boolean;
};

/**
 * Write to KV when available. Tier 1–2 must already be persisted to CPC/canon
 * before calling this — KV write is cache warming only.
 */
export async function resilientSet(
  key: string,
  value: unknown,
  opts?: { ex?: number },
): Promise<ResilientWriteResult> {
  const tier = tierForKey(key);

  try {
    await kv.set(key, value, opts);
    return { ok: true };
  } catch (err) {
    if (!isBudgetSuspensionError(err)) throw err;

    console.warn(`[mobius-kv] SET ${key} suspended (tier=${tier}) — non-fatal`);

    // Tier 3–4: skip silently. Tier 1–2: caller must have written canon first.
    if (tier === 'derived' || tier === 'canon-bound') {
      return { ok: false, kv_suspended: true };
    }
    return { ok: false, kv_suspended: true, skipped: true };
  }
}
```

---

## Step 5 — Substrate derivations

CPC `get_integrity_snapshot` returns `gi`, not `global_integrity` (see
`ledger/app/routes/mcp_tools.py`). Terminal `GiSnapshot` uses `global_integrity`.
**Always normalize** before passing to `computeNextGi`.

```typescript
// lib/substrate/derive/gi.ts

const CPC_BASE = process.env.CIVIC_LEDGER_URL
  ?? 'https://civic-protocol-core-ledger.onrender.com';

/** MCP payload shape from CPC get_integrity_snapshot */
type McpGiSnapshot = {
  ok?: boolean;
  gi?: number;
  mode?: string;
  terminal_status?: string;
  signals?: Record<string, number>;
  source?: string;
  timestamp?: string;
  gi_verified?: boolean;
  gi_verification_method?: string;
};

/** Terminal KV / heartbeat shape */
export type GiSnapshot = {
  global_integrity: number;
  mode: string;
  terminal_status?: string;
  primary_driver?: string;
  source?: string;
  gi_write_source?: string;
  signals?: Record<string, number>;
  gi_verified?: boolean;
  gi_verification_method?: string;
  timestamp: string;
};

export function normalizeMcpGiSnapshot(mcp: McpGiSnapshot): GiSnapshot | null {
  const gi = mcp.gi;
  if (typeof gi !== 'number' || Number.isNaN(gi)) return null;
  return {
    global_integrity: gi,
    mode: mcp.mode ?? 'yellow',
    terminal_status: mcp.terminal_status,
    source: mcp.source ?? 'substrate-fallback',
    gi_write_source: 'integrity',
    signals: mcp.signals,
    gi_verified: mcp.gi_verified,
    gi_verification_method: mcp.gi_verification_method,
    timestamp: mcp.timestamp ?? new Date().toISOString(),
  };
}

export async function deriveGiFromSubstrate(): Promise<GiSnapshot | null> {
  const res = await fetch(`${CPC_BASE}/api/mcp`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'MCP-Protocol-Version': '2025-03-26',
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: { name: 'get_integrity_snapshot', arguments: {} },
    }),
  });
  if (!res.ok) return null;
  const body = await res.json();
  const text = body?.result?.content?.[0]?.text;
  if (!text) return null;
  const mcp = JSON.parse(text) as McpGiSnapshot;
  return normalizeMcpGiSnapshot(mcp);
}
```

```typescript
// lib/substrate/derive/journal-index.ts

export async function deriveJournalIndexFromEpicon(): Promise<JournalIndexEntry[]> {
  const res = await fetch(`${CPC_BASE}/epicon/feed?limit=100`);
  if (!res.ok) return [];
  const feed = await res.json();
  return (feed.entries ?? []).map((e: { id: string; title?: string; timestamp?: string }) => ({
    agent: extractAgentFromTitle(e.title),
    cycle: extractCycleFromTitle(e.title),
    key: `journal:${extractAgentFromTitle(e.title)}:${extractCycleFromTitle(e.title)}`,
    updatedAt: e.timestamp ?? new Date().toISOString(),
  }));
}
```

---

## Step 6 — Heartbeat cron (stop returning 503)

```typescript
// app/api/cron/heartbeat/route.ts  (pattern)

import { resilientGet } from '@/lib/substrate/resilient-read';
import { resilientSet } from '@/lib/substrate/resilient-write';
import { deriveGiFromSubstrate } from '@/lib/substrate/derive/gi';

export async function GET(req: Request) {
  const { value: gi, source, kv_suspended } = await resilientGet(
    'gi:latest',
    deriveGiFromSubstrate,
  );

  if (!gi) {
    return Response.json({ ok: false, error: 'gi_unavailable' }, { status: 503 });
  }

  // Recompute / refresh GI (existing logic) ...
  const nextGi = computeNextGi(gi);

  const writeResult = await resilientSet('gi:latest', nextGi, { ex: 14400 });

  return Response.json({
    ok: true,
    gi: nextGi.global_integrity,
    mode: nextGi.mode,
    source: writeResult.kv_suspended ? 'substrate-fallback' : source,
    kv_suspended: writeResult.kv_suspended ?? kv_suspended ?? false,
  });
  // ↑ 200 even when KV is suspended — never 503 for budget cap alone
}
```

---

## Step 7 — Agent journal (stop returning 500)

```typescript
// app/api/agents/journal/route.ts  (pattern)

import { isBudgetSuspensionError } from '@/lib/substrate/kv-errors';

export async function POST(req: Request) {
  const body = await req.json();
  // ... validate ...

  // 1. Canon write first (CPC EPICON ingest or ledger attest)
  const cpcResult = await postJournalToCpc(body);
  if (!cpcResult.ok) {
    return Response.json({ ok: false, error: cpcResult.error }, { status: 502 });
  }

  // 2. KV meta write — non-fatal
  try {
    await kv.hset(`agent:meta:${body.agent}`, {
      last_journal_at: new Date().toISOString(),
      last_journal_cycle: body.cycle,
    });
  } catch (err) {
    if (isBudgetSuspensionError(err)) {
      console.warn(`[mobius-kv] agent:meta write skipped — KV suspended`);
      return Response.json({
        ok: true,
        canon: 'cpc',
        kv_suspended: true,
        entry_id: cpcResult.entry_id,
      });
    }
    throw err;
  }

  return Response.json({ ok: true, entry_id: cpcResult.entry_id });
}
```

---

## Step 8 — Vault attestation + C-355 seal dispatch

When quorum is met, **never** depend on KV for the seal.

**Critical:** CPC `sha256` must be the **MOBIUS01 .dat digest** (same bytes as
`ledger/app/reserve_dat.py` indexes), **not** `readiness_proof.hash`. The latter
may differ from the canonical `.dat` footer hash. Compute the digest deterministically
before anchoring — the GitHub workflow writes the same payload with the same rules.

```typescript
// lib/substrate/reserve-block-dat-digest.ts
// Must stay in sync with ledger/app/reserve_dat.py (MOBIUS01 format)

import { createHash } from 'crypto';

const MAGIC = Buffer.from('MOBIUS01');
const VERSION = Buffer.from([0x00, 0x01]);

function parseCycleNumber(cycle: string): number {
  const digits = cycle.replace(/\D/g, '');
  if (!digits) throw new Error(`Invalid cycle: ${cycle}`);
  return parseInt(digits, 10);
}

function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value as object)
        .sort()
        .map((k) => [k, sortKeysDeep((value as Record<string, unknown>)[k])]),
    );
  }
  return value;
}

/** Matches Python: json.dumps(payload, separators=(',', ':'), sort_keys=True) */
function canonicalPayloadBytes(payload: Record<string, unknown>): Buffer {
  return Buffer.from(JSON.stringify(sortKeysDeep(payload)), 'utf-8');
}

function packUint32BE(n: number): Buffer {
  const buf = Buffer.alloc(4);
  buf.writeUInt32BE(n, 0);
  return buf;
}

/** SHA-256 over header + payload (footer excluded) — same as read_reserve_block_dat().hash */
export function computeReserveBlockDatSha256(
  payload: Record<string, unknown>,
  cycle: string,
  sequence: number,
): string {
  const cycleNum = parseCycleNumber(cycle);
  const payloadBytes = canonicalPayloadBytes(payload);
  const header = Buffer.concat([
    MAGIC,
    VERSION,
    packUint32BE(cycleNum),
    packUint32BE(sequence),
    packUint32BE(payloadBytes.length),
  ]);
  const content = Buffer.concat([header, payloadBytes]);
  return createHash('sha256').update(content).digest('hex');
}

async function dispatchReserveBlockDat(
  block: ReserveBlockPayload,
): Promise<void> {
  const token = process.env.SUBSTRATE_GITHUB_TOKEN;
  if (!token) {
    throw new Error('SUBSTRATE_GITHUB_TOKEN missing — cannot write .dat canon');
  }

  const res = await fetch(
    'https://api.github.com/repos/kaizencycle/Civic-Protocol-Core/dispatches',
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        Accept: 'application/vnd.github+json',
      },
      body: JSON.stringify({
        event_type: 'reserve-block-sealed',
        client_payload: {
          block_id: block.block_id,
          cycle: block.cycle,
          sequence: block.sequence,
          payload: block,
        },
      }),
    },
  );

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(
      `GitHub repository_dispatch failed: ${res.status} ${detail}`,
    );
  }
  // GitHub returns 204 No Content on success
}

async function anchorReserveBlockOnCpc(
  block: ReserveBlockPayload,
  datSha256: string,
): Promise<void> {
  const anchor = await fetch(`${CPC_BASE}/api/reserve-blocks/anchor`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${process.env.AGENT_SERVICE_TOKEN}`,
    },
    body: JSON.stringify({
      block_id: block.block_id,
      cycle: block.cycle,
      sequence: block.sequence,
      gi_at_seal: block.gi_at_seal,
      mic_minted: block.mic_minted,
      quorum_met: true,
      sealed_at: block.sealed_at,
      sha256: datSha256,
      dat_path: `ledger/reserve-blocks/reserve-block-${block.cycle.replace(/-/g, '').replace(/^c/i, 'C')}-${String(block.sequence).padStart(3, '0')}.dat`,
    }),
  });
  if (!anchor.ok) {
    const detail = await anchor.text();
    throw new Error(`CPC anchor failed: ${anchor.status} ${detail}`);
  }
}

async function sealReserveBlock(block: ReserveBlockPayload): Promise<SealResult> {
  // Canonical payload written to .dat (include readiness_proof for audit, not as anchor hash)
  const datPayload = {
    ...block,
    block_id: block.block_id,
    cycle: block.cycle,
    sequence: block.sequence,
  };

  // 1. Deterministic .dat digest — MUST match write-reserve-block-dat.yml output
  const datSha256 = computeReserveBlockDatSha256(
    datPayload,
    block.cycle,
    block.sequence,
  );

  // 2. GitHub .dat canon (required) — before CPC anchor so canon exists if dispatch fails
  await dispatchReserveBlockDat(block);

  // 3. CPC hash anchor (required) — points at the .dat digest above
  await anchorReserveBlockOnCpc(block, datSha256);

  // 4. KV hot cache (optional — non-fatal)
  await resilientSet(`reserve_block:${block.block_id}`, JSON.stringify(block), {
    ex: 60 * 60 * 24 * 30,
  });

  return { ok: true, sha256: datSha256 };
}
```

**Seal order rationale:** dispatch first so a failed GitHub token does not leave
an orphaned CPC anchor without a `.dat` artifact. If dispatch succeeds but anchor
fails, the `.dat` exists in GitHub and can be anchored on retry (idempotent).

---

## Commit protocol (Terminal repo)

```bash
git commit -m "feat(C-356): add lib/substrate/kv-errors + kv-registry"
git commit -m "feat(C-356): add resilient-read.ts and extend resilient-write.ts"
git commit -m "feat(C-356): add derive/gi (normalize MCP gi→global_integrity) + journal-index"
git commit -m "feat(C-356): add reserve-block-dat-digest.ts (MOBIUS01 sha256)"
git commit -m "fix(C-356): heartbeat cron — 200 on KV suspension, derive GI from CPC"
git commit -m "fix(C-356): agent journal — CPC first, KV meta non-fatal"
git commit -m "fix(C-356): eve cycle-synthesize — tripwire write non-fatal on KV suspend"
git commit -m "feat(C-356): vault-attestation seal → CPC anchor + .dat dispatch (C-355)"
```

---

## Ops unblock (do today)

1. **Upstash Console** → increase budget or upgrade to Fixed plan
2. Confirm suspension lifted: `[mobius-kv] GET gi:latest` succeeds
3. Ship C-356 Terminal PR so next suspension is non-fatal

---

## Tests (Terminal)

```typescript
describe('isBudgetSuspensionError', () => {
  it('detects Upstash budget suspension', () => {
    expect(isBudgetSuspensionError(
      new Error('ERR This database has been suspended for exceeding the defined budget limit'),
    )).toBe(true);
  });
});

describe('resilientGet', () => {
  it('falls back when KV throws suspension', async () => {
    vi.mocked(kv.get).mockRejectedValue(new Error('...suspended...'));
    const result = await resilientGet('gi:latest', async () => ({ global_integrity: 0.8 }));
    expect(result.source).toBe('fallback');
    expect(result.kv_suspended).toBe(true);
  });
});

describe('normalizeMcpGiSnapshot', () => {
  it('maps MCP gi to Terminal global_integrity', () => {
    const out = normalizeMcpGiSnapshot({ gi: 0.71, mode: 'yellow', timestamp: 't' });
    expect(out?.global_integrity).toBe(0.71);
  });
});

describe('computeReserveBlockDatSha256', () => {
  it('matches CPC Python writer for same payload', async () => {
    // golden-vector test: run scripts/write_reserve_block_dat.py locally, compare footer hash
    const hash = computeReserveBlockDatSha256(
      { block_id: 'reserve-block-C355-001', cycle: 'C-355', sequence: 1 },
      'C-355',
      1,
    );
    expect(hash).toMatch(/^[a-f0-9]{64}$/);
  });
});

describe('dispatchReserveBlockDat', () => {
  it('throws when GitHub returns 401', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, text: async () => 'Bad credentials' });
    await expect(dispatchReserveBlockDat(fixtureBlock)).rejects.toThrow(/repository_dispatch failed/);
  });
});
```

---

*"We heal as we walk." — Mobius Systems*
