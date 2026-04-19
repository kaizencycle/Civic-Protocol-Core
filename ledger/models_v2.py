"""Typed views for mesh + IPFS hybrid rows (optional; ledger DB remains SQLite-first)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class MeshEntryV2(BaseModel):
    """Logical mesh row including optional IPFS index fields."""

    id: str
    node_id: str
    node_tier: str = "observer"
    timestamp: str
    title: Optional[str] = None
    sha: Optional[str] = None
    source: str = "mesh-node"
    raw: Any = None
    ipfs_cid: Optional[str] = None
    content_addressed: bool = False
    pinned_at: Optional[str] = None
    pin_count: int = Field(default=0, ge=0)


class MeshIPFSIndexRow(BaseModel):
    """Subset returned by GET /mesh/entries/ipfs."""

    id: str
    node_id: str
    ipfs_cid: Optional[str] = None
    pinned_at: Optional[str] = None
    pin_count: int = 0
    timestamp: str
