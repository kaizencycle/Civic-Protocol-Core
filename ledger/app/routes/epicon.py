"""EPICON feed (local ledger file + ingested mesh entries)."""

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from ..db import get_db_connection, sync_ledger_feed_json_to_epicon_entries

router = APIRouter(tags=["epicon"])

_AGENT_SERVICE_TOKEN = os.environ.get("AGENT_SERVICE_TOKEN", "")


def _require_auth(authorization: str | None = Header(default=None)) -> None:
    if not _AGENT_SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingest auth not configured (AGENT_SERVICE_TOKEN missing)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if authorization.removeprefix("Bearer ").strip() != _AGENT_SERVICE_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


class IngestEntry(BaseModel):
    id: str
    timestamp: str
    title: str | None = None
    sha: str | None = None
    source: str = "mesh-node"
    raw: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    entries: list[IngestEntry]


@router.post("/api/epicon/ingest", dependencies=[Depends(_require_auth)])
def epicon_ingest(body: IngestRequest):
    """
    Ingest EPICON entries from an authorized node into the ledger.
    Idempotent — duplicate IDs update existing rows (upsert).
    """
    if not body.entries:
        raise HTTPException(status_code=400, detail="entries list is empty")

    with get_db_connection() as conn:
        before = conn.execute("SELECT COUNT(*) FROM epicon_entries").fetchone()[0]
        for entry in body.entries:
            raw_str = json.dumps(entry.raw, sort_keys=True) if entry.raw else "{}"
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
                (entry.id, entry.timestamp, entry.title, entry.sha, entry.source, raw_str),
            )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM epicon_entries").fetchone()[0]

    inserted = after - before

    return {
        "ok": True,
        "received": len(body.entries),
        "inserted": inserted,
        "updated": len(body.entries) - inserted,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/epicon/feed")
async def epicon_feed(
    limit: int = 50,
    node: str | None = None,
    source: str | None = None,
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

    entries: list[dict[str, Any]] = []
    for row in rows:
        raw_obj: dict[str, Any] = {}
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
