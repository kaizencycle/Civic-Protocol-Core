"""MNS mesh ingest and public registry mirror."""

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from ledger.app.mesh.registry import load_mesh_registry, registry_cache_mtime_iso
from ledger.app.db import LEDGER_DB_PATH
from ledger.app.routes.oaa_memory import persist_oaa_entries_from_body

router = APIRouter(prefix="/mesh", tags=["mesh"])


def _hybrid_ipfs_enabled() -> bool:
    """Mirror ledger.ipfs_bridge.hybrid_ipfs_enabled without importing ipfs_bridge at startup."""
    return os.getenv("HYBRID_LEDGER_MODE", "").lower() in ("1", "true", "yes")


def _ipfs_pin_on_ingest() -> bool:
    """Mirror ledger.ipfs_bridge.ipfs_ingest_async_enabled."""
    return os.getenv("IPFS_PIN_ON_INGEST", "true").lower() in ("1", "true", "yes")


def _schedule_pin_if_hybrid(entry_id: str) -> None:
    """Lazy import: avoids base58/ipfshttpclient when hybrid IPFS is off (e.g. Render)."""
    if not _hybrid_ipfs_enabled() or not _ipfs_pin_on_ingest():
        return
    from ledger.ipfs_bridge import schedule_pin_mesh_entry

    schedule_pin_mesh_entry(LEDGER_DB_PATH, entry_id)


def _mesh_token_expected() -> str:
    token = os.getenv("MOBIUS_MESH_TOKEN", "").strip()
    return f"Bearer {token}" if token else ""


def generate_id(entry: dict) -> str:
    """Deterministic ID for entries missing one."""
    key = f"{entry.get('sha', '')}:{entry.get('timestamp', '')}:{entry.get('title', '')}"
    return f"EPICON-MNS-{hashlib.sha256(key.encode()).hexdigest()[:8]}"


@router.post("/ingest")
async def mesh_ingest(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_mns_node: Optional[str] = Header(None, alias="X-MNS-Node"),
):
    """Receive EPICON ledger feed from a mesh node."""
    from ledger.app.db import get_db_connection

    expected = _mesh_token_expected()
    if not expected or not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")

    if not x_mns_node:
        raise HTTPException(status_code=403, detail="node_not_registered: missing X-MNS-Node")

    registry, fetch_ok = load_mesh_registry()
    node = next(
        (n for n in registry.get("nodes", []) if n.get("node_id") == x_mns_node),
        None,
    )
    # OAA journal forwarder may not appear in Substrate registry yet
    if x_mns_node == "oaa-api-library":
        node = node or {"tier": "service"}
    elif fetch_ok and not node:
        raise HTTPException(
            status_code=403, detail=f"node_not_registered: {x_mns_node}"
        )

    body: Any = await request.json()
    entries: List[Any] = body if isinstance(body, list) else body.get("entries", [])

    if not entries:
        return {
            "ok": True,
            "received": 0,
            "stored": 0,
            "node": x_mns_node,
            "proof_hash": hashlib.sha256(
                json.dumps(
                    {"node": x_mns_node, "count": 0, "at": _utc_iso()},
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            "timestamp": _utc_iso(),
        }

    tier = (node or {}).get("tier", "observer")
    stored = 0
    capped = entries[:100]

    oaa_batch: List[dict] = []
    mesh_batch: List[dict] = []
    for entry in capped:
        if not isinstance(entry, dict):
            continue
        ptype = entry.get("type") or entry.get("payload_type")
        if ptype == "OAA_MEMORY_ENTRY_V1":
            oaa_batch.append(entry)
        else:
            mesh_batch.append(entry)

    oaa_result: dict = {"stored": 0, "duplicates": 0, "errors": []}
    if oaa_batch:
        if x_mns_node != "oaa-api-library":
            raise HTTPException(
                status_code=400,
                detail="OAA_MEMORY_ENTRY_V1 requires X-MNS-Node: oaa-api-library",
            )
        oaa_result = persist_oaa_entries_from_body(oaa_batch, source="oaa-api-library")
        stored += int(oaa_result.get("stored", 0))

    with get_db_connection() as conn:
        for entry in mesh_batch:
            eid = entry.get("id") or generate_id(entry)
            ts = entry.get("timestamp") or _utc_iso()
            title = entry.get("title", "")
            if title is not None:
                title = str(title)
            sha = entry.get("sha", "")
            if sha is not None:
                sha = str(sha)
            raw = json.dumps(entry, sort_keys=True)
            try:
                cur = conn.execute(
                    """
                    INSERT INTO mesh_entries
                      (id, node_id, node_tier, timestamp, title, sha, source, raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(eid),
                        x_mns_node,
                        str(tier),
                        str(ts),
                        title,
                        sha,
                        "mesh-node",
                        raw,
                    ),
                )
                if cur.rowcount == 1:
                    stored += 1
                    _schedule_pin_if_hybrid(str(eid))
            except Exception as e:
                print(f"mesh_ingest entry error: {e}")
        conn.commit()

    proof_input = json.dumps(
        {
            "node": x_mns_node,
            "count": stored,
            "oaa": oaa_result,
            "at": _utc_iso(),
        },
        sort_keys=True,
    )
    proof_hash = hashlib.sha256(proof_input.encode()).hexdigest()

    out: dict = {
        "ok": True,
        "received": len(entries),
        "stored": stored,
        "node": x_mns_node,
        "proof_hash": proof_hash,
        "timestamp": _utc_iso(),
    }
    if oaa_batch:
        out["oaa_memory"] = oaa_result
    return out


@router.get("/entries/ipfs")
async def mesh_entries_ipfs(
    limit: int = 100,
    offset: int = 0,
    content_addressed: Optional[int] = None,
):
    """
    List mesh rows with IPFS CIDs (for MIC indexer / sovereign sync).
    `content_addressed=1` filters rows that have been pinned.
    """
    from ledger.app.db import get_db_connection

    lim = max(1, min(limit, 500))
    off = max(0, offset)
    with get_db_connection() as conn:
        if content_addressed == 1:
            cur = conn.execute(
                """
                SELECT id, node_id, ipfs_cid, pinned_at, pin_count, timestamp
                FROM mesh_entries
                WHERE content_addressed = 1 AND ipfs_cid IS NOT NULL
                ORDER BY datetime(COALESCE(pinned_at, timestamp)) DESC
                LIMIT ? OFFSET ?
                """,
                (lim, off),
            )
        else:
            cur = conn.execute(
                """
                SELECT id, node_id, ipfs_cid, pinned_at, pin_count, timestamp
                FROM mesh_entries
                ORDER BY datetime(timestamp) DESC
                LIMIT ? OFFSET ?
                """,
                (lim, off),
            )
        rows = [dict(r) for r in cur.fetchall()]
    return {
        "ok": True,
        "schema": "MNS_MESH_IPFS_INDEX_V1",
        "count": len(rows),
        "entries": rows,
        "timestamp": _utc_iso(),
    }


@router.get("/nodes")
async def mesh_nodes():
    """Mirror mesh/registry.json from Substrate (cached)."""
    registry, _ = load_mesh_registry()
    nodes = registry.get("nodes", [])
    return {
        "ok": True,
        "schema": "MNS_REGISTRY_V1",
        "mesh_version": registry.get("mesh_version", "1.0"),
        "node_count": len(nodes),
        "nodes": nodes,
        "cached_at": registry_cache_mtime_iso(),
        "timestamp": _utc_iso(),
    }


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
