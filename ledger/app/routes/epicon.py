"""EPICON feed (local ledger file + ingested mesh entries)."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from ledger.app.db import get_db_connection, sync_ledger_feed_json_to_epicon_entries

router = APIRouter(tags=["epicon"])


@router.get("/epicon/feed")
async def epicon_feed(
    limit: int = 50,
    node: Optional[str] = None,
    source: Optional[str] = None,
):
    """Unified EPICON feed: ledger/feed.json rows plus ingested mesh_entries."""
    lim = max(1, min(limit, 200))

    with get_db_connection() as conn:
        sync_ledger_feed_json_to_epicon_entries(conn)
        cur = conn.execute(
            """
            SELECT id, node_id, node_tier, timestamp, title, sha, source, raw FROM (
                SELECT
                    id, 'civic-protocol-core' AS node_id,
                    'contributor' AS node_tier,
                    timestamp, title, sha, source, raw
                FROM epicon_entries
                WHERE (? IS NULL OR source = ?)
                UNION ALL
                SELECT id, node_id, node_tier, timestamp, title, sha, source, raw
                FROM mesh_entries
                WHERE (? IS NULL OR node_id = ?)
            ) combined
            ORDER BY datetime(timestamp) DESC
            LIMIT ?
            """,
            (source, source, node, node, lim),
        )
        rows = cur.fetchall()

    entries: List[Dict[str, Any]] = []
    for row in rows:
        raw_obj: Dict[str, Any] = {}
        if row["raw"]:
            try:
                raw_obj = json.loads(row["raw"])
            except json.JSONDecodeError:
                raw_obj = {}
        base = {
            "id": row["id"],
            "node_id": row["node_id"],
            "tier": row["node_tier"],
            "timestamp": row["timestamp"],
            "title": row["title"],
            "sha": row["sha"],
            "source": row["source"],
        }
        merged = {**base, **raw_obj}
        entries.append(merged)

    return {
        "ok": True,
        "schema": "MNS_FEED_V1",
        "node_id": "civic-protocol-core",
        "count": len(entries),
        "entries": entries,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
