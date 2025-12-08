# Civic Protocol Core

A sovereign blockchain for civilization state - where AI and citizens co-govern through verified civic activity.

## Overview

Civic Protocol Core implements a **Proof-of-Cycle (PoC)** consensus mechanism that rewards verified civic heartbeat rather than raw compute power. The protocol is purpose-built for civic memory, default-private with opt-in public participation, and AI-native with companions as first-class participants.

## Core Concepts

* **Cycle**: The fundamental primitive (Seed → Sweep → Seal → Ledger)
* **Reflections**: Private civic thoughts and insights (encrypted off-chain)
* **MIC**: Mobius Integrity Credit for civic participation
* **Proof-of-Cycle**: Consensus based on verifiable civic activity
* **Shield**: Privacy-preserving layer for private reflections with zkRL
* **Agora**: Democratic governance system with quadratic voting
* **Identity**: Authentication and user management
* **MII**: Mobius Integrity Index for earning multipliers

## Repository Structure

```
civic-protocol-core/
├── ledger/                     # The Blockchain Kernel (Civic Ledger API)
│   ├── app/
│   │   ├── main.py            # FastAPI ledger service
│   │   ├── ledger.py          # Core ledger functionality
│   │   └── verify.py          # Token and signature verification
│   ├── requirements.txt
│   └── README.md
├── identity/                   # NEW: Identity & Auth Service
│   ├── app/
│   │   └── main.py            # FastAPI identity service
│   ├── requirements.txt
│   ├── render.yaml            # Render deployment config
│   └── README.md
├── mic-wallet/                 # NEW: MIC Wallet Service
│   ├── app/
│   │   └── main.py            # FastAPI wallet service
│   ├── requirements.txt
│   ├── render.yaml            # Render deployment config
│   └── README.md
├── mic-indexer/                # NEW: MIC Indexer (renamed from gic-indexer)
│   ├── app/
│   │   ├── main.py            # FastAPI indexer service
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── schemas.py         # Pydantic schemas
│   │   ├── storage.py         # Database storage
│   │   └── config.py          # Configuration
│   ├── policy.yaml            # MIC earning policy
│   ├── requirements.txt
│   ├── render.yaml            # Render deployment config
│   └── README.md
├── lab6-proof/                 # Citizen Shield API
│   ├── app/
│   │   └── main.py            # Shield zkRL service
│   ├── policy.yaml            # Virtue Accords v0
│   └── requirements.txt
├── frontend/                   # Frontend Applications
│   └── citizen-shield-app/    # Citizen Shield React App
│       ├── src/
│       │   ├── components/    # React components
│       │   ├── pages/         # App pages
│       │   └── api/           # API client
│       ├── package.json
│       └── README.md
├── integrations/               # Integration Components
│   └── lab6-citizen-shield/   # Lab6 Citizen Shield Integration
│       ├── app_routes_onboard.py
│       └── README_UPDATE.md
├── tools/                      # Development Tools
│   ├── scripts/               # Automation scripts
│   └── utilities/             # Utility tools
├── consensus/                  # Quorum + ZEUS arbitration
│   └── proof_of_cycle.py      # PoC consensus implementation
├── governance/                 # Festivals, Agora contracts
│   └── agora.py               # Agora governance system
├── gic-indexer/               # Legacy GIC indexer (use mic-indexer)
├── docs/                      # Documentation
├── sdk/                       # Python & JavaScript SDKs
│   ├── python/
│   └── js/
├── registry/                  # Component Registry
├── examples/                  # Example Applications
├── scripts/                   # Legacy Scripts
├── policies/                  # GitHub Policies
├── .github/                   # GitHub Workflows
├── start-all-services.py      # Service orchestration
├── docker-compose.yml         # Container orchestration
├── Dockerfile                 # Container definition
├── render.yaml                # Render blueprint (all services)
└── requirements.txt           # Python dependencies
```

## Quick Start

### Option 1: Start All Services (Recommended)

```bash
# Install dependencies
pip install -r requirements.txt

# Start all services at once
python start-all-services.py
```

This will start:
* Civic Dev Node (port 5411)
* Shield (port 7000)
* MIC-Indexer (port 8000)
* Identity Service (port 8002)
* MIC Wallet Service (port 8003)

### Option 2: Start Services Individually

```bash
# Terminal 1: Civic Dev Node
python sdk/python/devnode.py

# Terminal 2: Shield
cd lab6-proof && python app/main.py

# Terminal 3: MIC-Indexer
cd mic-indexer && uvicorn app.main:app --port 8000

# Terminal 4: Identity Service
cd identity && uvicorn app.main:app --port 8002

# Terminal 5: MIC Wallet Service
cd mic-wallet && uvicorn app.main:app --port 8003
```

### Option 3: Docker Compose

```bash
docker-compose up -d
```

### Test the Integration

```bash
# Run the full integration test
python examples/full-integration-example.py
```

### Test Authentication + MIC Flow

```bash
# 1. Signup
curl -X POST http://localhost:8002/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"secret123","name":"Test User"}'

# 2. Use the returned token to earn MIC
curl -X POST http://localhost:8003/mic/earn \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"source":"oaa_tutor_question"}'

# 3. Check wallet balance
curl http://localhost:8003/mic/wallet \
  -H "Authorization: Bearer <TOKEN>"
```

## Frontend Applications

### Citizen Shield App

A React-based frontend for the Citizen Shield system:

```bash
cd frontend/citizen-shield-app
npm install
npm run dev
```

