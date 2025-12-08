# MIC Indexer API

**Mobius Integrity Credit (MIC) Indexer** - Simple FastAPI service that indexes civic ledger events and exposes MIC state.

## Features

- `/supply` — total/circulating MIC, XP pool
- `/balances/{handle}` — XP, direct MIC, implied MIC (XP * ratio)
- `/events` — recent events
- `/scores/{handle}` — alias to balances (extendable)
- `/ingest/ledger` — POST events from the ledger (secured via `X-API-Key`)
- `/policy` — get current earning rules and policy
- `/stats` — indexer statistics

## Earning Rules

```yaml
oaa_tutor_question: 1.0
oaa_tutor_session_complete: 5.0
reflection_entry_created: 2.0
reflection_phase_complete: 1.0
reflection_entry_complete: 5.0
shield_module_complete: 3.0
shield_checklist_item: 1.0
civic_radar_action_taken: 2.0
```

## Run Locally

```bash
cd civic-protocol-core/mic-indexer
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
# open http://127.0.0.1:8000/docs
```

## Ingest Examples

```bash
# XP award to user "michael"
curl -X POST http://127.0.0.1:8000/ingest/ledger \
  -H "Content-Type: application/json" -H "X-API-Key: $MIC_API_KEY" \
  -d '{"kind":"xp_award","amount":500,"unit":"XP","target":"michael","meta":{"source":"reflections"}}'

# Direct MIC grant
curl -X POST http://127.0.0.1:8000/ingest/ledger \
  -H "Content-Type: application/json" -H "X-API-Key: $MIC_API_KEY" \
  -d '{"kind":"grant","amount":5,"unit":"MIC","target":"michael","meta":{"program":"founders"}}'
```

## Query

```bash
curl http://127.0.0.1:8000/supply
curl http://127.0.0.1:8000/balances/michael
curl http://127.0.0.1:8000/events?limit=20
curl http://127.0.0.1:8000/policy
curl http://127.0.0.1:8000/stats
```

## Environment Variables

```
MIC_DB_URL=sqlite:///./mic.db
MIC_API_KEY=your-secret-key
MIC_XP_TO_MIC_RATIO=0.001
CORS_ALLOW_ORIGINS=*
LAB4_BASE=https://hive-api.onrender.com
POLICY_PATH=./policy.yaml
INDEX_DB=./data/index.db
```

## Deploy to Render

The `render.yaml` in this directory configures deployment to Render.
