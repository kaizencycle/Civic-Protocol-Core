#!/usr/bin/env python3
"""
Civic Ledger API - The Blockchain Kernel

This is the central immutable anchor service that all Civic Protocol
components write to. Think of it as the "Bitcoin Core" for GIC.

Every reflection, shield action, companion event, and governance decision
gets anchored here as an immutable event in the ledger.
"""

import hashlib
import json
import logging
import os
import re
import time
import warnings
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .database import Base, check_db_health, engine
from .db import DATA_DIR, LEDGER_DB_PATH, assert_persistent_storage, get_db_connection
from .mcp_integrity import load_gi_state
from .observability import configure_logging, install_operational_middleware
from .routes import epicon, mcp_tools, mesh, oaa_memory, reserve_blocks, seal_reconciliation
from .vault_routes import router as vault_router

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # C-331: refuse ephemeral ledger storage in production (see db.py).
    assert_persistent_storage(DATA_DIR)
    yield
    await mcp_tools.mcp.shutdown()


app = FastAPI(
    title="Civic Ledger API",
    description="The blockchain kernel for Civic Protocol - immutable event anchoring",
    version="0.1.0",
    lifespan=_lifespan,
)
install_operational_middleware(app)

app.include_router(mesh.router)
app.include_router(epicon.router)
app.include_router(oaa_memory.router, prefix="/api")
app.include_router(seal_reconciliation.router)
app.include_router(reserve_blocks.router)
app.include_router(mcp_tools.mcp, prefix="/api/mcp")
app.include_router(vault_router)

# Create vault tables on cold start (idempotent against PostgreSQL or SQLite fallback)
Base.metadata.create_all(bind=engine)

# API Configuration
LAB4_API_BASE = os.getenv("LAB4_API_BASE", "https://hive-api-2le8.onrender.com")
LAB6_API_BASE = os.getenv("LAB6_API_BASE", "")
# Mobius Identity (JWT from /auth/login) — used when lab_source is identity or terminal
IDENTITY_API_BASE = (
    os.getenv("IDENTITY_API_BASE", "").strip()
    or os.getenv("IDENTITY_SERVICE_URL", "").strip()
)

if not IDENTITY_API_BASE:
    warnings.warn(
        "IDENTITY_API_BASE is not set. Attestations from lab_source "
        "'terminal' and 'identity' will fail with 400. "
        "Set IDENTITY_API_BASE to the Mobius Identity service base URL.",
        RuntimeWarning,
        stacklevel=1,
    )

logger.info("Using data directory: %s", DATA_DIR)
logger.info("Database path: %s", LEDGER_DB_PATH)

TOKEN_INTROSPECTION_CACHE_TTL_SECONDS = float(
    os.getenv("TOKEN_INTROSPECTION_CACHE_TTL_SECONDS", "30")
)
_token_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


@dataclass
class LedgerEvent:
    """Immutable ledger event"""
    event_id: str
    event_type: str
    civic_id: str
    lab_source: str  # "lab4", "lab6", "identity", "terminal", or "hive"
    payload: dict[str, Any]
    timestamp: str
    previous_hash: str
    event_hash: str
    signature: str | None = None


class AttestationRequest(BaseModel):
    """Request to attest an event to the ledger"""
    event_type: str
    civic_id: str
    lab_source: str
    payload: dict[str, Any]
    signature: str | None = None


class EventResponse(BaseModel):
    """Response for ledger events"""
    event_id: str
    event_type: str
    civic_id: str
    lab_source: str
    timestamp: str
    event_hash: str
    confirmed: bool


def clear_token_cache() -> None:
    """Clear cached token introspection results (used by tests and ops reload hooks)."""

    _token_cache.clear()


def _get_cached_token(token: str, lab_source: str) -> dict[str, Any] | None:
    if TOKEN_INTROSPECTION_CACHE_TTL_SECONDS <= 0:
        return None
    cache_key = (lab_source, token)
    cached = _token_cache.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.monotonic():
        _token_cache.pop(cache_key, None)
        return None
    return dict(payload)


