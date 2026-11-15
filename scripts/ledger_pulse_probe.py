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

NON_OBJECT_JSON_ERROR = (
    "Expected JSON object response; received non-JSON or non-object JSON."
)


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
        if "url" not in out:
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


def decode_endpoint_json(
    raw: bytes,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    """
    Parse response body as JSON object for snapshot merge.

    Returns (parsed_object, error_message, invalid_json_shape).
    invalid_json_shape is True when JSON decoded but was not a JSON object
    (array, primitive, or null).
    """
    try:
        text = raw.decode()
    except UnicodeDecodeError:
        return None, NON_OBJECT_JSON_ERROR, False
    try:
        loaded: Any = json.loads(text)
    except json.JSONDecodeError:
        return None, NON_OBJECT_JSON_ERROR, False
    if not isinstance(loaded, dict):
        return None, NON_OBJECT_JSON_ERROR, True
    return loaded, None, False


def classify_probe(
    *,
    http_status: int,
    x_render_routing: str | None,
    content_type: str | None,
    parsed_json: dict[str, Any] | None,
    invalid_json_shape: bool = False,
) -> tuple[bool, str]:
    routing = (x_render_routing or "").strip().lower()
    if routing == "suspend":
        return False, "render_suspend"
    if invalid_json_shape:
        return False, "invalid_json_shape"
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


def _probe_error_message(
    *,
    classification: str,
    parsed_json: dict[str, Any] | None,
    decode_error: str | None,
    raw: bytes,
    http_reason: str | None = None,
) -> str | None:
    if classification == "render_suspend":
        return "Render service suspended (x-render-routing: suspend)"
    if decode_error is not None and parsed_json is None:
        return decode_error
    if not parsed_json and classification in (
        "unreachable_or_non_json",
        "invalid_json_shape",
        "platform_error_html",
    ):
        if decode_error:
            return decode_error
        snippet = raw.decode(errors="replace")[:120].strip()
        return snippet or http_reason or NON_OBJECT_JSON_ERROR
    return None


def _result_from_http(
    *,
    safe_url: str,
    http_status: int,
    headers: dict[str, str],
    raw: bytes,
    http_reason: str | None = None,
) -> PulseProbeResult:
    x_render_routing = headers.get("x-render-routing")
    content_type = headers.get("content-type")
    parsed, decode_error, invalid_shape = decode_endpoint_json(raw)
    ok, classification = classify_probe(
        http_status=http_status,
        x_render_routing=x_render_routing,
        content_type=content_type,
        parsed_json=parsed,
        invalid_json_shape=invalid_shape,
    )
    err = _probe_error_message(
        classification=classification,
        parsed_json=parsed,
        decode_error=decode_error,
        raw=raw,
        http_reason=http_reason,
    )
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


def build_pulse_snapshot_dict(
    *,
    base_url: str,
    health_path: str = "/health",
    feed_path: str = "/epicon/feed?limit=10",
    allow_http: bool = False,
) -> dict[str, Any]:
    """Shape written by the ledger-pulse-snapshot workflow (for contract tests)."""
    from datetime import UTC, datetime

    base = validate_ledger_public_base(base_url, allow_http=allow_http)
    health = probe_json_url(f"{base}{health_path}", allow_http=allow_http)
    feed = probe_json_url(f"{base}{feed_path}", allow_http=allow_http)
    return {
        "schema": "MNS_LEDGER_PULSE_SNAPSHOT_V1",
        "node_id": "civic-protocol-core",
        "captured_at": datetime.now(UTC).isoformat(),
        "ledger_base_url": base,
        "health": health.to_snapshot_dict(),
        "epicon_feed": feed.to_snapshot_dict(),
    }


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
        return _result_from_http(
            safe_url=safe_url,
            http_status=http_status,
            headers=headers,
            raw=raw,
        )
    except urllib.error.HTTPError as exc:
        http_status, headers, raw = _read_http_error(exc)
        return _result_from_http(
            safe_url=safe_url,
            http_status=http_status,
            headers=headers,
            raw=raw,
            http_reason=exc.reason,
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
