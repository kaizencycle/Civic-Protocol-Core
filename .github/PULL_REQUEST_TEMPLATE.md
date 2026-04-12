# Mobius Terminal PR — C-[CYCLE]

> Replace all `[PLACEHOLDERS]` before submitting. Incomplete PRs will not be merged.

---

## 1. Summary

- **Cycle:** C-
- **Type:** `fix` | `feat` | `chore` | `docs`
- **Primary area:** `journal` | `epicon` | `signals` | `echo` | `ledger` | `agents` | `ui` | `infra` | `docs`
- **Files changed:** (list every file modified)
- **Files deliberately NOT changed:** (list files in the same area you intentionally left alone)

**What changed?**
(One paragraph. Concrete. What the code does now that it didn't before.)

**Why?**
(Reference to CURRENT_CYCLE.md section, snapshot lane state, or specific broken behavior with evidence.)

---

## 2. Risk Tier

- [ ] **Tier 0** — Docs / comments / formatting only
- [ ] **Tier 1** — App logic, no auth/KV schema changes
- [ ] **Tier 2** — KV key schema, journal schema, EPICON shape, signal domain assignment
- [ ] **Tier 3** — MIC economy, identity, ledger integrity math, auth

> Tier 2+ requires operator review before merge. Do not self-merge Tier 2+.

---

## 3. EPICON Intent

```
epicon_id: EPICON_C-[CYCLE]_[area]_[short-description]
scope: [area]
mode: normal
issued_at: [ISO timestamp]

justification:
  PROBLEM:
    [What is broken or missing? Be specific. Include snapshot lane state or error text.]

  CONTEXT:
    [Why does this matter now? Reference CURRENT_CYCLE.md if relevant.]

  DECISION:
    [What exactly is being changed and why this approach over alternatives.]

  BOUNDARIES:
    [What this PR does NOT touch. Be explicit about locked behaviors preserved.]

  TRADEOFFS:
    - Removed: [anything deleted or disabled]
    - Kept: [locked behaviors confirmed preserved]
    - Risk: [what could go wrong]

  COUNTERFACTUALS:
    - If [condition], then [corrective action]
    - If [condition], then [corrective action]
```

---

## 4. LOCKED BEHAVIOR AUDIT

I have read `CURRENT_CYCLE.md` and confirm the following:

**Journal KV key schema (`journal:{AGENT}:{CYCLE}`)**
- [ ] This PR does NOT change the key schema in `app/api/agents/journal/route.ts`
- [ ] OR: I am modifying this because: ___

**ECHO → `epicon:feed` LPUSH**
- [ ] This PR does NOT remove or bypass the LPUSH/LTRIM in `app/api/echo/ingest/route.ts`
- [ ] OR: I am modifying this because: ___

**Substrate GitHub auth header**
- [ ] This PR does NOT remove the `Authorization` header from `lib/substrate/github-reader.ts`
- [ ] OR: I am modifying this because: ___

**Signal domain ownership**
- [ ] This PR does NOT add crypto price sources to HERMES-µ
- [ ] This PR does NOT reassign domain ownership between agents
- [ ] OR: I am modifying this because: ___

**EXPECTED EMPTY states**
- [ ] This PR does NOT attempt to "fix" `sources.kv: 0` on epicon or journal
- [ ] This PR does NOT add seed/genesis data to mask empty KV state
- [ ] OR: I am modifying this because: ___

---

## 5. Integrity Impact

**What could go wrong if this PR is wrong?**

### Assessment
- **Estimated MII for this PR:** (0.00–1.00)
- **Risk level:** Low | Medium | High
- **Lanes affected:** (list terminal snapshot lanes this could impact)

### Checklist
- [ ] Does not change KV key schemas without operator approval
- [ ] Does not remove auth from any route
- [ ] Does not introduce duplicate signal sources across agents
- [ ] Does not add hardcoded cycle IDs, timestamps, or seed data
- [ ] pnpm build passes (or explain why it couldn't be run)

---

## 6. Verification

**Pre-merge:**
- [ ] `pnpm exec tsc --noEmit` — typecheck passes
- [ ] `pnpm build` — build passes (or document environment failure reason)
- [ ] Hit `/api/terminal/snapshot` on preview deployment
- [ ] Confirm affected lanes show expected state in snapshot

**Post-merge (operator to verify):**
- [ ] `/api/terminal/snapshot` checked on production
- [ ] No regressions in previously healthy lanes
- [ ] Snapshot `ok` field and lane states match expected outcome

**Evidence:**
(Paste relevant snapshot lane output or API response here)

---

## 7. Rollback Plan

```bash
git revert [commit-sha]
# If KV writes were involved, manually clean affected keys in Upstash console
# Verify /api/terminal/snapshot returns to pre-PR state
```

---

## 8. Stop Conditions Met

This PR was reviewed against the following stop conditions before submission:

- [ ] No stop condition triggered — scope is clean
- [ ] Stop condition triggered: ___ — resolved by: ___

> Stop conditions: touching a LOCKED file, "fixing" an EXPECTED EMPTY state,
> creating duplicate signal sources, changing KV key schema without Tier 2 review.

---

## 9. Final Checklist

- [ ] Risk tier correctly assessed
- [ ] EPICON intent block completed with BOUNDARIES field
- [ ] Locked behavior audit completed (all boxes checked or exceptions documented)
- [ ] Rollback plan provided
- [ ] I have read AGENTS.md, BUILD.md, and CURRENT_CYCLE.md before starting this PR
- [ ] I am okay with this appearing in the public cathedral

---

*"Let me update my consensus." — Mobius constitutional phrase for acknowledging new ground truth.*
