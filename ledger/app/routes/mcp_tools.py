"""MCP server (streamable HTTP) mounted at /api/mcp for civic-protocol-core."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi_mcp_router import MCPRouter
from fastapi_mcp_router.types import ServerInfo

from ledger.app.db import get_db_connection, sync_ledger_feed_json_to_epicon_entries
from ledger.app.mcp_integrity import (
    check_integrity_gate,
    load_gi_state,
    log_mcp_invocation,
)

async def _public_mcp_auth(api_key: str | None, bearer_token: str | None) -> bool:
    """Allow public MCP tools; GI / write gates are enforced inside tools."""
    return True


_mcp_server_info: ServerInfo = {
    "name": "civic-protocol-core",
    "version": "1.0.0",
    "title": "Civic Ledger MCP",
    "description": (
        "Mobius Civic Ledger — integrity-governed MCP bridge (streamable HTTP). "
        "Constitutional substrate: kaizencycle/Mobius-Substrate"
    ),
}

mcp = MCPRouter(auth_validator=_public_mcp_auth, server_info=_mcp_server_info)

_DEFAULT_CYCLE = os.getenv("MOBIUS_CURRENT_CYCLE", "C-unknown")
_NODE_ID = "civic-protocol-core"


def _cycle() -> str:
    return os.getenv("CURRENT_CYCLE", _DEFAULT_CYCLE)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mcp_log_enabled() -> bool:
    return os.getenv("MCP_LOG_INVOCATIONS", "true").lower() in ("1", "true", "yes")


def _maybe_log(
    tool: str,
    args: Dict[str, Any],
    ok: bool,
    gi: Optional[float],
) -> None:
    if _mcp_log_enabled():
        log_mcp_invocation(tool, args, ok, gi, _cycle())


def _new_mcp_entry_id(title: str) -> str:
    digest = hashlib.sha256(f"{title}:{_utc_iso()}".encode()).hexdigest()
    return f"EPICON-MCP-{digest[:8]}"


@mcp.tool(
    name="get_integrity_snapshot",
    description=(
        "Returns Global Integrity snapshot when GI_STATE_JSON / gi_state.json is "
        "configured, plus civic ledger chain stats (event count, latest hash)."
    ),
    annotations={"readOnlyHint": True},
)
async def get_integrity_snapshot() -> str:
    gate = check_integrity_gate(0.0)
    gi_state = load_gi_state() or {}
    snapshot: Dict[str, Any] = {
        "ok": True,
        "node_id": _NODE_ID,
        "gi": gi_state.get("global_integrity"),
        "mode": gi_state.get("mode"),
        "cycle": _cycle(),
        "terminal_status": gi_state.get("terminal_status"),
        "signals": gi_state.get("signals"),
        "source": gi_state.get("source"),
        "timestamp": gi_state.get("timestamp"),
        "ledger": {},
    }
    try:
        with get_db_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM events")
            total = cur.fetchone()[0]
            cur = conn.execute(
                "SELECT event_hash FROM events ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
        snapshot["ledger"] = {
            "total_events": total,
            "latest_event_hash": row[0] if row else None,
        }
    except Exception as e:
        snapshot["ledger"] = {"error": str(e)}

    _maybe_log("get_integrity_snapshot", {}, True, gate.gi)
    return json.dumps(snapshot, indent=2)


@mcp.tool(
    name="get_epicon_feed",
    description=(
        "Returns recent EPICON entries from this node (ledger/feed.json mirror "
        "plus ingested mesh rows)."
    ),
    annotations={"readOnlyHint": True},
)
async def get_epicon_feed(limit: int = 10) -> str:
    gate = check_integrity_gate(0.0)
    lim = max(1, min(int(limit), 50))
    with get_db_connection() as conn:
        sync_ledger_feed_json_to_epicon_entries(conn)
        cur = conn.execute(
            """
            SELECT id, node_id, node_tier, timestamp, title, sha, source, raw FROM (
                SELECT
                    id, ? AS node_id, 'contributor' AS node_tier,
                    timestamp, title, sha, source, raw
                FROM epicon_entries
                UNION ALL
                SELECT id, node_id, node_tier, timestamp, title, sha, source, raw
                FROM mesh_entries
            ) combined
            ORDER BY datetime(timestamp) DESC
            LIMIT ?
            """,
            (_NODE_ID, lim),
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
        entries.append({**base, **raw_obj})

    _maybe_log("get_epicon_feed", {"limit": lim}, True, gate.gi)
    return json.dumps({"ok": True, "count": len(entries), "entries": entries}, indent=2)


@mcp.tool(
    name="get_vault_status",
    description=(
        "Returns MIC vault metadata when VAULT_META_JSON is set; otherwise a "
        "typed placeholder for this ledger-only node."
    ),
    annotations={"readOnlyHint": True},
)
async def get_vault_status() -> str:
    gate = check_integrity_gate(0.0)
    raw = os.getenv("VAULT_META_JSON", "").strip()
    if raw:
        try:
            vault = json.loads(raw)
            vault.setdefault("ok", True)
        except json.JSONDecodeError:
            vault = {"ok": False, "error": "invalid_VAULT_META_JSON"}
    else:
        vault = {
            "ok": True,
            "in_progress_balance": 0,
            "sealed_reserve_total": 0,
            "tranche_target": 50,
            "seals_count": 0,
            "fountain_status": "locked",
            "cycle": _cycle(),
            "note": (
                "Vault live data is not colocated on civic-protocol-core; "
                "set VAULT_META_JSON."
            ),
        }
    _maybe_log("get_vault_status", {}, True, gate.gi)
    return json.dumps(vault, indent=2)


@mcp.tool(
    name="get_agent_journal",
    description=(
        "Returns recent EPICON entries likely from agent activity (mcp-bridge "
        "or mesh-node sources), newest first."
    ),
    annotations={"readOnlyHint": True},
)
async def get_agent_journal(limit: int = 10) -> str:
    gate = check_integrity_gate(0.0)
    lim = max(1, min(int(limit), 50))
    with get_db_connection() as conn:
        sync_ledger_feed_json_to_epicon_entries(conn)
        cur = conn.execute(
            """
            SELECT id, timestamp, title, sha, source, raw
            FROM epicon_entries
            WHERE source IN ('mcp-bridge', 'mesh-node')
            ORDER BY datetime(timestamp) DESC
            LIMIT ?
            """,
            (lim,),
        )
        rows = cur.fetchall()
    items = []
    for row in rows:
        raw_obj: Dict[str, Any] = {}
        if row["raw"]:
            try:
                raw_obj = json.loads(row["raw"])
            except json.JSONDecodeError:
                raw_obj = {}
        items.append(
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "title": row["title"],
                "sha": row["sha"],
                "source": row["source"],
                **raw_obj,
            }
        )
    _maybe_log("get_agent_journal", {"limit": lim}, True, gate.gi)
    return json.dumps({"ok": True, "count": len(items), "entries": items}, indent=2)


@mcp.tool(
    name="post_epicon_entry",
    description=(
        "Submit an EPICON-style intent entry to this node's civic ledger. "
        "Requires GI > 0.6 when GI is known. Optional bearer via AGENT_SERVICE_TOKEN."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 5, "maxLength": 200},
            "category": {
                "type": "string",
                "enum": [
                    "governance",
                    "infrastructure",
                    "market",
                    "civic-risk",
                    "agent-action",
                ],
            },
            "rationale": {"type": "string", "minLength": 10, "maxLength": 1000},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "authorization": {
                "type": "string",
                "description": "Bearer token when AGENT_SERVICE_TOKEN is configured",
            },
        },
        "required": ["title", "category", "rationale", "confidence"],
    },
)
async def post_epicon_entry(
    title: str,
    category: str,
    rationale: str,
    confidence: float,
    authorization: Optional[str] = None,
) -> str:
    expected = os.getenv("AGENT_SERVICE_TOKEN", "").strip()
    if expected:
        if not authorization or not authorization.startswith("Bearer "):
            _maybe_log("post_epicon_entry", {"title": title}, False, None)
            return json.dumps(
                {
                    "ok": False,
                    "error": "unauthorized",
                    "message": "Bearer AGENT_SERVICE_TOKEN required for writes.",
                }
            )
        token = authorization[7:].strip()
        if token != expected:
            _maybe_log("post_epicon_entry", {"title": title}, False, None)
            return json.dumps({"ok": False, "error": "unauthorized"})

    gate = check_integrity_gate(0.6)
    if not gate.allowed:
        _maybe_log(
            "post_epicon_entry",
            {"title": title, "category": category},
            False,
            gate.gi,
        )
        return json.dumps(
            {
                "ok": False,
                "error": "gi_gate_blocked",
                "gi": gate.gi,
                "reason": gate.reason,
                "message": (
                    f"GI {gate.gi} is below the 0.6 threshold required for ledger writes."
                ),
            }
        )

    entry_id = _new_mcp_entry_id(title)
    ts = _utc_iso()
    entry = {
        "id": entry_id,
        "timestamp": ts,
        "type": "agent-action",
        "agentOrigin": "MCP-BRIDGE",
        "title": title,
        "category": category,
        "rationale": rationale,
        "confidence": confidence,
        "tags": ["mcp", "agent-action", f"category:{category}"],
        "cycleId": _cycle(),
        "source": "mcp-bridge",
        "integrityDelta": 0,
        "status": "pending",
        "_mcp": True,
    }

    raw = json.dumps(entry, sort_keys=True)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO epicon_entries (id, timestamp, title, sha, source, raw)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_id, ts, title, "", "mcp-bridge", raw),
        )
        conn.commit()

    _maybe_log(
        "post_epicon_entry",
        {"title": title, "category": category, "confidence": confidence},
        True,
        gate.gi,
    )
    return json.dumps(
        {
            "ok": True,
            "entry_id": entry_id,
            "status": "pending_zeus_verification",
            "message": "Entry submitted. ZEUS will verify the intent chain.",
        }
    )


@mcp.tool(
    name="get_mic_readiness",
    description=(
        "Returns MIC readiness JSON when MIC_READINESS_JSON env is set; "
        "otherwise reports that no snapshot is available on this service."
    ),
    annotations={"readOnlyHint": True},
)
async def get_mic_readiness() -> str:
    gate = check_integrity_gate(0.0)
    raw = os.getenv("MIC_READINESS_JSON", "").strip()
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"ok": False, "error": "invalid_MIC_READINESS_JSON"}
    else:
        body = {"ok": False, "error": "no_snapshot"}
    _maybe_log("get_mic_readiness", {}, bool(raw), gate.gi)
    return json.dumps(body, indent=2)
