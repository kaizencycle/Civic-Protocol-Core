from fastapi import FastAPI, Query, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlitedict import SqliteDict
from dateutil import parser as dtp
import os, httpx, json, math, time
from collections import defaultdict
from typing import Optional, List

from .config import settings
from .storage import SessionLocal, init_db, apply_event, compute_supply, get_or_create_account
from .schemas import HealthOut, IngestEvent, BalanceOut, SupplyOut, EventOut
from .models import Balance, Event, Account
from sqlalchemy import select, desc

try:
    import ipfs_sync
except ImportError:
    ipfs_sync = None

LAB4 = os.getenv("LAB4_BASE", "").rstrip("/")
POLICY_PATH = os.getenv("POLICY_PATH", "./policy.yaml")
INDEX_DB_PATH = os.getenv("INDEX_DB", "./data/index.db")

app = FastAPI(
    title="MIC Indexer",
    description="Mobius Integrity Credit (MIC) Indexer - tracks XP and MIC balances",
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

os.makedirs(os.path.dirname(INDEX_DB_PATH), exist_ok=True)

def load_policy():
    import yaml
    try:
        with open(POLICY_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {
            "version": "1.0.0",
            "rewards": {
                "epoch_seconds": 600,
                "per_event_baseline": {
                    "reflection_private": 1,
                    "reflection_public": 1.25,
                    "seed": 5,
                    "seal": 5
                },
                "daily_user_cap_mic": 50
            }
        }

POL = load_policy()

def epoch_of(ts_iso):
    # 10-min epochs
    t = int(dtp.isoparse(ts_iso).timestamp())
    return t // POL.get("rewards", {}).get("epoch_seconds", 600)

def day_of(ts_iso):
    return dtp.isoparse(ts_iso).date().isoformat()

def reward_for(event):
    base = 0
    per_event = POL.get("rewards", {}).get("per_event_baseline", {})
    if event["type"] == "sweep":
        vis = event.get("meta", {}).get("visibility", "private")
        base = per_event.get("reflection_private", 1)
        if vis == "public":
            base = per_event.get("reflection_public", 1.25)
    elif event["type"] == "seed":
        base = per_event.get("seed", 5)
    elif event["type"] == "seal":
        base = per_event.get("seal", 5)
    return base

def address_for(event):
    # TEMP: derive from companion_id or a supplied addr; replace with real addr later
    cmp_id = (event.get("meta", {}) or {}).get("companion_id") or "anon"
    return f"cmp::{cmp_id}"

# Dependency for API key verification
def verify_api_key(x_api_key: str = Header(None)):
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health", response_model=HealthOut)
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {
        "service": "mic-indexer",
        "version": "1.0.0",
        "docs": "/docs",
        "timestamp": int(time.time())
    }

@app.post("/recompute")
def recompute(from_date: str = Query(None), to_date: str = Query(None)):
    """
    Pulls day ledgers from Lab4 and recomputes balances.
    """
    done = []
    with SqliteDict(INDEX_DB_PATH, autocommit=True) as db:
        db["balances"] = db.get("balances", {})
        db["events"] = db.get("events", {})

        # naive: query the last N days from Lab4 (add your own /index endpoint later)
        candidate_dates = []
        if from_date and to_date:
            start = dtp.isoparse(from_date).date()
            end = dtp.isoparse(to_date).date()
            d = start
            while d <= end:
                candidate_dates.append(d.isoformat())
                d = dtp.isoparse((d + (dtp.relativedelta(days=+1))).isoformat()).date()
        else:
            # fallback: try today only
            candidate_dates.append(time.strftime("%Y-%m-%d"))

        balances = defaultdict(int)
        events = db["events"]

        for date_str in candidate_dates:
            try:
                # pull aggregated day JSON (you already printed this structure in lab4)
                url = f"{LAB4}/ledger/{date_str}"
                r = httpx.get(url, timeout=10.0)
                if r.status_code != 200:
                    continue
                day = r.json()
            except Exception:
                continue

            # apply events
            files = day.get("files", {})
            echo = files.get(f"{date_str}.echo.json", [])
            seed = files.get(f"{date_str}.seed.json")
            seal = files.get(f"{date_str}.seal.json")

            if seed:
                ev = seed | {"type": "seed"}
                amt = reward_for(ev)
                addr = address_for(ev)
                balances[addr] += amt
                events.setdefault(date_str, []).append({"addr": addr, "amt": amt, "ev": "seed", "ts": seed.get("ts")})

            for e in echo:
                ev = e | {"type": "sweep"}
                amt = reward_for(ev)
                addr = address_for(ev)
                balances[addr] += amt
                events.setdefault(date_str, []).append({"addr": addr, "amt": amt, "ev": "sweep", "ts": e.get("ts")})

            if seal:
                ev = seal | {"type": "seal"}
                amt = reward_for(ev)
                addr = address_for(ev)
                balances[addr] += amt
                events.setdefault(date_str, []).append({"addr": addr, "amt": amt, "ev": "seal", "ts": seal.get("ts")})

            done.append(date_str)

        # enforce per-user daily cap
        cap = POL.get("rewards", {}).get("daily_user_cap_mic", 50)
        # (Simple demo: not implemented per-day-per-user here; add when you promote to prod.)

        # save
        db["events"] = events
        # merge balances
        b = db["balances"]
        for k,v in balances.items():
            b[k] = b.get(k, 0) + v
        db["balances"] = b

    return {"ok": True, "days": done}

@app.get("/balance/{addr}")
def balance(addr: str):
    with SqliteDict(INDEX_DB_PATH, autocommit=False) as db:
        b = db.get("balances", {})
        return {"addr": addr, "balance": int(b.get(addr, 0))}

@app.get("/earn/events")
def earn_events(date: str | None = None):
    with SqliteDict(INDEX_DB_PATH, autocommit=False) as db:
        ev = db.get("events", {})
        if date:
            return {"date": date, "events": ev.get(date, [])}
        return {"dates": list(ev.keys())}

@app.get("/policy")
def get_policy():
    return POL

@app.get("/stats")
def stats():
    with SqliteDict(INDEX_DB_PATH, autocommit=False) as db:
        balances = db.get("balances", {})
        events = db.get("events", {})
        
        total_balance = sum(balances.values())
        total_events = sum(len(day_events) for day_events in events.values())
        
        return {
            "total_balance": total_balance,
            "total_events": total_events,
            "unique_addresses": len(balances),
            "days_processed": len(events),
            "policy_version": POL.get("version", "unknown")
        }

# === New SQLAlchemy-backed endpoints ===

@app.get("/supply", response_model=SupplyOut)
def get_supply():
    """Get total and circulating MIC supply"""
    with SessionLocal() as db:
        return compute_supply(db)

@app.get("/balances/{handle}", response_model=BalanceOut)
def get_balance(handle: str):
    """Get balance for a specific handle"""
    with SessionLocal() as db:
        acct = db.scalar(select(Account).where(Account.handle == handle))
        if not acct:
            raise HTTPException(404, f"Account '{handle}' not found")
        bal = db.scalar(select(Balance).where(Balance.account_id == acct.id))
        mic_from_xp = bal.xp * settings.XP_TO_MIC_RATIO
        return BalanceOut(
            handle=handle,
            xp=bal.xp,
            mic=bal.mic,
            mic_from_xp=mic_from_xp,
            total_mic=bal.mic + mic_from_xp
        )

@app.get("/scores/{handle}", response_model=BalanceOut)
def get_scores(handle: str):
    """Alias for balances (for compatibility)"""
    return get_balance(handle)

@app.get("/events", response_model=List[EventOut])
def list_events(limit: int = Query(50, le=500), offset: int = 0):
    """List recent events"""
    with SessionLocal() as db:
        rows = db.scalars(
            select(Event).order_by(desc(Event.created_at)).limit(limit).offset(offset)
        ).all()
        out = []
        for ev in rows:
            actor_handle = None
            target_handle = None
            if ev.actor_id:
                actor_acct = db.get(Account, ev.actor_id)
                actor_handle = actor_acct.handle if actor_acct else None
            if ev.target_id:
                target_acct = db.get(Account, ev.target_id)
                target_handle = target_acct.handle if target_acct else None
            out.append(EventOut(
                id=ev.id,
                kind=ev.kind,
                amount=ev.amount,
                unit=ev.unit,
                actor=actor_handle,
                target=target_handle,
                created_at=str(ev.created_at),
                meta=ev.meta or {}
            ))
        return out

@app.post("/ingest/ledger", status_code=201)
def ingest_event(body: IngestEvent, _: str = Depends(verify_api_key)):
    """Ingest an event from the ledger (requires API key)"""
    with SessionLocal() as db:
        apply_event(db, body.kind, body.amount, body.unit, body.actor, body.target, body.meta)
        db.commit()
    return {"ok": True, "event": body.model_dump()}


@app.post("/ipfs/sync")
def ipfs_sync_from_ledger(_: str = Depends(verify_api_key)):
    """
    Pull CID index from Civic Ledger `GET /mesh/entries/ipfs` into local SqliteDict.
    Requires LEDGER_MESH_IPFS_URL (see docker-compose.sovereign.yml).
    """
    if ipfs_sync is None:
        raise HTTPException(status_code=501, detail="ipfs_sync module unavailable")
    try:
        n = ipfs_sync.sync_cids_to_local_index(INDEX_DB_PATH, limit=500)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ok": True, "indexed_rows": n}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
