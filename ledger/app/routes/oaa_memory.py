"""OAA sovereign memory proof — durable seal on Civic Ledger (C-286)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ledger.app.db import get_db_connection
from ledger.app.oaa_store import get_proof_by_hash, insert_oaa_proof, list_proofs

router = APIRouter(prefix="/oaa", tags=["oaa"])


def _expected_bearer() -> str:
    token = (
        os.getenv("OAA_MEMORY_API_TOKEN", "").strip()
        or os.getenv("MOBIUS_MESH_TOKEN", "").strip()
    )
    return f"Bearer {token}" if token else ""


class OaaMemoryEntryV1(BaseModel):
    """OAA journal line sealed on the civic ledger."""

    type: Literal["OAA_MEMORY_ENTRY_V1"] = "OAA_MEMORY_ENTRY_V1"
    agent: str = Field(..., min_length=1)
    cycle: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1)
    intent: Optional[str] = None
    hash: str = Field(..., min_length=8, max_length=128)
    previous_hash: Optional[str] = None
    timestamp: str = Field(..., min_length=1)


@router.post("/memory")
async def seal_oaa_memory(
    entry: OaaMemoryEntryV1,
    authorization: Optional[str] = Header(None),
):
    """
    Durable seal for OAA_MEMORY_ENTRY_V1 proofs.

    Auth: Bearer `OAA_MEMORY_API_TOKEN` (preferred) or `MOBIUS_MESH_TOKEN`.
    """
    expected = _expected_bearer()
    if not expected or not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")

    with get_db_connection() as conn:
        try:
            inserted, h = insert_oaa_proof(conn, entry.model_dump(), source="oaa-api-library")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        conn.commit()

    return {
        "ok": True,
        "accepted": True,
        "hash": h,
        "inserted": inserted,
        "duplicate": not inserted,
    }


@router.get("/memory/{proof_hash}")
async def get_oaa_memory_by_hash(proof_hash: str):
    """Lookup a sealed OAA proof by content hash."""
    with get_db_connection() as conn:
        row = get_proof_by_hash(conn, proof_hash)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "entry": row}


@router.get("/memory")
async def list_oaa_memory(
    source: Optional[str] = None,
    key_prefix: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """List recent OAA memory proofs (optional filters)."""
    with get_db_connection() as conn:
        rows = list_proofs(
            conn, source=source, key_prefix=key_prefix, limit=limit, offset=offset
        )
    return {"ok": True, "count": len(rows), "entries": rows}


def persist_oaa_entries_from_body(
    entries: List[Dict[str, Any]],
    *,
    source: str = "oaa-api-library",
) -> Dict[str, Any]:
    """Shared insert path for /api/oaa/memory and mesh/ingest OAA payloads."""
    stored = 0
    duplicates = 0
    errors: List[str] = []
    with get_db_connection() as conn:
        for raw in entries:
            if not isinstance(raw, dict):
                errors.append("non_object_entry")
                continue
            ptype = raw.get("type") or raw.get("payload_type")
            if ptype != "OAA_MEMORY_ENTRY_V1":
                errors.append(f"bad_type:{ptype}")
                continue
            try:
                entry = OaaMemoryEntryV1.model_validate(raw)
                ins, _h = insert_oaa_proof(conn, entry.model_dump(), source=source)
                if ins:
                    stored += 1
                else:
                    duplicates += 1
            except Exception as e:
                errors.append(str(e))
        conn.commit()
    return {"stored": stored, "duplicates": duplicates, "errors": errors}
