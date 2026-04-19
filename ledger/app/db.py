"""SQLite connection and schema for Civic Ledger API."""

import json
import os
import sqlite3
import tempfile
from typing import Optional

from fastapi import HTTPException


def get_data_dir() -> str:
    """Writable data directory (Render /tmp, local ./data, or system temp)."""
    possible_dirs = [
        os.getenv("LEDGER_DATA_DIR"),
        "/tmp/ledger_data",
        "./data",
        tempfile.gettempdir() + "/ledger_data",
    ]

    for dir_path in possible_dirs:
        if dir_path is None:
            continue
        try:
            os.makedirs(dir_path, exist_ok=True)
            test_file = os.path.join(dir_path, "test_write")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("test")
            os.remove(test_file)
            return dir_path
        except (OSError, PermissionError):
            continue

    return tempfile.gettempdir()


DATA_DIR = get_data_dir()
LEDGER_DB_PATH = os.path.join(DATA_DIR, "ledger.db")

_FEED_PATH_CANDIDATES = [
    os.getenv("LEDGER_FEED_PATH"),
    os.path.join(os.path.dirname(__file__), "..", "feed.json"),
    os.path.join(os.getcwd(), "ledger", "feed.json"),
]


def ledger_feed_json_path() -> Optional[str]:
    for p in _FEED_PATH_CANDIDATES:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def get_db_connection() -> sqlite3.Connection:
    """Open SQLite connection and ensure core + mesh tables exist."""
    try:
        conn = sqlite3.connect(LEDGER_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                civic_id TEXT NOT NULL,
                lab_source TEXT NOT NULL,
                payload TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                signature TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS identities (
                civic_id TEXT PRIMARY KEY,
                lab_source TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                event_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS mesh_entries (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                node_tier TEXT NOT NULL DEFAULT 'observer',
                timestamp TEXT NOT NULL,
                title TEXT,
                sha TEXT,
                source TEXT NOT NULL DEFAULT 'mesh-node',
                raw TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_mesh_entries_node_id ON mesh_entries(node_id);
            CREATE INDEX IF NOT EXISTS idx_mesh_entries_timestamp ON mesh_entries(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_mesh_entries_node_tier ON mesh_entries(node_tier);
            CREATE TABLE IF NOT EXISTS epicon_entries (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                title TEXT,
                sha TEXT,
                source TEXT NOT NULL DEFAULT 'local',
                raw TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_epicon_entries_timestamp ON epicon_entries(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_epicon_entries_source ON epicon_entries(source);
            """
        )
        conn.commit()
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        raise HTTPException(500, f"Database connection failed: {str(e)}") from e


def sync_ledger_feed_json_to_epicon_entries(conn: sqlite3.Connection) -> None:
    """Mirror ledger/feed.json into epicon_entries for unified /epicon/feed."""
    path = ledger_feed_json_path()
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ledger feed sync skipped: {e}")
        return
    if not isinstance(data, list):
        return
    for entry in data:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("id")
        if not eid:
            continue
        ts = str(entry.get("timestamp") or "")
        title = entry.get("title")
        if title is not None:
            title = str(title)
        sha = entry.get("sha")
        if sha is not None:
            sha = str(sha)
        source = str(entry.get("source") or "mesh-node")
        raw = json.dumps(entry, sort_keys=True)
        conn.execute(
            """
            INSERT INTO epicon_entries (id, timestamp, title, sha, source, raw)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              timestamp = excluded.timestamp,
              title = excluded.title,
              sha = excluded.sha,
              source = excluded.source,
              raw = excluded.raw
            """,
            (str(eid), ts, title, sha, source, raw),
        )
    conn.commit()
