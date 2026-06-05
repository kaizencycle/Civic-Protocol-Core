"""Render deploy webhook → Claude Code routine /fire shim (Option B).

Render posts a fixed JSON envelope; Anthropic's /fire expects {"text": "..."}.
Deploy as a small web service and point Render's deploy webhook at POST /render-deploy.
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="render-to-routine-shim", version="1.0.0")

_SUCCESS_STATUSES = frozenset(
    {
        "deploy_succeeded",
        "live",
        "succeeded",
        "success",
    }
)


def _routine_fire_url() -> str:
    trigger_id = os.environ.get("ROUTINE_TRIGGER_ID", "").strip()
    if not trigger_id:
        raise RuntimeError("ROUTINE_TRIGGER_ID is not set")
    return (
        f"https://api.anthropic.com/v1/claude_code/routines/{trigger_id}/fire"
    )


def _deploy_status(body: dict) -> str:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    for candidate in (
        data.get("status"),
        body.get("status"),
        body.get("type"),
        body.get("event"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return "unknown"


def _service_name(body: dict) -> str:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    service = data.get("service")
    if isinstance(service, dict):
        name = service.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(service, str) and service.strip():
        return service.strip()
    return "civic-protocol-core-ledger"


@app.get("/health")
def health():
    return {"ok": True, "service": "render-to-routine-shim"}


@app.post("/render-deploy")
async def render_deploy(request: Request):
    shim_secret = os.environ.get("SHIM_SECRET", "").strip()
    if shim_secret and request.headers.get("x-shim-secret") != shim_secret:
        raise HTTPException(status_code=401, detail="bad shim secret")

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    status = _deploy_status(body)
    if status not in _SUCCESS_STATUSES:
        return {"skipped": True, "status": status}

    service = _service_name(body)
    text = (
        f"Render deploy succeeded for {service} (status={status}). "
        "Run the post-deploy drift + ledger-health check now."
    )

    token = os.environ.get("ROUTINE_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=500, detail="ROUTINE_TOKEN is not set")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _routine_fire_url(),
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "experimental-cc-routine-2026-04-01",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"text": text},
        )
        response.raise_for_status()
        payload = response.json()

    return {
        "fired": True,
        "status": status,
        "fire_status_code": response.status_code,
        "session_url": payload.get("claude_code_session_url"),
    }
