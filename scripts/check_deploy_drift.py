#!/usr/bin/env python3
"""Deploy-drift alarm for the Civic Protocol Core Ledger.

WHY THIS EXISTS (C-332): the deployed ledger silently fell ~10 routes behind
origin/main for multiple cycles. `/api/vault/*`, `/api/seal/*`, and
`/api/epicon/ingest` returned 404 live while present in the code, so Terminal
calls to e.g. /api/seal/reconcile hit a stale release, not a real bug. Nothing
caught it because nothing audited live-vs-main. This makes that drift LOUD.

It compares a LIVE deployment's OpenAPI operation set (METHOD + path) against
the committed manifest (scripts/expected_routes.json, generated from the app by
gen_route_manifest.py). If the live deployment is missing any expected operation,
it fails — that is deploy drift.

Path-only comparison is insufficient: the same URL can expose GET but not POST
(e.g. /api/oaa/memory). Comparing paths alone would pass while one method still
405s in production.

Cold-start gate: Render free/instance tiers cold-start after idle; the first
request can time out or 5xx. That is NOT drift. The checker retries with backoff
and only asserts drift once the service is provably reachable (parseable
/openapi.json). If it never becomes reachable within the budget, it exits
UNRESOLVED (distinct from DRIFT) so a transient outage doesn't masquerade as a
drift alarm.

Render inbound IP rules: disallowed clients get HTTP 403 with a body like
"Host not in allowlist". That is NOT cold start and NOT drift — exit BLOCKED.

Usage:
    python3 scripts/check_deploy_drift.py --url https://civic-protocol-core-ledger.onrender.com
    python3 scripts/check_deploy_drift.py --url <URL> --manifest scripts/expected_routes.json

Exit codes:
    0  OK        — live serves every expected operation
    1  DRIFT     — reachable, but missing expected operation(s)
    2  UNRESOLVED — could not reach the service (cold start / outage); inconclusive
    3  USAGE/IO  — bad args or manifest
    4  BLOCKED   — Render inbound IP rules rejected the probe (403 allowlist); inconclusive
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})


def operations_from_openapi(spec: dict) -> list[str]:
    ops: set[str] = set()
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                ops.add(f"{method.upper()} {path}")
    return sorted(ops)


EXIT_OK, EXIT_DRIFT, EXIT_UNRESOLVED, EXIT_USAGE, EXIT_BLOCKED = 0, 1, 2, 3, 4

DEFAULT_MANIFEST = Path(__file__).resolve().parent / "expected_routes.json"

# Render inbound IP rules return 403 with a body like "Host not in allowlist".
_ALLOWLIST_MARKERS = ("host not in allowlist", "not in allowlist")


def _get(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "cpc-drift-check"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, b""


def _body_indicates_inbound_ip_block(status: int, body: bytes) -> bool:
    if status != 403:
        return False
    text = body.decode("utf-8", errors="replace").lower()
    return any(marker in text for marker in _ALLOWLIST_MARKERS)


def probe_inbound_ip_blocked(base: str) -> bool:
    """True when Render inbound IP rules reject this client's probes."""
    base = base.rstrip("/")
    for path in ("/health", "/openapi.json"):
        status, body = _get(f"{base}{path}", timeout=15)
        if _body_indicates_inbound_ip_block(status, body):
            return True
    return False


def load_expected_operations(manifest_path: Path) -> set[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "operations" in manifest:
        return set(manifest["operations"])
    # Legacy path-only manifests (pre method-aware drift check).
    return {f"GET {path}" for path in manifest["routes"]}


def fetch_live_operations(
    base: str, attempts: int, base_delay: float
) -> set[str] | None:
    """Return live OpenAPI operations, or None if never reachable."""
    base = base.rstrip("/")
    openapi_url = f"{base}/openapi.json"
    health_url = f"{base}/health"
    seen_alive = False

    for i in range(attempts):
        status, body = _get(openapi_url, timeout=20)
        if status == 200 and body:
            try:
                spec = json.loads(body)
                return set(operations_from_openapi(spec))
            except json.JSONDecodeError:
                pass
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

    manifest_path = Path(args.manifest)
    try:
        expected = load_expected_operations(manifest_path)
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"USAGE/IO: cannot read manifest {args.manifest}: {e}", file=sys.stderr)
        return EXIT_USAGE

    print(f"Expected operations (from manifest): {len(expected)}")
    print(f"Probing live: {args.url}")

    if probe_inbound_ip_blocked(args.url):
        print(
            "BLOCKED: Render inbound IP rules rejected this probe (403 allowlist). "
            "The service may be healthy for other clients — this is NOT deploy drift. "
            "Run from GitHub Actions (deploy-drift-alarm) or adjust Render inbound rules.",
            file=sys.stderr,
        )
        return EXIT_BLOCKED

    live = fetch_live_operations(args.url, args.attempts, args.base_delay)
    if live is None:
        print(
            "UNRESOLVED: live service unreachable within cold-start budget "
            "— inconclusive, not drift."
        )
        return EXIT_UNRESOLVED

    missing = sorted(expected - live)
    extra = sorted(live - expected)

    print(f"Live operations: {len(live)}")
    if extra:
        print(
            f"  note: live exposes {len(extra)} operation(s) not in manifest "
            f"(regen manifest if intentional): {extra[:8]}{'...' if len(extra) > 8 else ''}"
        )

    if missing:
        print(f"\nDRIFT: live is missing {len(missing)} expected operation(s):")
        for op in missing:
            print(f"  - {op}")
        print("\nThe deployed build is behind the committed code. Redeploy current main.")
        return EXIT_DRIFT

    print("\nOK: live serves every expected operation. No drift.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
