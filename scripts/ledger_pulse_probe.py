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


@dataclass(frozen=True)
class PulseProbeResult:
    url: str
    ok: bool
    classification: str
    http_status: int | None
    x_render_routing: str | None
    content_type: str | None
    body: dict[str, Any] | None
    error: str | None

    def to_snapshot_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": self.ok,
            "classification": self.classification,
            "url": self.url,
        }
        if self.http_status is not None:
            out["http_status"] = self.http_status
        if self.x_render_routing is not None:
            out["x_render_routing"] = self.x_render_routing
        if self.content_type is not None:
            out["content_type"] = self.content_type
        if self.body is not None:
            out["body"] = self.body
        if self.error is not None:
            out["error"] = self.error
        return out


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


def probe_json_url(url: str, *, timeout: float = 20.0) -> PulseProbeResult:
    """HTTP GET with classification metadata for pulse snapshots."""
    req = urllib.request.Request(url, headers={"User-Agent": "mobius-ledger-pulse-snapshot/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            http_status = int(getattr(response, "status", 200))
            headers = {k.lower(): v for k, v in response.headers.items()}
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
                url=url,
                ok=ok,
                classification=classification,
                http_status=http_status,
                x_render_routing=x_render_routing,
                content_type=content_type,
                body=parsed,
                error=None,
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        headers = {k.lower(): v for k, v in exc.headers.items()}
        x_render_routing = headers.get("x-render-routing")
        content_type = headers.get("content-type")
        http_status = int(exc.code)
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
            url=url,
            ok=ok,
            classification=classification,
            http_status=http_status,
            x_render_routing=x_render_routing,
            content_type=content_type,
            body=parsed,
            error=err,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return PulseProbeResult(
            url=url,
            ok=False,
            classification="unreachable",
            http_status=None,
            x_render_routing=None,
            content_type=None,
            body=None,
            error=str(exc),
        )