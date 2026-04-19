"""GI gate and MCP invocation logging for civic-protocol-core MCP bridge."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ledger.app.db import get_db_connection


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_gi_state() -> Optional[Dict[str, Any]]:
    """Load optional GI snapshot from env JSON, file path, or data dir file."""
    raw = os.getenv("GI_STATE_JSON", "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    path = (
        os.getenv("GI_STATE_PATH", "").strip()
        or os.path.join(
            os.getenv("LEDGER_DATA_DIR", "/tmp/ledger_data"), "gi_state.json"
        )
    )
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    return None


@dataclass
class IntegrityGateResult:
    allowed: bool
    gi: Optional[float]
    reason: Optional[str] = None


def check_integrity_gate(min_gi: float = 0.0) -> IntegrityGateResult:
    """Enforce minimum Global Integrity when GI is known; never blocks on unknown GI."""
    if min_gi <= 0.0:
        return IntegrityGateResult(allowed=True, gi=None)

    state = load_gi_state()
    if not state:
        return IntegrityGateResult(
            allowed=True, gi=None, reason="gi_unknown_allowing"
        )

    gi_val = state.get("global_integrity")
    if gi_val is None:
        return IntegrityGateResult(
            allowed=True, gi=None, reason="gi_unknown_allowing"
        )

    try:
        gi = float(gi_val)
    except (TypeError, ValueError):
        return IntegrityGateResult(
            allowed=True, gi=None, reason="gi_unknown_allowing"
        )

    if gi < min_gi:
        return IntegrityGateResult(
            allowed=False,
            gi=gi,
            reason=f"gi_{gi}_below_threshold_{min_gi}",
        )
    return IntegrityGateResult(allowed=True, gi=gi)


def log_mcp_invocation(
    tool: str,
    args: Dict[str, Any],
    result_ok: bool,
    gi: Optional[float],
    cycle: str,
) -> None:
    """Persist MCP tool invocation as an EPICON row when integrity.logging is on."""
    entry = {
        "id": f"EPICON-MCP-{hashlib.sha256(f'{tool}:{_utc_iso()}'.encode()).hexdigest()[:8]}",
        "timestamp": _utc_iso(),
        "type": "mcp-invocation",
        "agentOrigin": "HERMES",
        "title": f"MCP tool call: {tool}",
        "tags": [
            "mcp",
            f"tool:{tool}",
            f"gi:{gi if gi is not None else 'unknown'}",
            "result:ok" if result_ok else "result:error",
        ],
        "cycleId": cycle,
        "source": "mcp-bridge",
        "args": args,
        "integrityDelta": 0,
        "status": "committed",
    }
    raw = json.dumps(entry, sort_keys=True)
    try:
        with get_db_connection() as conn:
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
                (
                    entry["id"],
                    entry["timestamp"],
                    entry["title"],
                    "",
                    "mcp-bridge",
                    raw,
                ),
            )
            conn.commit()
    except Exception as exc:
        print(f"mcp invocation log error: {exc}")
