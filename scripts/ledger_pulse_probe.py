"""
Classify live ledger pulse probes for mesh-pulse-snapshot (C-496 JOB-33).

Distinguishes Render platform suspend (HTML 503 + x-render-routing: suspend)
from in-app degraded /health JSON 503 and successful JSON responses.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class UnsafeProbeUrlError(ValueError):
    """Raised when a probe URL is outside the allowed http(s) contract."""


@dataclass(frozen=True)
class PulseProbeResult:
    url: str
    ok: bool
    classification: str
    http_status: int | None
    x_render_routing: str | None
    content_type: str | None
    parsed_json: dict[str, Any] | None
    error: str | None

    def to_snapshot_dict(self) -> dict[str, Any]:
        """Snapshot shape: endpoint JSON at top level; probe metadata alongside."""
        if self.parsed_json is not None:
            out = dict(self.parsed_json)
            out["ok"] = self.ok
        else:
            out = {"ok": self.ok, "url": self.url}
            if self.error is not None:
                out["error"] = self.error

        out["classification"] = self.classification
        if self.http_status is not None:
            out["http_status"] = self.http_status
        if self.x_render_routing is not None:
            out["x_render_routing"] = self.x_render_routing
        if self.content_type is not None:
            out["content_type"] = self.content_type
        if (
            self.parsed_json is None
            and "url" not in out
            or self.parsed_json is not None
            and "url" not in out
        ):
            out["url"] = self.url
        return out


def validate_probe_url(url: str, *, allow_http: bool = False) -> str:
    """
    Validate URL before urllib fetch. Production probes require https:// only;
    tests may pass allow_http=True for loopback http URLs.
    """
    cleaned = url.strip()
    if not cleaned:
        raise UnsafeProbeUrlError("URL must not be empty")
    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UnsafeProbeUrlError(f"disallowed URL scheme: {scheme!r}")
    if scheme == "http" and not allow_http:
        raise UnsafeProbeUrlError(
            "only https:// URLs are allowed for ledger pulse probes"
        )
    if parsed.username or parsed.password:
        raise UnsafeProbeUrlError("URL must not embed credentials")
    if not parsed.hostname:
        raise UnsafeProbeUrlError("URL must include a host")
    return cleaned


def validate_ledger_public_base(base: str, *, allow_http: bool = False) -> str:
    return validate_probe_url(base.rstrip("/"), allow_http=allow_http)


def classify_probe(
    *,
    http_status: int,
    x_render_routing: str | None,
    content_type: str | None,
    parsed_json: dict[str, Any] | None,
) -> tuple[bool, str]:
    routing = (x_render_routing or "").strip().lower()
    if routing == "suspend":
        return False, "render_suspend"
    if http_status >= 500 and (content_type or "").startswith("text/html"):
        return False, "platform_error_html"
    if parsed_json is not None and http_status == 200:
        return True, "ok"
    if parsed_json is not None and http_status == 503:
        return False, "app_degraded"
    if http_status == 404:
        return False, "not_found"
    if parsed_json is not None:
        return http_status < 400, "http_json"
    return False, "unreachable_or_non_json"


def _read_http_response(
    url: str, *, timeout: float
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(
        url, headers={"User-Agent": "mobius-ledger-pulse-snapshot/1.1"}
    )
    # S310: scheme/host validated in validate_probe_url immediately before this call.
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        raw = response.read()
        http_status = int(getattr(response, "status", 200))
        headers = {k.lower(): v for k, v in response.headers.items()}
        return http_status, headers, raw


def _read_http_error(exc: urllib.error.HTTPError) -> tuple[int, dict[str, str], bytes]:
    raw = exc.read()
    headers = {k.lower(): v for k, v in exc.headers.items()}
    return int(exc.code), headers, raw


def probe_json_url(
    url: str,
    *,
    timeout: float = 20.0,
    allow_http: bool = False,
) -> PulseProbeResult:
    """HTTP GET with classification metadata for pulse snapshots."""
    try:
        safe_url = validate_probe_url(url, allow_http=allow_http)
    except UnsafeProbeUrlError as exc:
        return PulseProbeResult(
            url=url,
            ok=False,
            classification="unsafe_url",
            http_status=None,
            x_render_routing=None,
            content_type=None,
            parsed_json=None,
            error=str(exc),
        )

    try:
        http_status, headers, raw = _read_http_response(safe_url, timeout=timeout)
        x_render_routing = headers.get("x-render-routing")
        content_type = headers.get("content-type")
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        ok, classification = classify_probe(
            http_status=http_status,
            x_render_routing=x_render_routing,
            content_type=content_type,
            parsed_json=parsed,
        )
        return PulseProbeResult(
            url=safe_url,
            ok=ok,
            classification=classification,
            http_status=http_status,
            x_render_routing=x_render_routing,
            content_type=content_type,
            parsed_json=parsed,
            error=None,
        )
    except urllib.error.HTTPError as exc:
        http_status, headers, raw = _read_http_error(exc)
        x_render_routing = headers.get("x-render-routing")
        content_type = headers.get("content-type")
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        ok, classification = classify_probe(
            http_status=http_status,
            x_render_routing=x_render_routing,
            content_type=content_type,
            parsed_json=parsed,
        )
        err: str | None = None
        if not ok and classification == "render_suspend":
            err = "Render service suspended (x-render-routing: suspend)"
        elif not ok and parsed is None:
            snippet = raw.decode(errors="replace")[:120].strip()
            err = snippet or exc.reason
        return PulseProbeResult(
            url=safe_url,
            ok=ok,
            classification=classification,
            http_status=http_status,
            x_render_routing=x_render_routing,
            content_type=content_type,
            parsed_json=parsed,
            error=err,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return PulseProbeResult(
            url=safe_url,
            ok=False,
            classification="unreachable",
            http_status=None,
            x_render_routing=None,
            content_type=None,
            parsed_json=None,
            error=str(exc),
        )
