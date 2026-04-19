"""
IPFS ledger bridge — content-addressed copies of mesh rows (hybrid mode).

The ledger service uses SQLite `mesh_entries`. This module adds optional
IPFS pinning: canonical JSON bytes are hashed with SHA-256; the multihash
(0x12 0x20 + digest) is base58-encoded as CIDv0, matching Kubo's CID for the
same bytes. Postgres deployments can use the same canonical payload via
`migrations/005_mesh_entries_ipfs.sql`.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import base58

_CANON_SEP = (",", ":")


def canonical_mesh_payload(row: sqlite3.Row | Dict[str, Any]) -> bytes:
    """Deterministic JSON for a mesh row (id + node + tier + time + title + sha + source + raw JSON)."""
    if isinstance(row, sqlite3.Row):
        d = dict(row)
    else:
        d = row
    raw_obj: Any
    raw_s = d.get("raw")
    if isinstance(raw_s, str):
        try:
            raw_obj = json.loads(raw_s)
        except json.JSONDecodeError:
            raw_obj = raw_s
    else:
        raw_obj = raw_s
    payload = {
        "id": d["id"],
        "node_id": d["node_id"],
        "node_tier": d["node_tier"],
        "timestamp": d["timestamp"],
        "title": d.get("title"),
        "sha": d.get("sha"),
        "source": d.get("source") or "mesh-node",
        "raw": raw_obj,
    }
    return json.dumps(payload, sort_keys=True, separators=_CANON_SEP).encode("utf-8")


def content_digest_sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def digest_to_cidv0(digest: bytes) -> str:
    if len(digest) != 32:
        raise ValueError("CIDv0 sha256 multihash requires 32-byte digest")
    multihash = b"\x12\x20" + digest
    return base58.b58encode(multihash).decode("ascii")


def cidv0_to_digest_hex(cid: str) -> str:
    decoded = base58.b58decode(cid)
    if len(decoded) < 3 or decoded[0] != 0x12 or decoded[1] != 0x20:
        raise ValueError("Not a CIDv0 sha256 multihash")
    return decoded[2:].hex()


@dataclass
class IPFSAddResult:
    cid: str
    size: int


class IPFSLedgerBridge:
    """Thin wrapper over Kubo HTTP API (ipfshttpclient)."""

    def __init__(self, ipfs_addr: Optional[str] = None):
        addr = (ipfs_addr or os.getenv("IPFS_API_ADDR", "")).strip()
        if not addr:
            addr = "/ip4/127.0.0.1/tcp/5001"
        if not addr.startswith("http"):
            addr = f"http://{addr}"
        self._addr = addr.rstrip("/")
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            import ipfshttpclient

            self._client = ipfshttpclient.connect(self._addr)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def add_canonical_bytes(self, data: bytes) -> IPFSAddResult:
        digest = content_digest_sha256(data)
        expected_cid = digest_to_cidv0(digest)
        res = self._client_lazy().add_bytes(data, pin=False)
        cid = res["Hash"]
        if cid != expected_cid:
            raise ValueError(
                f"CID mismatch: kubo returned {cid}, expected {expected_cid} for canonical bytes"
            )
        size = int(res.get("Size", len(data)))
        return IPFSAddResult(cid=cid, size=size)

    def pin_cid(self, cid: str) -> None:
        self._client_lazy().pin.add(cid)

    def cat_json(self, cid: str) -> Dict[str, Any]:
        raw = self._client_lazy().cat(cid)
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8"))
        return json.loads(raw)


def mesh_row_by_id(conn: sqlite3.Connection, entry_id: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM mesh_entries WHERE id = ?", (entry_id,))
    return cur.fetchone()


def pin_mesh_entry_sqlite(
    conn: sqlite3.Connection,
    bridge: IPFSLedgerBridge,
    entry_id: str,
    *,
    do_pin: bool = True,
) -> Optional[Tuple[str, str]]:
    """
    Pin one mesh row to IPFS; update ipfs_cid / content_addressed / pinned_at.

    Returns (entry_id, cid) or None if row missing. Raises on CID mismatch.
    """
    row = mesh_row_by_id(conn, entry_id)
    if row is None:
        return None
    data = canonical_mesh_payload(row)
    result = bridge.add_canonical_bytes(data)
    if do_pin:
        bridge.pin_cid(result.cid)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE mesh_entries SET
          ipfs_cid = ?,
          content_addressed = 1,
          pinned_at = ?,
          pin_count = COALESCE(pin_count, 0) + 1
        WHERE id = ?
        """,
        (result.cid, now, entry_id),
    )
    conn.commit()
    return entry_id, result.cid


def schedule_pin_mesh_entry(
    db_path: str,
    entry_id: str,
    ipfs_addr: Optional[str] = None,
) -> None:
    """Fire-and-forget background pin (hybrid mode)."""

    def _run() -> None:
        bridge = IPFSLedgerBridge(ipfs_addr)
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            pin_mesh_entry_sqlite(conn, bridge, entry_id)
        except Exception as exc:
            print(f"ipfs pin background error for {entry_id}: {exc}")
        finally:
            bridge.close()
            if conn is not None:
                conn.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def hybrid_ipfs_enabled() -> bool:
    return os.getenv("HYBRID_LEDGER_MODE", "").lower() in ("1", "true", "yes")


def ipfs_ingest_async_enabled() -> bool:
    return os.getenv("IPFS_PIN_ON_INGEST", "true").lower() in ("1", "true", "yes")
