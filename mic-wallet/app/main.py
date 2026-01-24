# mic-wallet/app/main.py
"""
Mobius MIC Wallet Service

MIC earning and wallet management for the Mobius platform.
Tracks MIC balance, earning events, and provides leaderboard functionality.
"""

from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer, JSON, desc, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from typing import Optional, List
from urllib.parse import urlparse
import socket
import logging
import jwt
import os
import uuid

logger = logging.getLogger(__name__)

# =============================================================================
# Database Configuration with IPv4 Forcing
# =============================================================================
# This fixes connectivity issues on platforms like Render.com that don't support
# IPv6 outbound connections to Supabase.

def resolve_hostname_to_ipv4(hostname: str) -> str | None:
    """Resolve a hostname to its IPv4 address."""
    try:
        result = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        if result:
            ipv4_address = result[0][4][0]
            logger.info(f"Resolved {hostname} to IPv4: {ipv4_address}")
            return ipv4_address
    except socket.gaierror as e:
        logger.warning(f"Failed to resolve {hostname} to IPv4: {e}")
    return None


def get_engine_kwargs(database_url: str) -> dict:
    """Get engine kwargs with IPv4 forcing for PostgreSQL connections."""
    kwargs = {}
    
    if not database_url.startswith("postgresql"):
        return kwargs
    
    # Connection pool settings optimized for serverless/Supabase
    kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "pool_recycle": 300,  # Recycle connections after 5 minutes
        "pool_pre_ping": True,  # Verify connections before use
    })
    
    # Force IPv4 connections to fix Render.com/Supabase connectivity
    try:
        parsed = urlparse(database_url)
        hostname = parsed.hostname
        
        if hostname and hostname not in ("localhost", "127.0.0.1", "::1"):
            ipv4_addr = resolve_hostname_to_ipv4(hostname)
            if ipv4_addr:
                # Use hostaddr to bypass DNS and force IPv4
                kwargs["connect_args"] = {"hostaddr": ipv4_addr}
                logger.info(f"Configured IPv4 connection to {hostname} via {ipv4_addr}")
    except Exception as e:
        logger.warning(f"Error configuring IPv4 connection: {e}")
    
    return kwargs

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mic_wallet.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"

