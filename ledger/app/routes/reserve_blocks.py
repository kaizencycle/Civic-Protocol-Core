"""C-355 Reserve Block hash anchors and portable .dat index (no full canon in CPC)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..db import get_db_connection
from ..reserve_dat import (
    build_reserve_block_index,
    load_reserve_block_index,
)

router = APIRouter(prefix="/api/reserve-blocks", tags=["reserve-blocks"])


def _agent_service_token() -> str:
    return os.environ.get("AGENT_SERVICE_TOKEN", "")


def _require_auth(authorization: str | None = Header(default=None)) -> None:
    token = _agent_service_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Anchor auth not configured (AGENT_SERVICE_TOKEN missing)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if authorization.removeprefix("Bearer ").strip() != token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


class ReserveBlockAnchor(BaseModel):
    block_id: str = Field(min_length=1)
    cycle: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    gi_at_seal: float = Field(ge=0.0, le=1.0)
    mic_minted: float = Field(ge=0.0)
    quorum_met: bool
    sealed_at: str = Field(min_length=1)
    sha256: str | None = None
    dat_path: str | None = None


def _anchor_entry_id(block_id: str) -> str:
    return f"RESERVE-BLOCK-{block_id}"


@router.post("/anchor", dependencies=[Depends(_require_auth)])
def anchor_reserve_block(anchor: ReserveBlockAnchor) -> dict[str, Any]:
    """
    Store a hash anchor for a sealed Reserve Block.
    CPC stores proof pointers only — full payload lives in the .dat artifact.
    """
    dat_path = anchor.dat_path or f"ledger/reserve-blocks/{anchor.block_id}.dat"
    now = datetime.now(timezone.utc).isoformat()
    raw: dict[str, Any] = {
        "event_type": "RESERVE_BLOCK_SEALED_V1",
        "block_id": anchor.block_id,
        "cycle": anchor.cycle,
        "sequence": anchor.sequence,
        "gi_at_seal": anchor.gi_at_seal,
        "mic_minted": anchor.mic_minted,
        "quorum_met": anchor.quorum_met,
        "sealed_at": anchor.sealed_at,
        "anchored_at": now,
        "dat_path": dat_path,
        "sha256": anchor.sha256,
        "cpc_stores_hash_anchors_not_full_canon": True,
    }

    entry_id = _anchor_entry_id(anchor.block_id)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO epicon_entries (id, timestamp, title, sha, source, raw)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                timestamp = excluded.timestamp,
                title     = excluded.title,
                sha       = excluded.sha,
                source    = excluded.source,
                raw       = excluded.raw
            """,
            (
                entry_id,
                now,
                f"Reserve Block sealed {anchor.block_id}",
                anchor.sha256 or "",
                "reserve-block-anchor",
                json.dumps(raw, sort_keys=True),
            ),
        )
        conn.commit()

    return {"status": "anchored", "block_id": anchor.block_id, "entry_id": entry_id}


@router.get("/index")
def get_reserve_block_index() -> dict[str, Any]:
    """Return the hash anchor index over portable .dat artifacts (file-backed, not DB)."""
    build_reserve_block_index()
    return load_reserve_block_index()
