"""C-357 Reserve Block .dat hash anchor endpoints (NDJSON cold canon path).

Routes:
  POST /api/canon/reserve-blocks/anchor   — store a .dat file hash anchor
  GET  /api/canon/reserve-blocks/manifest — list all anchors + chain state
  GET  /api/canon/reserve-blocks/verify   — verify anchored chain continuity

EPICON: C-357 | RESERVE_BLOCK_DAT_CANONIZATION
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from ..db import get_db_connection

router = APIRouter(prefix="/api/canon", tags=["canon"])


def _normalize_sha256_digest(value: str) -> str:
    """Accept sha256:<hex> or bare 64-char hex; store as sha256:<hex>."""
    raw = value.removeprefix("sha256:").strip().lower()
    if len(raw) != 64 or not all(ch in "0123456789abcdef" for ch in raw):
        raise ValueError("hash must be sha256:<64-char-hex> or a 64-character hex digest")
    return f"sha256:{raw}"


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


class DatHashAnchorPayload(BaseModel):
    dat_file: str = Field(..., max_length=32)
    file_hash: str = Field(..., max_length=80)
    block_range_start: int = Field(..., ge=1)
    block_range_end: int = Field(..., ge=1)
    block_count: int = Field(..., ge=1)
    chain_tip_hash: str = Field(..., max_length=80)
    manifest_hash: str | None = Field(None, max_length=80)
    version: str = Field(..., max_length=10)
    canonized_at: str = Field(...)

    @field_validator("file_hash", "chain_tip_hash")
    @classmethod
    def _validate_required_hash(cls, value: str) -> str:
        return _normalize_sha256_digest(value)

    @field_validator("manifest_hash")
    @classmethod
    def _validate_optional_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_sha256_digest(value)


class DatHashAnchorResponse(BaseModel):
    status: str
    action: str
    dat_file: str
    blocks: str
    chain_tip: str


class DatManifestEntry(BaseModel):
    id: int
    dat_file: str
    file_hash: str
    block_range_start: int
    block_range_end: int
    block_count: int
    chain_tip_hash: str
    manifest_hash: str | None
    version: str
    canonized_at: str
    created_at: str


class DatManifestResponse(BaseModel):
    total_dat_files: int
    total_blocks_anchored: int
    total_mic_anchored: float
    chain_tip: str | None
    chain_tip_hash: str | None
    anchors: list[DatManifestEntry]


class ChainVerifyResponse(BaseModel):
    valid: bool
    verified_files: int
    verified_blocks: int
    chain_tip: str | None
    error: str | None = None


@router.post("/reserve-blocks/anchor", response_model=DatHashAnchorResponse)
def anchor_dat_file(
    payload: DatHashAnchorPayload,
    _: None = Depends(_require_auth),
) -> DatHashAnchorResponse:
    """Store hash anchor for a .dat Reserve Block file (idempotent on same hash)."""
    if payload.block_range_end < payload.block_range_start:
        raise HTTPException(400, "block_range_end must be >= block_range_start")

    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT file_hash FROM dat_hash_anchors WHERE dat_file = ?",
            (payload.dat_file,),
        ).fetchone()

        if existing:
            if existing[0] != payload.file_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Hash conflict for {payload.dat_file}: "
                        f"stored={existing[0][:20]}..., received={payload.file_hash[:20]}..."
                    ),
                )
            return DatHashAnchorResponse(
                status="ok",
                action="idempotent",
                dat_file=payload.dat_file,
                blocks=f"{payload.block_range_start}–{payload.block_range_end}",
                chain_tip=payload.chain_tip_hash[:20] + "...",
            )

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO dat_hash_anchors (
                dat_file, file_hash, block_range_start, block_range_end,
                block_count, chain_tip_hash, manifest_hash, version,
                canonized_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.dat_file,
                payload.file_hash,
                payload.block_range_start,
                payload.block_range_end,
                payload.block_count,
                payload.chain_tip_hash,
                payload.manifest_hash,
                payload.version,
                payload.canonized_at,
                now,
            ),
        )
        conn.commit()

    return DatHashAnchorResponse(
        status="ok",
        action="anchored",
        dat_file=payload.dat_file,
        blocks=f"{payload.block_range_start}–{payload.block_range_end}",
        chain_tip=payload.chain_tip_hash[:20] + "...",
    )


@router.get("/reserve-blocks/manifest", response_model=DatManifestResponse)
def get_manifest() -> DatManifestResponse:
    """Return all anchored .dat files and chain state (public)."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, dat_file, file_hash, block_range_start, block_range_end,
                   block_count, chain_tip_hash, manifest_hash, version,
                   canonized_at, created_at
            FROM dat_hash_anchors
            ORDER BY block_range_start ASC
            """
        ).fetchall()

    anchors = [
        DatManifestEntry(
            id=r[0],
            dat_file=r[1],
            file_hash=r[2],
            block_range_start=r[3],
            block_range_end=r[4],
            block_count=r[5],
            chain_tip_hash=r[6],
            manifest_hash=r[7],
            version=r[8],
            canonized_at=str(r[9]),
            created_at=str(r[10]),
        )
        for r in rows
    ]

    total_blocks = sum(a.block_count for a in anchors)
    chain_tip_row = anchors[-1] if anchors else None

    return DatManifestResponse(
        total_dat_files=len(anchors),
        total_blocks_anchored=total_blocks,
        total_mic_anchored=total_blocks * 50.0,
        chain_tip=chain_tip_row.dat_file if chain_tip_row else None,
        chain_tip_hash=chain_tip_row.chain_tip_hash if chain_tip_row else None,
        anchors=anchors,
    )


@router.get("/reserve-blocks/verify", response_model=ChainVerifyResponse)
def verify_chain() -> ChainVerifyResponse:
    """Verify anchored block ranges are contiguous (no gaps between files)."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT block_range_start, block_range_end, block_count, dat_file
            FROM dat_hash_anchors
            ORDER BY block_range_start ASC
            """
        ).fetchall()

    if not rows:
        return ChainVerifyResponse(
            valid=False,
            verified_files=0,
            verified_blocks=0,
            chain_tip=None,
            error="No anchors found — canonization not yet run",
        )

    verified_files = 0
    verified_blocks = 0
    expected_next_start = rows[0][0]

    for start, end, count, filename in rows:
        if start != expected_next_start:
            return ChainVerifyResponse(
                valid=False,
                verified_files=verified_files,
                verified_blocks=verified_blocks,
                chain_tip=None,
                error=f"Gap at {filename}: expected start={expected_next_start}, got start={start}",
            )

        expected_count = end - start + 1
        if count != expected_count:
            return ChainVerifyResponse(
                valid=False,
                verified_files=verified_files,
                verified_blocks=verified_blocks,
                chain_tip=None,
                error=f"{filename}: block_count={count} but range implies {expected_count}",
            )

        expected_next_start = end + 1
        verified_files += 1
        verified_blocks += count

    return ChainVerifyResponse(
        valid=True,
        verified_files=verified_files,
        verified_blocks=verified_blocks,
        chain_tip=rows[-1][3],
    )
