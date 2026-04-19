"""Durable seal storage for OAA sovereign memory proofs (SQLite)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional, Tuple


def ensure_oaa_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS oaa_memory_proofs (
            hash TEXT PRIMARY KEY,
            payload_type TEXT NOT NULL,
            agent TEXT NOT NULL,
            cycle TEXT NOT NULL,
            key TEXT NOT NULL,
            intent TEXT,
            previous_hash TEXT,
            timestamp TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'oaa-api-library',
            raw TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_oaa_memory_agent ON oaa_memory_proofs(agent)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_oaa_memory_key ON oaa_memory_proofs(key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_oaa_memory_created ON oaa_memory_proofs(created_at DESC)"
    )


def insert_oaa_proof(
    conn: sqlite3.Connection,
    row: Dict[str, Any],
    *,
    source: str = "oaa-api-library",
) -> Tuple[bool, str]:
    """
    Insert one OAA_MEMORY_ENTRY_V1 (or compatible) proof row.

    Returns (inserted, hash). Duplicate hash → (False, hash).
    """
    ensure_oaa_table(conn)
    h = str(row.get("hash", "")).strip()
    if not h:
        raise ValueError("missing_hash")
    ptype = str(row.get("type") or row.get("payload_type") or "OAA_MEMORY_ENTRY_V1")
    agent = str(row.get("agent", "")).strip()
    cycle = str(row.get("cycle", "")).strip()
    key = str(row.get("key", "")).strip()
    ts = str(row.get("timestamp", "")).strip()
    if not all([agent, cycle, key, ts]):
        raise ValueError("missing_required_fields")
    intent = row.get("intent")
    if intent is not None:
        intent = str(intent)
    prev = row.get("previous_hash")
    if prev is not None and prev != "":
        prev = str(prev)
    else:
        prev = None
    raw = json.dumps(row, sort_keys=True, separators=(",", ":"))
    cur = conn.execute(
        """
        INSERT INTO oaa_memory_proofs
          (hash, payload_type, agent, cycle, key, intent, previous_hash, timestamp, source, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(hash) DO NOTHING
        """,
        (h, ptype, agent, cycle, key, intent, prev, ts, source, raw),
    )
    inserted = cur.rowcount == 1
    return inserted, h


def get_proof_by_hash(conn: sqlite3.Connection, h: str) -> Optional[Dict[str, Any]]:
    ensure_oaa_table(conn)
    cur = conn.execute(
        "SELECT * FROM oaa_memory_proofs WHERE hash = ?", (h,)
    )
    r = cur.fetchone()
    if not r:
        return None
    d = dict(r)
    try:
        d["raw"] = json.loads(d["raw"])
    except json.JSONDecodeError:
        pass
    return d


def list_proofs(
    conn: sqlite3.Connection,
    *,
    source: Optional[str] = None,
    key_prefix: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Dict[str, Any]]:
    ensure_oaa_table(conn)
    lim = max(1, min(limit, 200))
    off = max(0, offset)
    q = "SELECT hash, payload_type, agent, cycle, key, intent, previous_hash, timestamp, source, created_at FROM oaa_memory_proofs WHERE 1=1"
    args: list[Any] = []
    if source:
        q += " AND source = ?"
        args.append(source)
    if key_prefix:
        q += " AND key LIKE ?"
        args.append(f"{key_prefix}%")
    q += " ORDER BY datetime(created_at) DESC LIMIT ? OFFSET ?"
    args.extend([lim, off])
    cur = conn.execute(q, args)
    return [dict(r) for r in cur.fetchall()]
