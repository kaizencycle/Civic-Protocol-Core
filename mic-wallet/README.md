# Mobius MIC Wallet Service

MIC (Mobius Integrity Credit) earning and wallet management for the Mobius platform.

## Features

- MIC wallet per user with Civic ID integration
- Earning event tracking with source categorization
- Configurable earning rules with MII multiplier support
- Full event history with filtering
- Global leaderboard
- Statistics endpoint

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/mic/wallet` | Get user's balance and stats |
| `POST` | `/mic/earn` | Record earning event |
| `GET` | `/mic/events` | Get earning history |
| `GET` | `/mic/rules` | Get earning rules |
| `GET` | `/mic/leaderboard` | Get top earners |
| `GET` | `/mic/stats` | Get global statistics |
| `GET` | `/mic/balance/{civic_id}` | Get balance by Civic ID |
| `GET` | `/health` | Health check |

## Earning Rules

```python
{
    # OAA Tutor actions
    "oaa_tutor_question": 1.0,
    "oaa_tutor_session_complete": 5.0,
    
    # Reflection actions
    "reflection_entry_created": 2.0,
    "reflection_phase_complete": 1.0,
    "reflection_entry_complete": 5.0,
    
    # Shield actions
    "shield_module_complete": 3.0,
    "shield_checklist_item": 1.0,
    
    # Civic Radar actions
    "civic_radar_action_taken": 2.0,
    
    # Engagement actions
    "daily_login": 0.5,
    "streak_bonus_7": 3.0,
    "streak_bonus_30": 10.0,
    
    # Community actions
    "community_contribution": 2.0,
    "peer_recognition": 1.0,
}
```

## MII Multiplier

Earning amounts can be modified by the MII (Mobius Integrity Index) multiplier:
- Range: 0.1x to 5.0x
- Default: 1.0x
- Passed in the `/mic/earn` request

## Environment Variables

```bash
DATABASE_URL=postgresql://user:pass@host:5432/dbname
SECRET_KEY=same-as-identity-service  # Must match Identity Service
PORT=8001
```

## Local Development

```bash
cd mic-wallet
pip install -r requirements.txt
python -m app.main
# or
uvicorn app.main:app --reload --port 8001
```

Open http://localhost:8001/docs for API documentation.

## Testing

```bash
# Get wallet (replace TOKEN with JWT from Identity Service)
curl http://localhost:8001/mic/wallet \
  -H "Authorization: Bearer TOKEN"

# Earn MIC
curl -X POST http://localhost:8001/mic/earn \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source":"oaa_tutor_question","meta":{"subject":"mathematics"}}'

# Earn with multiplier
curl -X POST http://localhost:8001/mic/earn \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source":"reflection_entry_complete","multiplier":1.5,"meta":{"entry_id":"abc123"}}'

# Get earning history
curl http://localhost:8001/mic/events \
  -H "Authorization: Bearer TOKEN"

# Get leaderboard
curl http://localhost:8001/mic/leaderboard

# Get stats
curl http://localhost:8001/mic/stats
```

## Response Examples

### Wallet Response
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "civic_id": "civic::a1b2c3d4e5f6",
  "balance": 42.5,
  "lifetime_earned": 150.0,
  "event_count": 25
}
```

### Earn Response
```json
{
  "delta": 7.5,
  "new_balance": 50.0,
  "source": "reflection_entry_complete",
  "event_id": "evt_123abc",
  "multiplier": 1.5
}
```

### Leaderboard Response
```json
[
  {
    "rank": 1,
    "civic_id": "civic::top_earner",
    "balance": 1000.0,
    "lifetime_earned": 2500.0
  }
]
```

## Deploy to Render

The `render.yaml` in this directory configures deployment:

```bash
# From the mic-wallet directory
render deploy
```

**Important:** Use the same `SECRET_KEY` as the Identity Service so JWT tokens work across services.
