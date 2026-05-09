# Mobius Agent Ownership Map
**EPICON:** C-306 / AUREA / agent-ownership  
**CC0 Public Domain**

| Agent | DVA Tier | Owns Service | Activation | LLM Tier |
|-------|----------|-------------|-----------|----------|
| ATLAS | Sentinel | Terminal cron, broker-api | GI drop >0.05 or tripwire | Tier 2-3 |
| ZEUS | Sentinel | reattest-seals, verification | New EPICON events | Tier 1-2 |
| HERMES | Architect | thought-broker, broker-api | Pending lane count > 0 | Tier 0-1 |
| AUREA | Architect | integrity-pulse, service registry | Lane pressure > 0.8 | Tier 1 |
| JADE | Architect | civic-ledger canon gate | Pending canon > 0 | Tier 1-2 |
| DAEDALUS | Steward | oaa-api-library, infra signals | Infra score < 0.7 | Tier 1-2 |
| ECHO | Steward | thought-broker-scheduler, journal | Journal stale >15m | Tier 0 |
| EVE | Observer | narrative synthesis | HERMES mu4 > 0.7 | Tier 2 |
| URIEL | External | adversarial reasoning | anomaly spike | Tier 2-3 |
| ZENITH | External | alternate-model crosscheck | agent disagreement | Tier 2 |

## Current Live State (C-306)

- **seal-C-306-032**: ATLAS ✓ ZEUS ✓ EVE ✓ JADE ✓ AUREA ✓ (cautionary)
- **GI**: 0.727 (yellow / stressed)
- **8 seals quarantined** — substrate write blocked (env var gap)
- **Vault**: 32/40 attested, healthy underneath the write failure
