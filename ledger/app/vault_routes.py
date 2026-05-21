"""
Universal Vault API — receives writes from all authorized Mobius nodes.
Provides canonical vault state readable by any node on the network.

Auth: Bearer token via AGENT_SERVICE_TOKEN env var.
Public reads: /api/vault/global, /api/vault/seals (no auth required).
Authenticated writes: /api/vault/deposit, /api/vault/seal, /api/vault/attest.
"""
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from .vault_models import VaultAttestation, VaultDeposit, VaultSeal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vault", tags=["vault"])

AGENT_SERVICE_TOKEN = os.environ.get("AGENT_SERVICE_TOKEN", "")
QUORUM_REQUIRED = 5
BLOCK_SIZE = 50.0


# ── Auth ──────────────────────────────────────────────────────────────────────

def _require_auth(authorization: Optional[str] = Header(default=None)):
    if not AGENT_SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vault auth not configured (AGENT_SERVICE_TOKEN missing)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    token = authorization.removeprefix("Bearer ").strip()
    if token != AGENT_SERVICE_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


# ── Schemas ───────────────────────────────────────────────────────────────────

class DepositRequest(BaseModel):
    node_id: str = Field(..., description="e.g. 'node:terminal', 'node:atlas-paw'")
    cycle: str = Field(..., description="e.g. 'C-318'")
    amount_mic: float = Field(..., gt=0)
    tx_hash: Optional[str] = None
    depositor_agent: Optional[str] = None


class SealRequest(BaseModel):
    node_id: str
    cycle: str
    block_number: int
    seal_hash: str
    sentinel_quorum: Optional[dict] = None  # {agents: [...], completed_at: ...}


class AttestRequest(BaseModel):
    seal_id: str
    agent: str
    cycle: str
    node_id: str
    signature: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_deposit_id(node_id: str, cycle: str, amount_mic: float, ts: str) -> str:
    raw = f"{node_id}:{cycle}:{amount_mic}:{ts}"
    return "dep-" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _build_seal_id(node_id: str, cycle: str, block_number: int) -> str:
    return f"seal-{node_id}-{cycle}-{block_number}"


def _running_balance(db: Session, node_id: str) -> float:
    result = db.query(func.sum(VaultDeposit.amount_mic)).filter(
        VaultDeposit.node_id == node_id
    ).scalar()
    return round(result or 0.0, 6)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/deposit", dependencies=[Depends(_require_auth)])
