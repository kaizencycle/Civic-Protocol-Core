from fastapi import FastAPI, Depends, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from typing import List, Optional
import orjson

from .config import settings
from .schemas import HealthOut, IngestEvent, BalanceOut, SupplyOut, EventOut
from .storage import SessionLocal, init_db, get_or_create_account, apply_event, compute_supply
from .models import Account, Balance, Event

app = FastAPI(title="GIC Indexing API")

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda r, e: HTTPException(status_code=429, detail="Too many requests"))
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/health", response_model=HealthOut)
@limiter.limit("10/second")
def health(request: Request):
    return HealthOut()

# ---------- READ ----------
@app.get("/supply", response_model=SupplyOut)
def get_supply(db: Session = Depends(get_db)):
    return SupplyOut(**compute_supply(db))

@app.get("/balances/{handle}", response_model=BalanceOut)
def get_balance(handle: str, db: Session = Depends(get_db)):
    acct = get_or_create_account(db, handle)
    bal = db.execute(select(Balance).where(Balance.account_id==acct.id)).scalar_one()
    gic_from_xp = bal.xp * settings.XP_TO_GIC_RATIO
    total = bal.gic + gic_from_xp
    return BalanceOut(handle=handle, xp=bal.xp, gic=bal.gic, gic_from_xp=gic_from_xp, total_gic=total)

@app.get("/events", response_model=List[EventOut])
def list_events(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.execute(select(Event).order_by(desc(Event.created_at)).limit(limit)).scalars().all()
    out = []
    for e in rows:
        out.append(EventOut(
            id=e.id, kind=e.kind, amount=e.amount, unit=e.unit,
            actor=e.actor.handle if e.actor else None,
            target=e.target.handle if e.target else None,
            created_at=str(e.created_at), meta=e.meta or {}
        ))
    return out

@app.get("/scores/{handle}", response_model=BalanceOut)
def get_scores(handle: str, db: Session = Depends(get_db)):
    # alias to balances for now; can extend to include governance weight, reputation, etc.
    return get_balance(handle, db)

# ---------- WRITE (secured) ----------
def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")
    return True

@app.post("/ingest/ledger", dependencies=[Depends(require_api_key)])
def ingest(ev: IngestEvent, db: Session = Depends(get_db)):
    apply_event(db, ev.kind, ev.amount, ev.unit, ev.actor, ev.target, ev.meta)
    return {"status":"ok"}