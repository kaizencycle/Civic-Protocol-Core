"""Render-to-routine shim.

Render's deploy webhook sends a fixed JSON envelope that cannot be reshaped
before delivery. The Claude Code routine /fire endpoint expects {"text": "..."}.
This service bridges the two: it receives Render's webhook, extracts status,
and forwards a text-shaped payload to /fire — but only on a successful deploy.

Required env vars:
  ROUTINE_TRIGGER_ID  — from the API trigger on the Claude Code routine
  ROUTINE_TOKEN       — bearer token shown once at trigger creation

Optional env vars:
  SHIM_SECRET         — if set, callers must send it as x-shim-secret header
  PORT                — Render sets this automatically
"""
from __future__ import annotations

import os
import httpx
from fastapi import FastAPI, Request, HTTPException

app = FastAPI(title="render-to-routine-shim")

_ROUTINE_TRIGGER_ID = os.environ.get("ROUTINE_TRIGGER_ID", "")
_ROUTINE_TOKEN = os.environ.get("ROUTINE_TOKEN", "")
_SHIM_SECRET = os.environ.get("SHIM_SECRET", "")

ROUTINE_URL = (
    f"https://api.anthropic.com/v1/claude_code/routines/{_ROUTINE_TRIGGER_ID}/fire"
)

# Render deploy webhook statuses that mean the deploy actually went live.
_SUCCESS_STATUSES = frozenset({"deploy_succeeded", "live", "succeeded"})


@app.get("/health")
def health() -> dict:
    configured = bool(_ROUTINE_TRIGGER_ID and _ROUTINE_TOKEN)
    return {"ok": True, "routine_configured": configured}


@app.post("/render-deploy")
async def render_deploy(request: Request) -> dict:
    if _SHIM_SECRET and request.headers.get("x-shim-secret") != _SHIM_SECRET:
        raise HTTPException(status_code=401, detail="bad shim secret")

    if not _ROUTINE_TRIGGER_ID or not _ROUTINE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="ROUTINE_TRIGGER_ID or ROUTINE_TOKEN not configured",
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    # Render deploy webhook envelope:
    # {"type": "deploy", "data": {"service": {"name": "..."}, "status": "..."}}
    data = (body or {}).get("data", {})
    status = data.get("status") or body.get("type") or "unknown"
    service = (data.get("service") or {}).get("name", "civic-protocol-core-ledger")

    if status not in _SUCCESS_STATUSES:
        return {"skipped": True, "reason": "not a successful deploy", "status": status}

    text = (
        f"Render deploy succeeded for {service} (status={status}). "
        f"Run the post-deploy drift + ledger-health check now."
    )

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            ROUTINE_URL,
            headers={
                "Authorization": f"Bearer {_ROUTINE_TOKEN}",
                "anthropic-beta": "experimental-cc-routine-2026-04-01",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"text": text},
        )

    return {"fired": True, "status": status, "fire_status_code": r.status_code}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
