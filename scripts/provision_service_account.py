#!/usr/bin/env python3
"""
Provision a Mobius Identity service account and smoke-test ledger attestation.

This creates a robot identity for Terminal→CPC attest — NOT a founder wallet.
Credentials belong in a secret manager; JWTs are minted at runtime via login.

Usage:
  # Create account (one-time)
  python scripts/provision_service_account.py signup \\
    --email terminal-service@mobius.systems \\
    --password "$IDENTITY_SERVICE_PASSWORD" \\
    --name "Mobius Civic AI Terminal"

  # Smoke test: login → introspect → attest
  python scripts/provision_service_account.py smoke \\
    --email terminal-service@mobius.systems \\
    --password "$IDENTITY_SERVICE_PASSWORD"

Environment (smoke/signup may omit --email/--password when set):
  IDENTITY_SERVICE_EMAIL
  IDENTITY_SERVICE_PASSWORD
  IDENTITY_API_BASE   https://mobius-identity-service.onrender.com
  CIVIC_LEDGER_URL    https://civic-protocol-core-ledger.onrender.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

DEFAULT_IDENTITY = "https://mobius-identity-service.onrender.com"
DEFAULT_LEDGER = "https://civic-protocol-core-ledger.onrender.com"


def _base_url(arg: str | None) -> str:
    return (arg or os.getenv("IDENTITY_API_BASE") or DEFAULT_IDENTITY).rstrip("/")


def _ledger_url(arg: str | None) -> str:
    return (arg or os.getenv("CIVIC_LEDGER_URL") or DEFAULT_LEDGER).rstrip("/")


def _resolve_credential(value: str | None, env_key: str, flag_name: str) -> str:
    """Resolve CLI flag or environment variable for service account credentials."""
    resolved = (value or os.getenv(env_key) or "").strip()
    if not resolved:
        raise SystemExit(f"Missing --{flag_name} or {env_key}")
    return resolved


def cmd_signup(args: argparse.Namespace) -> int:
    email = _resolve_credential(args.email, "IDENTITY_SERVICE_EMAIL", "email").lower()
    password = _resolve_credential(args.password, "IDENTITY_SERVICE_PASSWORD", "password")
    base = _base_url(args.identity_base)
    payload = {
        "email": email,
        "password": password,
        "name": args.name,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{base}/auth/signup", json=payload)

    if response.status_code == 400 and "already registered" in response.text.lower():
        print("Account already exists — run smoke with login instead.", file=sys.stderr)
        return 2
    response.raise_for_status()
    data = response.json()
    user = data.get("user", {})
    print(json.dumps({
        "status": "created",
        "email": user.get("email"),
        "civic_id": user.get("civic_id"),
        "user_id": user.get("id"),
        "next_steps": [
            f"Store IDENTITY_SERVICE_EMAIL={email} in secret manager",
            "Store IDENTITY_SERVICE_PASSWORD in secret manager (never commit)",
            "Wire Terminal OPT-6 client (sdk/js/identityClient.js)",
            "Run: python scripts/provision_service_account.py smoke",
        ],
    }, indent=2))
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from sdk.python.identity_client import IdentityTokenClient  # noqa: E402

    email = _resolve_credential(args.email, "IDENTITY_SERVICE_EMAIL", "email").lower()
    password = _resolve_credential(args.password, "IDENTITY_SERVICE_PASSWORD", "password")
    base = _base_url(args.identity_base)
    ledger = _ledger_url(args.ledger_url)
    client = IdentityTokenClient(base, email, password)

    print(f"1. Login → {base}/auth/login")
    login = client.login()
    print(f"   civic_id={login.user.get('civic_id')} token_len={len(login.access_token)}")

    print(f"2. Introspect → {base}/auth/introspect")
    intro = client.introspect()
    print(f"   active={intro.get('active')} email={intro.get('email')}")

    civic_id = args.civic_id or "mobius-civic-ai-terminal"
    print(f"3. Attest → {ledger}/ledger/attest (civic_id={civic_id})")
    result = client.attest(
        ledger,
        event_type="seal.immortalize",
        civic_id=civic_id,
        payload={"seal_id": "smoke-opt6-provision", "source": "provision_service_account"},
    )
    print(json.dumps({
        "status": "ok",
        "event_id": result.get("event_id"),
        "event_hash": result.get("event_hash"),
        "confirmed": result.get("confirmed"),
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mobius Identity service account tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    signup = sub.add_parser("signup", help="Create dedicated service account (one-time)")
    signup.add_argument("--email", help="Service email (or IDENTITY_SERVICE_EMAIL)")
    signup.add_argument("--password", help="Service password (or IDENTITY_SERVICE_PASSWORD)")
    signup.add_argument("--name", default="Mobius Terminal Service")
    signup.add_argument("--identity-base", dest="identity_base")
    signup.set_defaults(func=cmd_signup)

    smoke = sub.add_parser("smoke", help="Login → introspect → attest smoke test")
    smoke.add_argument("--email", help="Service email (or IDENTITY_SERVICE_EMAIL)")
    smoke.add_argument("--password", help="Service password (or IDENTITY_SERVICE_PASSWORD)")
    smoke.add_argument("--identity-base", dest="identity_base")
    smoke.add_argument("--ledger-url", dest="ledger_url")
    smoke.add_argument(
        "--civic-id",
        dest="civic_id",
        default=None,
        help="Attest civic_id (default mobius-civic-ai-terminal)",
    )
    smoke.set_defaults(func=cmd_smoke)

    args = parser.parse_args()
    try:
        return args.func(args)
    except httpx.HTTPStatusError as exc:
        print(f"HTTP {exc.response.status_code}: {exc.response.text}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
