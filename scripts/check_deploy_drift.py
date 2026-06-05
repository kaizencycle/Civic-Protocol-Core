#!/usr/bin/env python3
"""Deploy-drift alarm for the Civic Protocol Core Ledger.

WHY THIS EXISTS (C-332): the deployed ledger silently fell ~10 routes behind
origin/main for multiple cycles. `/api/vault/*`, `/api/seal/*`, and
`/api/epicon/ingest` returned 404 live while present in the code, so Terminal
calls to e.g. /api/seal/reconcile hit a stale release, not a real bug. Nothing
caught it because nothing audited live-vs-main. This makes that drift LOUD.

It compares a LIVE deployment's OpenAPI route set against the committed manifest
(scripts/expected_routes.json, generated from the app itself by
gen_route_manifest.py). If the live deployment is missing any expected route, it
fails — that is deploy drift.

Cold-start gate: Render free/instance tiers cold-start after idle; the first
request can time out or 5xx. That is NOT drift. The checker retries with backoff
and only asserts drift once the service is provably reachable (200 on /health or
a parseable /openapi.json). If it never becomes reachable within the budget, it
exits UNRESOLVED (distinct from DRIFT) so a transient outage doesn't masquerade
as a drift alarm.

Usage:
    python3 scripts/check_deploy_drift.py --url https://civic-protocol-core-ledger.onrender.com
    python3 scripts/check_deploy_drift.py --url <URL> --manifest scripts/expected_routes.json

Exit codes:
    0  OK        — live serves every expected route
    1  DRIFT     — reachable, but missing expected route(s)
    2  UNRESOLVED — could not reach the service (cold start / outage); inconclusive
    3  USAGE/IO  — bad args or manifest
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EXIT_OK, EXIT_DRIFT, EXIT_UNRESOLVED, EXIT_USAGE = 0, 1, 2, 3

DEFAULT_MANIFEST = Path(__file__).resolve().parent / "expected_routes.json"


def _get(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "cpc-drift-check"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, b""


def fetch_live_paths(base: str, attempts: int, base_delay: float) -> set[str] | None:
    """Return live OpenAPI paths, or None if the service never became reachable.

    Retries with exponential backoff to absorb cold starts. Reachability is
    proven by a parseable /openapi.json; a 200 /health alone counts as 'alive but
    spec unavailable' and keeps retrying the spec.
    """
    base = base.rstrip("/")
    openapi_url = f"{base}/openapi.json"
    health_url = f"{base}/health"
    seen_alive = False

    for i in range(attempts):
        status, body = _get(openapi_url, timeout=20)
        if status == 200 and body:
            try:
                spec = json.loads(body)
                return set(spec.get("paths", {}).keys())
            except json.JSONDecodeError:
                pass  # alive but spec garbled; retry
        # Spec not yet available — is the service at least alive?
        hstatus, _ = _get(health_url, timeout=15)
        if hstatus == 200:
            seen_alive = True
        if i < attempts - 1:
            delay = base_delay * (2 ** i)
            print(
                f"  [retry {i+1}/{attempts}] openapi={status} health={hstatus} "
                f"— waiting {delay:.0f}s (cold start?)",
                file=sys.stderr,
            )
            time.sleep(delay)

    # Never got a parseable spec.
    if seen_alive:
        print(
            "  service responded to /health but never served a parseable spec",
            file=sys.stderr,
        )
    else:
        print("  service never became reachable", file=sys.stderr)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="CPC ledger deploy-drift alarm")
    ap.add_argument("--url", required=True, help="Base URL of the live deployment")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument(
        "--attempts",
        type=int,
        default=5,
        help="Reachability attempts (cold-start budget)",
    )
    ap.add_argument(
        "--base-delay",
        type=float,
        default=5.0,
        help="Initial backoff seconds (doubles each retry)",
    )
    args = ap.parse_args()

    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        expected = set(manifest["routes"])
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"USAGE/IO: cannot read manifest {args.manifest}: {e}", file=sys.stderr)
        return EXIT_USAGE

    print(f"Expected routes (from manifest): {len(expected)}")
    print(f"Probing live: {args.url}")

    live = fetch_live_paths(args.url, args.attempts, args.base_delay)
    if live is None:
        print(
            "UNRESOLVED: live service unreachable within cold-start budget "
            "— inconclusive, not drift."
        )
        return EXIT_UNRESOLVED

    missing = sorted(expected - live)
    extra = sorted(live - expected)  # informational only (live ahead of manifest)

    print(f"Live routes: {len(live)}")
    if extra:
        print(
            f"  note: live exposes {len(extra)} route(s) not in manifest "
            f"(regen manifest if intentional): {extra}"
        )

    if missing:
        print(f"\nDRIFT: live is missing {len(missing)} expected route(s):")
        for path in missing:
            print(f"  - {path}")
        print("\nThe deployed build is behind the committed code. Redeploy current main.")
        return EXIT_DRIFT

    print("\nOK: live serves every expected route. No drift.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
