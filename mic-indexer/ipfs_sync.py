"""
MIC Indexer — CID / mesh IPFS index sync (Phase 1 stub).

Pulls content-addressed mesh entry metadata from the Civic Ledger API
(`GET /mesh/entries/ipfs`) and stores a lightweight CID ledger in SqliteDict
for hybrid MIC workflows. Resolving full payloads from IPFS is optional when
`IPFS_API_ADDR` is configured.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx

LEDGER_MESH_IPFS_URL = os.getenv(
    "LEDGER_MESH_IPFS_URL",
    "http://127.0.0.1:8000/mesh/entries/ipfs",
).rstrip("/")


def fetch_mesh_ipfs_index(
    *,
    limit: int = 200,
    content_addressed: bool = True,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    params = {"limit": limit}
    if content_addressed:
        params["content_addressed"] = 1
    with httpx.Client(timeout=timeout) as client:
        r = client.get(LEDGER_MESH_IPFS_URL, params=params)
        r.raise_for_status()
        return r.json()


def sync_cids_to_local_index(
    index_db_path: str,
    *,
    limit: int = 200,
) -> int:
    """
    Persist latest CID rows into SqliteDict under key `ipfs_cid_index`.

    Returns number of rows merged.
    """
    from sqlitedict import SqliteDict

    body = fetch_mesh_ipfs_index(limit=limit, content_addressed=True)
    entries: List[Dict[str, Any]] = body.get("entries") or []
    with SqliteDict(index_db_path, autocommit=True) as db:
        idx: Dict[str, Any] = db.get("ipfs_cid_index", {})
        for row in entries:
            cid = row.get("ipfs_cid")
            if not cid:
                continue
            idx[cid] = {
                "mesh_id": row.get("id"),
                "node_id": row.get("node_id"),
                "pinned_at": row.get("pinned_at"),
                "pin_count": row.get("pin_count"),
                "synced_at": time.time(),
            }
        db["ipfs_cid_index"] = idx
    return len(entries)


def resolve_entry_from_ipfs(cid: str) -> Optional[Dict[str, Any]]:
    """Fetch JSON object from Kubo when IPFS_API_ADDR is reachable."""
    addr = os.getenv("IPFS_API_ADDR", "").strip()
    if not addr:
        return None
    if not addr.startswith("http"):
        addr = f"http://{addr}"
    try:
        import ipfshttpclient

        with ipfshttpclient.connect(addr.rstrip("/")) as client:
            raw = client.cat(cid)
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8"))
        return json.loads(raw)
    except Exception:
        return None
