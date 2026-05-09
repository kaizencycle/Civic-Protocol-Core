# Mobius Mesh Workflow v1 — HIVE + execution fabric (C-287 / C-288)

## Core idea

**`mobius.yaml`** is the **declaration contract** for each repo (identity, pulse, ingest, optional MCP, **jobs**, **governance**).

**GitHub Actions and cron** are the **execution fabric** — they run the workflows listed under `jobs.workflows`.

**Mobius-Substrate** aggregates feeds into pulse / mesh artifacts.

**mobius-browser-shell** (and **mobius-hive**) render **world state** for humans from committed JSON and live APIs.

```
mobius.yaml  →  declares what each node is and which jobs exist
GitHub Actions / cron  →  run those jobs
Substrate  →  aggregates node outputs (pulse, mesh aggregate)
Browser shell / HIVE  →  render cycle, quests, sentinels, vault
```

This file is **doctrine for the mesh**; repo-specific `mobius.yaml` instances live in each repository.

---

## Repo roles (summary)

| Repo | Role | Primary outputs |
|------|------|-----------------|
| **Mobius-Substrate** | Registry, doctrine, pulse aggregation | `mesh-aggregate.json`, `mobius-pulse.json`, … |
| **mobius-civic-ai-terminal** | Operator runtime, snapshots | `snapshot-lite`, heartbeat, MIC readiness |
| **OAA-API-Library** | Sovereign signed memory | append journal, latest-by-key reads |
| **Civic-Protocol-Core** | Durable ledger, proof ingest | `/mesh/ingest`, `/epicon/feed`, `/api/oaa/memory` |
| **mobius-hive** | World layer (quests, lore, events) | `world/*.json`, PR proposals |
| **mobius-browser-shell** | Human-facing shell | Castle / HIVE UI |

---

## `mobius.yaml` — extensions (v1)

### `jobs`

| Field | Description |
|-------|-------------|
| `jobs.enabled` | Whether this repo participates in declared automation |
| `jobs.workflows[]` | Each entry: `id`, `file` (path under repo), `trigger` (`schedule` \| `push` \| `workflow_dispatch`), optional `cron`, optional `branches` |

**Civic-Protocol-Core** declares:

- `ledger-pulse-snapshot` — hourly-ish snapshot of public `/health` + `/epicon/feed` → `ledger/mesh-pulse-snapshot.json`
- `ledger-mesh-feed-on-push` — existing push workflow updating `ledger/feed.json`

### `governance`

| Field | Description |
|-------|-------------|
| `agent_prs_allowed` | Sentinel / agent PRs may propose world or ledger-adjacent changes |
| `auto_merge_allowed` | Must be `false` for production integrity |
| `required_reviewers` | Sentinel handles (ZEUS, ATLAS, …) — enforced via branch protection + human review |

**Rule:** agents may **generate files and open PRs**; they must **not** auto-merge or deploy MIC / trust logic without review.

---

## First HIVE auto-quest loop (concept)

**Inputs:** terminal snapshot, `mobius-pulse.json`, cycle state, optional OAA keys (`vault:status`, `mic:readiness`, `heartbeat:terminal`).

**Rules (example):** degraded KV → event “Signal Fog”, quest “Restore the Beacon”, sentinel ZEUS; vault progress + rising GI → “Fountain Murmur” / “Prepare the Seal” / HERMES.

**Outputs (mobius-hive):** `world/current-cycle.json`, `world/events/*.json`, `world/quests/*.json`, `world/sentinels/*.json`.

**Browser shell:** renders Current Cycle, Active Event/Quest, sentinel copy, vault / fountain / integrity.

Implementation of HIVE scripts and Substrate `mesh-sync` belongs in those repos; **this** repo supplies **ledger truth** and a **machine-readable snapshot** for downstream jobs.

---

## One-line truth

**`mobius.yaml` tells the mesh what each repo is; Actions and cron tell the mesh when each repo acts.**