# Database setup with IPv4 forcing
engine_kwargs = get_engine_kwargs(DATABASE_URL)
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Models
class Wallet(Base):
    __tablename__ = "mic_wallets"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), unique=True, nullable=False, index=True)
    civic_id = Column(String(255), unique=True, index=True)  # Link to Civic Protocol identity
    balance_mic = Column(Float, default=0.0)
    lifetime_earned = Column(Float, default=0.0)  # Total MIC ever earned
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MICEvent(Base):
    __tablename__ = "mic_events"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)
    source = Column(String(100), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    multiplier = Column(Float, default=1.0)  # MII multiplier applied
    final_amount = Column(Float, nullable=False)  # amount * multiplier
    meta = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# Create tables
Base.metadata.create_all(bind=engine)

# Security
security = HTTPBearer()

# Earning rules - base amounts for each action
EARNING_RULES = {
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


# Pydantic models
class EarnRequest(BaseModel):
    source: str
    meta: dict | None = None
    multiplier: float = 1.0  # Optional MII multiplier


class EarnResponse(BaseModel):
    delta: float
    new_balance: float
    source: str
    event_id: str
    multiplier: float


class WalletResponse(BaseModel):
    user_id: str
    civic_id: str | None
    balance: float
    lifetime_earned: float
    event_count: int


class EventResponse(BaseModel):
    id: str
    source: str
    amount: float
    multiplier: float
    final_amount: float
    meta: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


class LeaderboardEntry(BaseModel):
    rank: int
    civic_id: str | None
    balance: float
    lifetime_earned: float


class StatsResponse(BaseModel):
    total_wallets: int
    total_mic_distributed: float
    total_events: int
    top_earning_source: str | None


# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Auth
def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("user_id"), payload.get("civic_id")
    except:
        return None, None


def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user_id, civic_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid authentication")
    return user_id, civic_id


def get_or_create_wallet(user_id: str, civic_id: str | None, db: Session) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not wallet:
        wallet = Wallet(
            id=str(uuid.uuid4()),
            user_id=user_id,
            civic_id=civic_id,
            balance_mic=0.0,
            lifetime_earned=0.0
        )
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    elif civic_id and not wallet.civic_id:
        # Update civic_id if it wasn't set before
        wallet.civic_id = civic_id
        db.commit()
        db.refresh(wallet)
    return wallet


# FastAPI app
app = FastAPI(
    title="Mobius MIC Wallet Service",
    description="MIC earning and wallet management for Mobius",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mobius-browser-shell.vercel.app",
        "https://mobius-browser-shell-*.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routes
@app.get("/")
async def root():
    return {
        "service": "mobius-mic-wallet",
        "version": "1.0.0",
        "docs": "/docs",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "Mobius MIC Wallet Service",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/mic/wallet", response_model=WalletResponse)
async def get_wallet(
    auth: tuple = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get user's MIC wallet balance and stats"""
    user_id, civic_id = auth
    wallet = get_or_create_wallet(user_id, civic_id, db)
    
    # Get total events
    event_count = db.query(MICEvent).filter(MICEvent.user_id == user_id).count()
    
    return {
        "user_id": user_id,
        "civic_id": wallet.civic_id,
        "balance": wallet.balance_mic,
        "lifetime_earned": wallet.lifetime_earned,
        "event_count": event_count
    }


@app.post("/mic/earn", response_model=EarnResponse, status_code=status.HTTP_201_CREATED)
async def earn_mic(
    request: EarnRequest,
    auth: tuple = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Record a MIC earning event"""
    user_id, civic_id = auth
    
    # Validate source
    if request.source not in EARNING_RULES:
        raise HTTPException(
            status_code=400, 
            detail=f"Unknown earning source: {request.source}. Valid sources: {list(EARNING_RULES.keys())}"
        )
    
    # Get base amount
    base_amount = EARNING_RULES[request.source]
    
    # Apply multiplier (MII multiplier when implemented)
    multiplier = max(0.1, min(request.multiplier, 5.0))  # Clamp between 0.1 and 5.0
    final_amount = base_amount * multiplier
    
    # Get or create wallet
    wallet = get_or_create_wallet(user_id, civic_id, db)
    
    # Create event
    event = MICEvent(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source=request.source,
        amount=base_amount,
        multiplier=multiplier,
        final_amount=final_amount,
        meta=request.meta
    )
    db.add(event)
    
    # Update balance
    wallet.balance_mic += final_amount
    wallet.lifetime_earned += final_amount
    wallet.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(wallet)
    
    return {
        "delta": final_amount,
        "new_balance": wallet.balance_mic,
        "source": request.source,
        "event_id": event.id,
        "multiplier": multiplier
    }


@app.get("/mic/events", response_model=List[EventResponse])
async def get_events(
    auth: tuple = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    limit: int = Query(50, le=500),
    offset: int = 0,
    source: Optional[str] = None
):
    """Get user's MIC earning history"""
    user_id, _ = auth
    
    query = db.query(MICEvent).filter(MICEvent.user_id == user_id)
    
    if source:
        query = query.filter(MICEvent.source == source)
    
    events = (
        query
        .order_by(desc(MICEvent.created_at))
        .limit(limit)
        .offset(offset)
        .all()
    )
    
    return events


@app.get("/mic/rules")
async def get_earning_rules():
    """Get current MIC earning rules"""
    return {
        "rules": EARNING_RULES,
        "note": "Base amounts. Actual earnings may be modified by MII multiplier (0.1x - 5.0x).",
        "categories": {
            "oaa_tutor": ["oaa_tutor_question", "oaa_tutor_session_complete"],
            "reflection": ["reflection_entry_created", "reflection_phase_complete", "reflection_entry_complete"],
            "shield": ["shield_module_complete", "shield_checklist_item"],
            "civic_radar": ["civic_radar_action_taken"],
            "engagement": ["daily_login", "streak_bonus_7", "streak_bonus_30"],
            "community": ["community_contribution", "peer_recognition"]
        }
    }


@app.get("/mic/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(
    db: Session = Depends(get_db),
    limit: int = Query(10, le=100),
    by: str = Query("balance", pattern="^(balance|lifetime)$")
):
    """Get MIC leaderboard (top earners)"""
    order_column = Wallet.balance_mic if by == "balance" else Wallet.lifetime_earned
    
    wallets = (
        db.query(Wallet)
        .order_by(desc(order_column))
        .limit(limit)
        .all()
    )
    
    return [
        {
            "rank": i + 1,
            "civic_id": w.civic_id,
            "balance": w.balance_mic,
            "lifetime_earned": w.lifetime_earned
        }
        for i, w in enumerate(wallets)
    ]


@app.get("/mic/stats", response_model=StatsResponse)
async def get_stats(db: Session = Depends(get_db)):
    """Get global MIC statistics"""
    total_wallets = db.query(Wallet).count()
    total_mic = db.query(func.sum(Wallet.lifetime_earned)).scalar() or 0.0
    total_events = db.query(MICEvent).count()
    
    # Get top earning source
    top_source = (
        db.query(MICEvent.source, func.sum(MICEvent.final_amount).label("total"))
        .group_by(MICEvent.source)
        .order_by(desc("total"))
        .first()
    )
    
    return {
        "total_wallets": total_wallets,
        "total_mic_distributed": total_mic,
        "total_events": total_events,
        "top_earning_source": top_source[0] if top_source else None
    }


@app.get("/mic/balance/{civic_id}")
async def get_balance_by_civic_id(civic_id: str, db: Session = Depends(get_db)):
    """Get balance by Civic ID (public endpoint)"""
    wallet = db.query(Wallet).filter(Wallet.civic_id == civic_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Civic ID not found")
    
    return {
        "civic_id": civic_id,
        "balance": wallet.balance_mic,
        "lifetime_earned": wallet.lifetime_earned
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8001)))
