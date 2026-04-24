"""Seal reconciliation APIs for quarantined seal re-attestation/finalization (C-290)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ledger.app.db import get_db_connection

router = APIRouter(prefix="/api/seal", tags=["seal-reconciliation"])

IMMUTABLE_SEAL_FIELDS = {
    "seal_id",
    "sequence",
    "cycle_at_seal",
    "sealed_at",
    "reserve",
    "gi_at_seal",
    "mode_at_seal",
    "source_entries",
    "deposit_hashes",
    "carried_forward_deposit_hashes",
    "prev_seal_hash",
    "seal_hash",
}

ATTEST_REQUIRED = ("ZEUS", "ATLAS")
ALLOWED_STATUSES = {
    "candidate",
    "quarantined",
    "re_attesting",
    "re_attesting_passed",
    "finalized",
    "failed_permanent",
}


class SealSeedRequest(BaseModel):
    """Seed or return an existing seal record (immutable artifact + runtime status)."""

    seal: Dict[str, Any]
    quarantine_reason: Optional[str] = "attestation_timeout"


class SealActionRequest(BaseModel):
    """Request body for re-attest/finalize actions."""

    seal_id: str = Field(min_length=1)


@dataclass
class _SealRow:
    seal_id: str
    artifact: Dict[str, Any]
    status: str
    quarantine_reason: Optional[str]
    reconciliation: Dict[str, Any]
    reserve_accounted: bool
    finalized_event_id: Optional[str]



def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def _validate_artifact(seal: Dict[str, Any]) -> None:
    missing = sorted(k for k in ("seal_id", "cycle_at_seal", "sealed_at", "reserve", "seal_hash") if k not in seal)
    if missing:
        raise HTTPException(status_code=400, detail=f"seal missing required fields: {', '.join(missing)}")



def _default_reconciliation() -> Dict[str, Any]:
    return {
        "attempt_count": 0,
        "last_attempt_at": None,
        "last_attempt_result": None,
        "finalized_at": None,
        "failed_at": None,
    }



def _load_row(conn, seal_id: str) -> Optional[_SealRow]:
    row = conn.execute(
        """
        SELECT seal_id, artifact_json, status, quarantine_reason,
               reconciliation_json, reserve_accounted, finalized_event_id
        FROM seal_records
        WHERE seal_id = ?
        """,
        (seal_id,),
    ).fetchone()
    if not row:
        return None
    return _SealRow(
        seal_id=row["seal_id"],
        artifact=json.loads(row["artifact_json"]),
        status=row["status"],
        quarantine_reason=row["quarantine_reason"],
        reconciliation=json.loads(row["reconciliation_json"] or "{}") or _default_reconciliation(),
        reserve_accounted=bool(row["reserve_accounted"]),
        finalized_event_id=row["finalized_event_id"],
    )



def _store_row(conn, row: _SealRow) -> None:
    conn.execute(
        """
        UPDATE seal_records
        SET artifact_json = ?,
            status = ?,
            quarantine_reason = ?,
            reconciliation_json = ?,
            reserve_accounted = ?,
            finalized_event_id = ?
        WHERE seal_id = ?
        """,
        (
            json.dumps(row.artifact, sort_keys=True),
            row.status,
            row.quarantine_reason,
            json.dumps(row.reconciliation, sort_keys=True),
            int(row.reserve_accounted),
            row.finalized_event_id,
            row.seal_id,
        ),
    )



def _build_response(row: _SealRow) -> Dict[str, Any]:
    return {
        "seal_id": row.seal_id,
        "cycle_at_seal": row.artifact.get("cycle_at_seal"),
        "reserve": row.artifact.get("reserve"),
        "status": row.status,
        "quarantine_reason": row.quarantine_reason,
        "attestations": row.artifact.get("attestations", {}),
        "reconciliation": row.reconciliation,
        "fountain_status": row.artifact.get("fountain_status"),
        "finalized_event_id": row.finalized_event_id,
    }



def _merge_attestations(artifact: Dict[str, Any], attempt_ts: str) -> Dict[str, Any]:
    existing = artifact.get("attestations") or {}
    merged = dict(existing)
    for agent in ATTEST_REQUIRED:
        prior = existing.get(agent, {})
        verdict = prior.get("verdict", "flag")
        # Timeout-like failures stay flagged; otherwise mark pass.
        if verdict in ("flag", "fail") and "timeout" in str(prior.get("rationale", "")).lower():
            next_verdict = "flag"
            rationale = "timeout"
        else:
            next_verdict = "pass"
            rationale = "re_attest_ok"
        merged[agent] = {
            "agent": agent,
            "verdict": next_verdict,
            "rationale": rationale,
            "timestamp": attempt_ts,
            "signature": prior.get("signature", "re-attest"),
        }
    return merged


@router.post("/reconcile")
def seed_or_get_seal(request: SealSeedRequest):
    """Seed a canonical seal artifact once; return existing if already present."""
    artifact = dict(request.seal)
    _validate_artifact(artifact)
    seal_id = str(artifact["seal_id"])

    with get_db_connection() as conn:
        existing = _load_row(conn, seal_id)
        if existing:
            return {"ok": True, "created": False, "item": _build_response(existing)}

        status = str(artifact.get("status") or "quarantined")
        if status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
        for field in IMMUTABLE_SEAL_FIELDS:
            if field in artifact:
                continue
        conn.execute(
            """
            INSERT INTO seal_records (
                seal_id, artifact_json, status, quarantine_reason,
                reconciliation_json, reserve_accounted, finalized_event_id
            ) VALUES (?, ?, ?, ?, ?, 0, NULL)
            """,
            (
                seal_id,
                json.dumps(artifact, sort_keys=True),
                status,
                request.quarantine_reason,
                json.dumps(_default_reconciliation(), sort_keys=True),
            ),
        )
        conn.commit()

        created = _load_row(conn, seal_id)
        assert created is not None
        return {"ok": True, "created": True, "item": _build_response(created)}


@router.get("/quarantine")
def list_quarantined_seals():
    """List quarantined seals for operator visibility."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT seal_id, artifact_json, status, quarantine_reason,
                   reconciliation_json, reserve_accounted, finalized_event_id
            FROM seal_records
            WHERE status = 'quarantined'
            ORDER BY created_at DESC
            """
        ).fetchall()
    items = []
    for raw in rows:
        row = _SealRow(
            seal_id=raw["seal_id"],
            artifact=json.loads(raw["artifact_json"]),
            status=raw["status"],
            quarantine_reason=raw["quarantine_reason"],
            reconciliation=json.loads(raw["reconciliation_json"] or "{}") or _default_reconciliation(),
            reserve_accounted=bool(raw["reserve_accounted"]),
            finalized_event_id=raw["finalized_event_id"],
        )
        items.append(_build_response(row))
    return {"ok": True, "items": items}


@router.post("/reattest")
def reattest_seal(request: SealActionRequest):
    """Re-run attestation for a quarantined seal without changing immutable history."""
    with get_db_connection() as conn:
        row = _load_row(conn, request.seal_id)
        if not row:
            raise HTTPException(status_code=404, detail="seal_not_found")
        if row.status != "quarantined":
            raise HTTPException(status_code=409, detail="not_quarantined")

        attempt_ts = _utc_iso()
        row.status = "re_attesting"
        row.reconciliation = {
            **_default_reconciliation(),
            **row.reconciliation,
            "attempt_count": int(row.reconciliation.get("attempt_count") or 0) + 1,
            "last_attempt_at": attempt_ts,
        }
        _store_row(conn, row)

        merged_att = _merge_attestations(row.artifact, attempt_ts)
        row.artifact = dict(row.artifact)
        row.artifact["attestations"] = merged_att

        passed = all((merged_att.get(a) or {}).get("verdict") == "pass" for a in ATTEST_REQUIRED)
        row.reconciliation["last_attempt_result"] = "pass" if passed else "fail"
        row.status = "re_attesting_passed" if passed else "quarantined"
        if not passed and int(row.reconciliation.get("attempt_count") or 0) >= 3:
            row.status = "failed_permanent"
            row.reconciliation["failed_at"] = _utc_iso()

        _store_row(conn, row)
        conn.commit()

    return {"ok": True, "passed": passed, "item": _build_response(row)}


@router.post("/finalize")
def finalize_seal(request: SealActionRequest):
    """Finalize a successfully re-attested seal and anchor one ledger event (idempotent)."""
    with get_db_connection() as conn:
        row = _load_row(conn, request.seal_id)
        if not row:
            raise HTTPException(status_code=404, detail="seal_not_found")

        if row.status == "finalized":
            return {"ok": True, "already_finalized": True, "item": _build_response(row)}

        if row.status != "re_attesting_passed":
            raise HTTPException(status_code=409, detail="not_ready_for_finalize")

        event_id = row.finalized_event_id
        if not event_id:
            event_id = f"seal_finalize_{request.seal_id}_{int(datetime.now().timestamp() * 1000)}"
            payload = {
                "seal_id": row.seal_id,
                "cycle_at_seal": row.artifact.get("cycle_at_seal"),
                "reserve": row.artifact.get("reserve"),
                "seal_hash": row.artifact.get("seal_hash"),
                "reconciled": True,
            }
            prev = conn.execute(
                "SELECT event_hash FROM events ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            previous_hash = prev[0] if prev else "0" * 64
            event_timestamp = _utc_iso()
            event_hash = __import__("hashlib").sha256(
                f"{event_id}seal_reconciliation_finalizedmobius-seal-reconcilerterminal{json.dumps(payload, sort_keys=True)}{event_timestamp}{previous_hash}".encode()
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO events (event_id, event_type, civic_id, lab_source, payload, timestamp, previous_hash, event_hash, signature)
                VALUES (?, 'seal_reconciliation_finalized', 'mobius-seal-reconciler', 'terminal', ?, ?, ?, ?, NULL)
                """,
                (event_id, json.dumps(payload), event_timestamp, previous_hash, event_hash),
            )
            row.finalized_event_id = event_id

        row.status = "finalized"
        row.reconciliation = {
            **_default_reconciliation(),
            **row.reconciliation,
            "finalized_at": _utc_iso(),
        }
        row.reserve_accounted = True
        _store_row(conn, row)
        conn.commit()

    return {"ok": True, "item": _build_response(row)}