def _cache_token(token: str, lab_source: str, payload: dict[str, Any]) -> None:
    if TOKEN_INTROSPECTION_CACHE_TTL_SECONDS <= 0:
        return
    expires_at = time.monotonic() + TOKEN_INTROSPECTION_CACHE_TTL_SECONDS
    _token_cache[(lab_source, token)] = (expires_at, dict(payload))


def verify_token(token: str, lab_source: str) -> dict[str, Any]:
    """Verify Bearer token via Lab4, Lab6, or Mobius Identity introspection."""
    cached = _get_cached_token(token, lab_source)
    if cached is not None:
        return cached

    if lab_source == "lab4":
        api_base = LAB4_API_BASE
    elif lab_source == "lab6":
        api_base = LAB6_API_BASE
    elif lab_source in ("identity", "terminal"):
        api_base = IDENTITY_API_BASE
    else:
        raise HTTPException(400, f"Unknown lab source: {lab_source}")

    if not api_base:
        if lab_source in ("identity", "terminal"):
            raise HTTPException(
                400,
                f"IDENTITY_API_BASE is not configured on the ledger server "
                f"(lab_source={lab_source!r}). Set IDENTITY_API_BASE on the "
                f"Render service to enable token introspection for this lab source.",
            )
        raise HTTPException(400, f"No API base configured for {lab_source}")

    base = api_base.rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{base}/auth/introspect",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("active") is False:
                raise HTTPException(401, "Token inactive")
            _cache_token(token, lab_source, payload)
            return payload
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            raise HTTPException(503, "Token introspection service unavailable") from e
        raise HTTPException(401, "Token verification failed") from e
    except httpx.RequestError as e:
        raise HTTPException(503, "Token introspection service unavailable") from e
    except Exception as e:
        logger.exception("Token verification error")
        raise HTTPException(500, "Token verification error") from e


def _civic_id_allowed_for_lab(
    request_civic_id: str, token_civic_id: str | None, lab_source: str
) -> bool:
    """Bind civic_id to the JWT for identity; allow synthetic mobius-* ids for terminal agents."""
    if not token_civic_id:
        return True
    if request_civic_id == token_civic_id:
        return True
    return bool(lab_source == "terminal" and request_civic_id.startswith("mobius-"))


# C-341: lab_source="hive" is a pseudonymous, unauthenticated lane for HIVE
# Citadel player events (citizen_history write-back). It is NOT the same
# trust tier as "identity"/"terminal" — there is no JWT to introspect, so
# civic_id is a client-generated, localStorage-persisted id that must match
# this pattern. _civic_id_allowed_for_lab is not used here: that function
# binds a request civic_id to an authenticated token's civic_id, and hive
# attestations carry no token at all.
HIVE_LAB_SOURCE = "hive"
_HIVE_CIVIC_ID_RE = re.compile(r"^mobius-anon-[A-Za-z0-9]{4,32}$")

HIVE_RATE_LIMIT_SECONDS = float(os.getenv("HIVE_RATE_LIMIT_SECONDS", "1.0"))
_hive_last_attest: dict[str, float] = {}


def _require_hive_civic_id(civic_id: str) -> None:
    """lab_source=hive requires a client-generated mobius-anon-<id> civic_id."""
    if not _HIVE_CIVIC_ID_RE.match(civic_id):
        raise HTTPException(
            403,
            "lab_source=hive requires civic_id matching 'mobius-anon-<id>' "
            "(client-generated, no account)",
        )


def _enforce_hive_rate_limit(civic_id: str) -> None:
    """Cheap per-civic_id throttle on the first public-write surface into the ledger."""
    if HIVE_RATE_LIMIT_SECONDS <= 0:
        return
    now = time.monotonic()
    last = _hive_last_attest.get(civic_id)
    if last is not None and (now - last) < HIVE_RATE_LIMIT_SECONDS:
        raise HTTPException(
            429,
            f"Rate limit exceeded for lab_source=hive "
            f"(max 1 attestation per {HIVE_RATE_LIMIT_SECONDS:g}s per civic_id)",
        )
    _hive_last_attest[civic_id] = now


