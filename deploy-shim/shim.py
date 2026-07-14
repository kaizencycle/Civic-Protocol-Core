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
  GITHUB_DISPATCH_TOKEN — PAT with repo scope; dispatches cpc-deploy-live after ledger deploy
  GITHUB_DISPATCH_REPO  — default kaizencycle/Civic-Protocol-Core
  PORT                — Render sets this automatically
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="render-to-routine-shim")

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


def _is_ledger_service(service: str) -> bool:
    lowered = service.lower()
    return "civic-ledger" in lowered or "civic-protocol-core-ledger" in lowered


async def _maybe_dispatch_drift_gate(service: str) -> dict:
    """Optional: trigger cpc-post-deploy-drift-gate after Render deploy succeeds."""
    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_DISPATCH_REPO", "kaizencycle/Civic-Protocol-Core").strip()
    if not token or not _is_ledger_service(service):
        return {"skipped": True, "reason": "token missing or non-ledger service"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"https://api.github.com/repos/{repo}/dispatches",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "event_type": "cpc-deploy-live",
                "client_payload": {"service": service},
            },
        )
        response.raise_for_status()
        return {"dispatched": True, "repo": repo}


@app.get("/health")
def health() -> dict:
    configured = bool(
        os.environ.get("ROUTINE_TRIGGER_ID", "").strip()
        and os.environ.get("ROUTINE_TOKEN", "").strip()
    )
    return {"ok": True, "service": "render-to-routine-shim", "routine_configured": configured}


@app.post("/render-deploy")
async def render_deploy(request: Request) -> dict:
    shim_secret = os.environ.get("SHIM_SECRET", "").strip()
    if shim_secret and request.headers.get("x-shim-secret") != shim_secret:
        raise HTTPException(status_code=401, detail="bad shim secret")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body") from None
    if not isinstance(body, dict):
        body = {}

    status = _deploy_status(body)
    if status not in _SUCCESS_STATUSES:
        return {"skipped": True, "status": status}

    token = os.environ.get("ROUTINE_TOKEN", "").strip()
    if not os.environ.get("ROUTINE_TRIGGER_ID", "").strip() or not token:
        raise HTTPException(
            status_code=503,
            detail="ROUTINE_TRIGGER_ID or ROUTINE_TOKEN not configured",
        )

    service = _service_name(body)
    text = (
        f"Render deploy succeeded for {service} (status={status}). "
        "Run the post-deploy drift + ledger-health check now."
    )

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

    dispatch_result = await _maybe_dispatch_drift_gate(service)

    return {
        "fired": True,
        "status": status,
        "fire_status_code": response.status_code,
        "session_url": payload.get("claude_code_session_url"),
        "drift_gate_dispatch": dispatch_result,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
