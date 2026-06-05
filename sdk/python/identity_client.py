#!/usr/bin/env python3
"""
Mobius Identity token client (OPT-6).

Mint and cache short-lived JWTs via POST /auth/login instead of storing a
static bearer token in env. Intended for machine callers (Terminal cron,
workers) using a dedicated service account — not a founder identity.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


def _jwt_exp_unix(token: str) -> int | None:
    """Decode JWT exp claim without signature verification (cache scheduling only)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(decoded)
        exp = data.get("exp")
        return int(exp) if exp is not None else None
    except (ValueError, json.JSONDecodeError, TypeError):
        return None


@dataclass
class IdentityLoginResult:
    access_token: str
    token_type: str
    user: dict[str, Any]


class IdentityTokenClient:
    """Login-backed JWT cache with proactive refresh before expiry."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        *,
        refresh_margin_seconds: int = 86_400,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.refresh_margin_seconds = refresh_margin_seconds
        self.timeout_seconds = timeout_seconds
        self._token: str | None = None
        self._expires_at: int | None = None

    @classmethod
    def from_env(cls, prefix: str = "IDENTITY_SERVICE") -> IdentityTokenClient:
        """Build client from IDENTITY_API_BASE + IDENTITY_SERVICE_EMAIL/PASSWORD."""
        base = (
            os.getenv("IDENTITY_API_BASE", "").strip()
            or os.getenv("IDENTITY_SERVICE_URL", "").strip()
        )
        email = os.getenv(f"{prefix}_EMAIL", "").strip()
        password = os.getenv(f"{prefix}_PASSWORD", "").strip()
        if not base or not email or not password:
            missing = []
            if not base:
                missing.append("IDENTITY_API_BASE")
            if not email:
                missing.append(f"{prefix}_EMAIL")
            if not password:
                missing.append(f"{prefix}_PASSWORD")
            raise ValueError(f"Missing env for IdentityTokenClient: {', '.join(missing)}")
        margin = int(os.getenv("IDENTITY_TOKEN_REFRESH_MARGIN_SECONDS", "86400"))
        return cls(base, email, password, refresh_margin_seconds=margin)

    def login(self) -> IdentityLoginResult:
        """POST /auth/login and cache the access token."""
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/auth/login",
                json={"email": self.email, "password": self.password},
            )
            response.raise_for_status()
            data = response.json()

        token = data["access_token"]
        self._token = token
        self._expires_at = _jwt_exp_unix(token)
        return IdentityLoginResult(
            access_token=token,
            token_type=data.get("token_type", "bearer"),
            user=data.get("user", {}),
        )

    def _needs_refresh(self) -> bool:
        if not self._token:
            return True
        if self._expires_at is None:
            return True
        return time.time() >= (self._expires_at - self.refresh_margin_seconds)

    def get_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid JWT, refreshing via login when near expiry."""
        if force_refresh or self._needs_refresh():
            return self.login().access_token
        assert self._token is not None
        return self._token

    def get_authorization_header(self, *, force_refresh: bool = False) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token(force_refresh=force_refresh)}"}

    def introspect(self, token: str | None = None) -> dict[str, Any]:
        """GET /auth/introspect for the given or cached token."""
        bearer = token or self.get_token()
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(
                f"{self.base_url}/auth/introspect",
                headers={"Authorization": f"Bearer {bearer}"},
            )
            response.raise_for_status()
            return response.json()

    def attest(
        self,
        ledger_url: str,
        *,
        event_type: str,
        civic_id: str,
        payload: dict[str, Any],
        lab_source: str = "terminal",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """POST /ledger/attest with a fresh Identity JWT."""
        headers = {
            **self.get_authorization_header(force_refresh=force_refresh),
            "Content-Type": "application/json",
        }
        body = {
            "event_type": event_type,
            "civic_id": civic_id,
            "lab_source": lab_source,
            "payload": payload,
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{ledger_url.rstrip('/')}/ledger/attest",
                headers=headers,
                json=body,
            )
            if response.status_code == 401 and not force_refresh:
                return self.attest(
                    ledger_url,
                    event_type=event_type,
                    civic_id=civic_id,
                    payload=payload,
                    lab_source=lab_source,
                    force_refresh=True,
                )
            response.raise_for_status()
            return response.json()
