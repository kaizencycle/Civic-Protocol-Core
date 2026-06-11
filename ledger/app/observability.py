"""Operational logging and HTTP middleware for the ledger service."""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class _JsonFormatter(logging.Formatter):
    """Small JSON formatter for service logs without adding a dependency."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def configure_logging() -> None:
    """Configure JSON logs once, with level controlled by LOG_LEVEL."""

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        for handler in root.handlers:
            handler.setLevel(level)
            handler.setFormatter(_JsonFormatter())
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Echo or create a request ID so writes can be correlated across services."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline hardening headers to every ledger response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


def parse_allowed_origins() -> list[str]:
    """Read an explicit CORS allowlist; wildcard CORS stays disabled by default."""

    raw = (
        os.getenv("LEDGER_CORS_ALLOW_ORIGINS", "").strip()
        or os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    )
    if not raw:
        return []
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins and os.getenv("LEDGER_ALLOW_WILDCARD_CORS", "").lower() not in (
        "1",
        "true",
        "yes",
    ):
        logging.getLogger(__name__).warning(
            "Ignoring wildcard CORS origin; set LEDGER_ALLOW_WILDCARD_CORS=true to opt in"
        )
        return [origin for origin in origins if origin != "*"]
    return origins


def install_operational_middleware(app: FastAPI) -> None:
    """Install shared security, request tracing, and optional CORS middleware."""

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    allowed_origins = parse_allowed_origins()
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-MNS-Node", "X-Request-ID"],
        )