Features:
- Citizen enrollment interface
- Group status monitoring
- Verification workflows
- Seal card components

## Integration Components

### Lab6 Citizen Shield Integration

Integration tools and API routes for Lab6 Citizen Shield:

```bash
cd integrations/lab6-citizen-shield
# Follow README_UPDATE.md for setup instructions
```

## Development Tools

### Scripts

Automation scripts for development workflow:

- `autocommit.ps1` - PowerShell auto-commit script
- `detect-scope.sh` - Scope detection for commits
- `generate-commit-msg.sh` - Commit message generation
- `redaction-scan.sh` - Redaction scanning
- `start-autocommit.bat` - Windows auto-commit starter

### Utilities

Development utilities:

- `generate_checksum.py` - SHA-256 checksum generator for manifest files
- `get_lab4_token.py` - Lab4 authentication token generator
- `citizen-shield-ts-fix/` - TypeScript fixes and improvements

## SDK Usage

### Python SDK

```python
from sdk.python.client import CivicClient
c = CivicClient()
c.add_reflection("Cycle 0 Hello", "We heal as we walk.", ["hello","cycle0"])
print(c.list_reflections())
```

### JavaScript SDK

```javascript
import { CivicClient } from './sdk/js/index.js';
const c = new CivicClient('http://localhost:5411');
await c.addReflection({ title: 'Cycle 0 Hello', body: 'We heal as we walk.' });
console.log(await c.listReflections());
```

## Complete System Flow

### 1. Identity Service - Authentication

* **User Registration**: Email/password signup
* **JWT Tokens**: Secure token-based authentication
* **Civic ID**: Unique identifier for Civic Protocol
* **Introspection**: Token validation for other services

### 2. MIC Wallet Service - Earnings

* **Wallet Management**: Per-user MIC balance tracking
* **Earning Events**: Record MIC for civic actions
* **MII Multiplier**: Integrity-based earning bonuses
* **Leaderboards**: Global ranking of earners

### 3. Ledger API - The Blockchain Kernel

* **Central Event Store**: All civic activity anchored here
* **Immutable Events**: Chained, verified, and permanent
* **Token Verification**: Authenticated via Lab4/Lab6
* **Event Types**: Reflections, companions, governance, MIC transactions

### 4. Lab6-Proof - Citizen Shield

* **zkRL Verification**: Zero-knowledge rate limiting
* **Shield Actions**: Privacy-preserving civic activities
* **Citizen Attestations**: Verified civic contributions
* **Auto-Anchoring**: Every action posts to Ledger API

### 5. MIC Indexer - Balance Computation

* **Real-time Computation**: Balance calculation from ledger events
* **Activity Rewards**: MIC earned for civic participation
* **XP to MIC Conversion**: Experience points converted to MIC
* **Economic Policies**: Configurable reward schedules

### 6. Complete Integration Flow

```
Mobius Browser (Vercel)
    ↓
┌───────────────────────────────────┐
│  Civic Protocol Core (Render)     │
├───────────────────────────────────┤
│ identity/     → /auth/*           │ ← Signup/Login
│ mic-wallet/   → /mic/*            │ ← Earn MIC
│ ledger/       → /ledger/*         │ ← Anchor events
│ lab6-proof/   → /shield/*         │ ← Privacy actions
│ mic-indexer/  → /supply, /balance │ ← Compute totals
└───────────────────────────────────┘
    ↓
PostgreSQL Database (Render)
```

### MIC Earning Rules

| Action | Base MIC |
|--------|----------|
| OAA Tutor Question | 1.0 |
| OAA Tutor Session Complete | 5.0 |
| Reflection Entry Created | 2.0 |
| Reflection Phase Complete | 1.0 |
| Reflection Entry Complete | 5.0 |
| Shield Module Complete | 3.0 |
| Shield Checklist Item | 1.0 |
| Civic Radar Action | 2.0 |
| Daily Login | 0.5 |
| 7-Day Streak | 3.0 |
| 30-Day Streak | 10.0 |

## Genesis Custodian Event

The Civic Ledger supports Genesis Events for establishing the foundation of civic activity. See `GENESIS_CUSTODIAN_GUIDE.md` for complete instructions on:

- Creating Genesis Custodian Events
- Generating SHA-256 checksums
- Authentication with Lab4 tokens
- Posting events to the ledger

## Development Roadmap

### Phase 1: MVP (Current)

* Starter kit with dev node
* Python and JavaScript SDKs
* OpenAPI specification
* Example hello-reflection app
* Citizen Shield frontend
* Integration tools

### Phase 2: Testnet

* GIC blockchain implementation
* Proof-of-Cycle consensus
* Shield integration with zkRL
* Custodian node setup

### Phase 3: Mainnet

* Public custodian nodes
* Slashing mechanisms
* Governance with quadratic voting
* Policy time-locks

## Contributing

See CONTRIBUTING.md for development guidelines.

## License

See LICENSE for licensing information.

## About

Civic Protocol Core is a comprehensive blockchain platform for civic governance, combining AI companions, privacy-preserving verification, and democratic participation mechanisms.

### Resources

- [GitHub Repository](https://github.com/kaizencycle/Civic-Protocol-Core)
- [OpenAPI Documentation](docs/openapi.yaml)
- [Genesis Custodian Guide](GENESIS_CUSTODIAN_GUIDE.md)
- [CIP Templates](docs/)

### Contributors

* @kaizencycle **kaizencycle**
* @cursoragent **cursoragent** Cursor Agent