def clear_hive_rate_limit() -> None:
    """Reset hive rate-limit state (used by tests)."""

    _hive_last_attest.clear()


def get_latest_event_hash() -> str:
    """Get the hash of the latest event in the chain"""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute("""
                SELECT event_hash FROM events
                ORDER BY created_at DESC LIMIT 1
            """)
            result = cursor.fetchone()
            return result[0] if result else "0" * 64  # Genesis hash
    except Exception:
        logger.exception("Error getting latest hash")
        return "0" * 64


def _latest_attestation_timestamp() -> str | None:
    try:
        with get_db_connection() as conn:
            cursor = conn.execute("""
                SELECT timestamp FROM events
                ORDER BY created_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception:
        logger.exception("Error getting latest attestation timestamp")
        return None


def _current_cycle(gi_state: dict[str, Any] | None) -> str:
    return str(
        os.getenv("CYCLE_ID", "").strip()
        or os.getenv("CURRENT_CYCLE", "").strip()
        or (gi_state or {}).get("cycle")
        or (gi_state or {}).get("cycleId")
        or "unknown"
    )


def _current_gi(gi_state: dict[str, Any] | None) -> float | None:
    if not gi_state:
        return None
    value = gi_state.get("global_integrity", gi_state.get("gi"))
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring non-numeric GI state value: %r", value)
        return None


def calculate_event_hash(event: LedgerEvent) -> str:
    """Calculate SHA-256 hash of the event"""
    event_data = f"{event.event_id}{event.event_type}{event.civic_id}{event.lab_source}{json.dumps(event.payload, sort_keys=True)}{event.timestamp}{event.previous_hash}"
    return hashlib.sha256(event_data.encode()).hexdigest()


def create_ledger_event(event_type: str, civic_id: str, lab_source: str,
                       payload: dict[str, Any], signature: str | None = None) -> LedgerEvent:
    """Create a new ledger event"""
    event_id = f"evt_{int(datetime.now().timestamp() * 1000)}_{hashlib.sha256(f'{civic_id}{event_type}'.encode()).hexdigest()[:8]}"
    timestamp = datetime.now(timezone.utc).isoformat()
    previous_hash = get_latest_event_hash()

    event = LedgerEvent(
        event_id=event_id,
        event_type=event_type,
        civic_id=civic_id,
        lab_source=lab_source,
        payload=payload,
        timestamp=timestamp,
        previous_hash=previous_hash,
        event_hash="",  # Will be calculated
        signature=signature
    )

    # Calculate event hash
    event.event_hash = calculate_event_hash(event)

    return event


@app.get("/")
def root():
    return {
        "service": "civic-ledger-api",
        "status": "ok",
        "docs": "/docs",
        "network": "mobius-substrate",
    }


@app.get("/health")
def health():
    """Health check endpoint"""
    # Check vault DB (PostgreSQL / SQLite fallback)
    db_status = check_db_health()
    if not db_status["ok"]:
        logger.error("Vault DB unhealthy: %s", db_status.get("error"))
        raise HTTPException(status_code=503, detail="Vault DB unhealthy")

    # Also verify the ledger event DB that /ledger/attest writes to
    try:
        with get_db_connection() as conn:
            conn.execute("SELECT COUNT(*) FROM events")
    except Exception as e:
        logger.exception("Ledger DB unhealthy")
        raise HTTPException(status_code=503, detail="Ledger DB unhealthy") from e

    return {
        "status": "ok",
        "service": "civic-ledger-api",
    }


@app.get("/pulse/state")
def pulse_state():
    """Return compact ledger pulse state for Layer-1 sync writers."""

    gi_state = load_gi_state()
    return {
        "cycle": _current_cycle(gi_state),
        "gi": _current_gi(gi_state),
        "attested_at": _latest_attestation_timestamp(),
    }


@app.post("/ledger/attest")
def attest_event(request: AttestationRequest,
                authorization: str | None = Header(None)):
    """Attest an event to the immutable ledger"""

    if request.lab_source == HIVE_LAB_SOURCE:
        # Pseudonymous, unauthenticated lane (C-341) — no Bearer token to verify.
        _require_hive_civic_id(request.civic_id)
        _enforce_hive_rate_limit(request.civic_id)
    else:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing or invalid authorization header")

        token = authorization[7:]  # Remove "Bearer " prefix

        # Verify token with the appropriate lab
        try:
            token_data = verify_token(token, request.lab_source)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(401, f"Token verification failed: {str(e)}") from e

        if request.lab_source in ("identity", "terminal"):
            token_civic = token_data.get("civic_id")
            if isinstance(token_civic, str) and token_civic and not _civic_id_allowed_for_lab(
                request.civic_id, token_civic, request.lab_source
            ):
                raise HTTPException(
                    403,
                    "civic_id must match the authenticated user or use mobius- prefix "
                    "when lab_source is terminal",
                )

    # Create ledger event
    event = create_ledger_event(
        event_type=request.event_type,
        civic_id=request.civic_id,
        lab_source=request.lab_source,
        payload=request.payload,
        signature=request.signature
    )

    # Store in database
    try:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO events (event_id, event_type, civic_id, lab_source,
                                  payload, timestamp, previous_hash, event_hash, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id, event.event_type, event.civic_id, event.lab_source,
                json.dumps(event.payload), event.timestamp, event.previous_hash,
                event.event_hash, event.signature
            ))

            # Update identity stats
            conn.execute("""
                INSERT OR REPLACE INTO identities (civic_id, lab_source, first_seen, last_seen, event_count)
                VALUES (?, ?,
                        COALESCE((SELECT first_seen FROM identities WHERE civic_id = ?), ?),
                        ?,
                        COALESCE((SELECT event_count FROM identities WHERE civic_id = ?), 0) + 1)
            """, (event.civic_id, event.lab_source, event.civic_id, event.timestamp,
                  event.timestamp, event.civic_id))

            conn.commit()
    except Exception as e:
        logger.exception("Database error while attesting event")
        raise HTTPException(500, "Database error") from e

    return EventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        civic_id=event.civic_id,
        lab_source=event.lab_source,
        timestamp=event.timestamp,
        event_hash=event.event_hash,
        confirmed=True
    )


@app.get("/ledger/events")
def get_events(civic_id: str | None = None,
               event_type: str | None = None,
               lab_source: str | None = None,
               since: str | None = None,
               limit: int = 100,
               offset: int = 0):
    """Get events from the ledger with optional filtering.

    `since` switches to ascending cursor mode for poll-based consumers
    (e.g. the HIVE world-update job): `since=<event_id>` returns events
    after that event, oldest first; `since=` (empty) starts from the
    beginning of the chain. Omitting `since` keeps the legacy
    newest-first listing with `offset` pagination.
    """

    filters = "WHERE 1=1"
    params: list[Any] = []

    if civic_id:
        filters += " AND civic_id = ?"
        params.append(civic_id)

    if event_type:
        filters += " AND event_type = ?"
        params.append(event_type)

    if lab_source:
        filters += " AND lab_source = ?"
        params.append(lab_source)

    try:
        with get_db_connection() as conn:
            if since is not None:
                after_rowid = 0
                if since:
                    cursor = conn.execute(
                        "SELECT rowid FROM events WHERE event_id = ?", (since,)
                    )
                    row = cursor.fetchone()
                    if not row:
                        raise HTTPException(404, f"since event_id {since!r} not found")
                    after_rowid = row[0]

                # filters is built only from fixed " AND <col> = ?" fragments
                # above; values are bound via params, never interpolated.
                query = (
                    "SELECT * FROM events " + filters + " AND rowid > ? "  # noqa: S608
                    "ORDER BY rowid ASC LIMIT ?"
                )
                cursor = conn.execute(query, [*params, after_rowid, limit])
            else:
                query = (
                    "SELECT * FROM events " + filters +  # noqa: S608
                    " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                )
                cursor = conn.execute(query, [*params, limit, offset])

            rows = cursor.fetchall()

            events = []
            for row in rows:
                events.append({
                    "event_id": row[0],
                    "event_type": row[1],
                    "civic_id": row[2],
                    "lab_source": row[3],
                    "payload": json.loads(row[4]),
                    "timestamp": row[5],
                    "previous_hash": row[6],
                    "event_hash": row[7],
                    "signature": row[8]
                })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Database error: {str(e)}") from e

    return {"events": events, "count": len(events)}


@app.get("/ledger/identity/{civic_id}")
def get_identity(civic_id: str):
    """Get identity information and stats"""

    try:
        with get_db_connection() as conn:
            # Get identity stats
            cursor = conn.execute("""
                SELECT civic_id, lab_source, first_seen, last_seen, event_count
                FROM identities WHERE civic_id = ?
            """, (civic_id,))

            identity_row = cursor.fetchone()
            if not identity_row:
                raise HTTPException(404, f"Identity {civic_id} not found")

            # Get recent events
            cursor = conn.execute("""
                SELECT event_type, timestamp, event_hash
                FROM events WHERE civic_id = ?
                ORDER BY created_at DESC LIMIT 10
            """, (civic_id,))

            recent_events = []
            for row in cursor.fetchall():
                recent_events.append({
                    "event_type": row[0],
                    "timestamp": row[1],
                    "event_hash": row[2]
                })
    except Exception as e:
        raise HTTPException(500, f"Database error: {str(e)}") from e

    return {
        "civic_id": identity_row[0],
        "lab_source": identity_row[1],
        "first_seen": identity_row[2],
        "last_seen": identity_row[3],
        "event_count": identity_row[4],
        "recent_events": recent_events
    }


@app.get("/ledger/stats")
def get_ledger_stats():
    """Get ledger statistics"""

    try:
        with get_db_connection() as conn:
            # Total events
            cursor = conn.execute("SELECT COUNT(*) FROM events")
            total_events = cursor.fetchone()[0]

            # Total identities
            cursor = conn.execute("SELECT COUNT(*) FROM identities")
            total_identities = cursor.fetchone()[0]

            # Events by type
            cursor = conn.execute("""
                SELECT event_type, COUNT(*) FROM events
                GROUP BY event_type ORDER BY COUNT(*) DESC
            """)
            events_by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # Events by lab
            cursor = conn.execute("""
                SELECT lab_source, COUNT(*) FROM events
                GROUP BY lab_source ORDER BY COUNT(*) DESC
            """)
            events_by_lab = {row[0]: row[1] for row in cursor.fetchall()}

            # Latest event
            cursor = conn.execute("""
                SELECT event_id, timestamp, event_type FROM events
                ORDER BY created_at DESC LIMIT 1
            """)
            latest_event = cursor.fetchone()
    except Exception as e:
        raise HTTPException(500, f"Database error: {str(e)}") from e

    return {
        "total_events": total_events,
        "total_identities": total_identities,
        "events_by_type": events_by_type,
        "events_by_lab": events_by_lab,
        "latest_event": {
            "event_id": latest_event[0],
            "timestamp": latest_event[1],
            "event_type": latest_event[2]
        } if latest_event else None
    }


@app.get("/ledger/chain")
def get_chain_info():
    """Get blockchain-like chain information"""

    try:
        with get_db_connection() as conn:
            # Get chain length
            cursor = conn.execute("SELECT COUNT(*) FROM events")
            chain_length = cursor.fetchone()[0]

            # Get latest block hash
            cursor = conn.execute("""
                SELECT event_hash FROM events
                ORDER BY created_at DESC LIMIT 1
            """)
            latest_hash = cursor.fetchone()
            latest_hash = latest_hash[0] if latest_hash else "0" * 64

            # Get genesis hash
            cursor = conn.execute("""
                SELECT event_hash FROM events
                ORDER BY created_at ASC LIMIT 1
            """)
            genesis_hash = cursor.fetchone()
            genesis_hash = genesis_hash[0] if genesis_hash else "0" * 64
    except Exception as e:
        raise HTTPException(500, f"Database error: {str(e)}") from e

    return {
        "chain_length": chain_length,
        "latest_hash": latest_hash,
        "genesis_hash": genesis_hash,
        "is_genesis": chain_length == 0
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
