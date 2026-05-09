"""Typed views for mesh + IPFS hybrid rows (optional; ledger DB remains SQLite-first)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MeshEntryV2(BaseModel):
    """Logical mesh row including optional IPFS index fields."""

    id: str
    node_id: str
    node_tier: str = "observer"
    timestamp: str
    title: str | None = None
    sha: str | None = None
    source: str = "mesh-node"
    raw: Any = None
    ipfs_cid: str | None = None
    content_addressed: bool = False
    pinned_at: str | None = None
    pin_count: int = Field(default=0, ge=0)


class MeshIPFSIndexRow(BaseModel):
    """Subset returned by GET /mesh/entries/ipfs."""

    id: str
    node_id: str
    ipfs_cid: str | None = None
    pinned_at: str | None = None
    pin_count: int = 0
    timestamp: str