def create_deposit(body: DepositRequest, db: Session = Depends(get_db)):
    """Record a MIC deposit from an authorized node."""
    ts = datetime.now(timezone.utc).isoformat()
    deposit_id = _build_deposit_id(body.node_id, body.cycle, body.amount_mic, ts)

    # Idempotency: if tx_hash supplied and already exists, return existing
    if body.tx_hash:
        existing = db.query(VaultDeposit).filter(
            VaultDeposit.tx_hash == body.tx_hash,
            VaultDeposit.node_id == body.node_id,
        ).first()
        if existing:
            return {
                "ok": True,
                "deposit_id": existing.deposit_id,
                "idempotent": True,
                "running_balance": existing.cumulative_balance,
            }

    deposit = VaultDeposit(
        deposit_id=deposit_id,
        node_id=body.node_id,
        cycle=body.cycle,
        amount_mic=body.amount_mic,
        tx_hash=body.tx_hash,
        depositor_agent=body.depositor_agent,
    )
    db.add(deposit)
    db.flush()
    running = _running_balance(db, body.node_id)
    deposit.cumulative_balance = running
    db.commit()
    db.refresh(deposit)

    in_progress = running % BLOCK_SIZE
    block_number = int(running // BLOCK_SIZE) + (1 if in_progress > 0 else 0)

    return {
        "ok": True,
        "deposit_id": deposit_id,
        "running_balance": running,
        "in_progress_balance": round(in_progress, 6),
        "block_number": block_number,
        "block_progress_pct": round((in_progress / BLOCK_SIZE) * 100, 1),
    }


@router.post("/seal", dependencies=[Depends(_require_auth)])
def create_seal(body: SealRequest, db: Session = Depends(get_db)):
    """Register a Reserve Block seal from an authorized node."""
    seal_id = _build_seal_id(body.node_id, body.cycle, body.block_number)

    existing = db.query(VaultSeal).filter(VaultSeal.seal_id == seal_id).first()
    if existing:
        return {
            "ok": True,
            "seal_id": seal_id,
            "idempotent": True,
            "immortalized": existing.immortalized,
            "substrate_event_hash": existing.substrate_event_hash,
        }

    quorum_json = json.dumps(body.sentinel_quorum) if body.sentinel_quorum else None
    quorum_count = len(body.sentinel_quorum.get("agents", [])) if body.sentinel_quorum else 0

    canonical = json.dumps(
        {
            "seal_id": seal_id,
            "node_id": body.node_id,
            "cycle": body.cycle,
            "block_number": body.block_number,
            "seal_hash": body.seal_hash,
        },
        sort_keys=True,
    )
    substrate_event_hash = hashlib.sha256(canonical.encode()).hexdigest()
    immortalized = quorum_count >= QUORUM_REQUIRED

    seal = VaultSeal(
        seal_id=seal_id,
        node_id=body.node_id,
        cycle=body.cycle,
        block_number=body.block_number,
        seal_hash=body.seal_hash,
        sentinel_quorum=quorum_json,
        attestations_count=quorum_count,
        immortalized=immortalized,
        substrate_event_hash=substrate_event_hash,
        immortalized_at=datetime.now(timezone.utc) if immortalized else None,
    )
    db.add(seal)
    db.commit()
    db.refresh(seal)

    logger.info(
        "Seal registered: %s node=%s cycle=%s block=%d immortalized=%s",
        seal_id, body.node_id, body.cycle, body.block_number, immortalized,
    )

    return {
        "ok": True,
        "seal_id": seal_id,
        "immortalized": immortalized,
        "substrate_event_hash": substrate_event_hash,
        "attestations_count": quorum_count,
        "quorum_met": immortalized,
    }


@router.post("/attest", dependencies=[Depends(_require_auth)])
def create_attestation(body: AttestRequest, db: Session = Depends(get_db)):
    """Add a sentinel agent attestation to a pending seal."""
    seal = db.query(VaultSeal).filter(VaultSeal.seal_id == body.seal_id).first()
    if not seal:
        raise HTTPException(status_code=404, detail=f"Seal {body.seal_id} not found")

    existing = db.query(VaultAttestation).filter(
        VaultAttestation.seal_id == body.seal_id,
        VaultAttestation.agent == body.agent,
    ).first()
    if existing:
        return {"ok": True, "idempotent": True, "agent": body.agent, "seal_id": body.seal_id}

    att = VaultAttestation(
        seal_id=body.seal_id,
        agent=body.agent,
        cycle=body.cycle,
        node_id=body.node_id,
        signature=body.signature,
    )
    db.add(att)

    total = (
        db.query(func.count(VaultAttestation.id))
        .filter(VaultAttestation.seal_id == body.seal_id)
        .scalar()
        + 1  # +1 for the one we just added (pre-commit)
    )
    seal.attestations_count = total
    if total >= QUORUM_REQUIRED and not seal.immortalized:
        seal.immortalized = True
        seal.immortalized_at = datetime.now(timezone.utc)
        logger.info("Seal %s IMMORTALIZED — quorum achieved (%d/5)", body.seal_id, total)

    db.commit()

    return {
        "ok": True,
        "seal_id": body.seal_id,
        "agent": body.agent,
        "attestations_received": total,
        "quorum_met": seal.immortalized,
        "quorum_needed": max(0, QUORUM_REQUIRED - total),
    }


@router.get("/global")
def get_vault_global(db: Session = Depends(get_db)):
    """
    Public canonical vault state across all network nodes.
    No auth required — this is the universal read endpoint.
    """
    total_deposits = db.query(func.sum(VaultDeposit.amount_mic)).scalar() or 0.0
    total_seals = db.query(func.count(VaultSeal.id)).scalar() or 0
    immortalized_seals = (
        db.query(func.count(VaultSeal.id))
        .filter(VaultSeal.immortalized.is_(True))
        .scalar()
        or 0
    )
    latest_seal = db.query(VaultSeal).order_by(VaultSeal.created_at.desc()).first()

    node_rows = (
        db.query(
            VaultDeposit.node_id,
            func.sum(VaultDeposit.amount_mic).label("balance"),
            func.count(VaultDeposit.id).label("deposits"),
        )
        .group_by(VaultDeposit.node_id)
        .all()
    )
    nodes = [
        {"node_id": r.node_id, "balance": round(r.balance, 6), "deposits": r.deposits}
        for r in node_rows
    ]

    return {
        "ok": True,
        "vault_id": "vault-global",
        "total_balance": round(total_deposits, 6),
        "sealed_blocks": immortalized_seals,
        "total_seals_registered": total_seals,
        "in_progress_balance": round(total_deposits % BLOCK_SIZE, 6),
        "last_seal": (
            {
                "seal_id": latest_seal.seal_id,
                "cycle": latest_seal.cycle,
                "node_id": latest_seal.node_id,
                "immortalized": latest_seal.immortalized,
                "created_at": latest_seal.created_at.isoformat(),
            }
            if latest_seal
            else None
        ),
        "nodes": nodes,
        "network": "mobius-substrate",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/seals")
def list_seals(
    limit: int = 50,
    node_id: Optional[str] = None,
    immortalized_only: bool = False,
    db: Session = Depends(get_db),
):
    """Public seal history — filterable by node and immortalization status."""
    q = db.query(VaultSeal)
    if node_id:
        q = q.filter(VaultSeal.node_id == node_id)
    if immortalized_only:
        q = q.filter(VaultSeal.immortalized.is_(True))
    seals = q.order_by(VaultSeal.created_at.desc()).limit(min(limit, 200)).all()

    return {
        "ok": True,
        "count": len(seals),
        "seals": [
            {
                "seal_id": s.seal_id,
                "node_id": s.node_id,
                "cycle": s.cycle,
                "block_number": s.block_number,
                "seal_hash": s.seal_hash,
                "immortalized": s.immortalized,
                "attestations_count": s.attestations_count,
                "substrate_event_hash": s.substrate_event_hash,
                "created_at": s.created_at.isoformat(),
                "immortalized_at": s.immortalized_at.isoformat() if s.immortalized_at else None,
            }
            for s in seals
        ],
    }
