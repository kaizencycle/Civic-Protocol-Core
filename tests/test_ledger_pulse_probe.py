"""Contract tests for ledger pulse probe (C-496 JOB-33 / PR #106)."""

from __future__ import annotations

import json
import urllib.error
from unittest import mock

import pytest

from scripts.ledger_pulse_probe import (
    NON_OBJECT_JSON_ERROR,
    PulseProbeResult,
    UnsafeProbeUrlError,
    build_pulse_snapshot_dict,
    classify_probe,
    decode_endpoint_json,
    probe_json_url,
    validate_probe_url,
)


def test_classify_render_suspend():
    ok, label = classify_probe(
        http_status=503,
        x_render_routing="suspend",
        content_type="text/html; charset=utf-8",
        parsed_json=None,
    )
    assert ok is False
    assert label == "render_suspend"


def test_classify_app_degraded_json_503():
    ok, label = classify_probe(
        http_status=503,
        x_render_routing=None,
        content_type="application/json",
        parsed_json={"detail": {"status": "degraded"}},
    )
    assert ok is False
    assert label == "app_degraded"


def test_classify_ok_health_json():
    ok, label = classify_probe(
        http_status=200,
        x_render_routing=None,
        content_type="application/json",
        parsed_json={"status": "ok", "ledger_db": {"ok": True}},
    )
    assert ok is True
    assert label == "ok"


def test_validate_probe_url_rejects_file_scheme():
    with pytest.raises(UnsafeProbeUrlError, match="scheme"):
        validate_probe_url("file:///etc/passwd")


def test_validate_probe_url_rejects_credentials():
    with pytest.raises(UnsafeProbeUrlError, match="credentials"):
        validate_probe_url("https://user:pass@example.com/health")


def test_validate_probe_url_requires_https_by_default():
    with pytest.raises(UnsafeProbeUrlError, match="https"):
        validate_probe_url("http://127.0.0.1/health")


def test_snapshot_preserves_health_ledger_db_at_top_level():
    health_json = {
        "status": "ok",
        "service": "civic-ledger-api",
        "ledger_db": {
            "ok": True,
            "path": "/var/lib/ledger/ledger.db",
            "event_count": 42,
        },
    }
    ok, classification = classify_probe(
        http_status=200,
        x_render_routing=None,
        content_type="application/json",
        parsed_json=health_json,
    )
    from scripts.ledger_pulse_probe import PulseProbeResult

    snap = PulseProbeResult(
        url="https://example.com/health",
        ok=ok,
        classification=classification,
        http_status=200,
        x_render_routing=None,
        content_type="application/json",
        parsed_json=health_json,
        error=None,
    ).to_snapshot_dict()
    assert snap["ledger_db"]["event_count"] == 42
    assert snap["classification"] == "ok"
    assert snap["http_status"] == 200
    assert "body" not in snap


def test_snapshot_app_degraded_preserves_detail():
    detail = {"detail": {"status": "degraded", "ledger_db": {"ok": False}}}
    from scripts.ledger_pulse_probe import PulseProbeResult

    snap = PulseProbeResult(
        url="https://example.com/health",
        ok=False,
        classification="app_degraded",
        http_status=503,
        x_render_routing=None,
        content_type="application/json",
        parsed_json=detail,
        error=None,
    ).to_snapshot_dict()
    assert snap["detail"]["ledger_db"]["ok"] is False
    assert snap["classification"] == "app_degraded"
    assert snap["ok"] is False


def test_snapshot_render_suspend_legacy_error_shape():
    from scripts.ledger_pulse_probe import PulseProbeResult

    snap = PulseProbeResult(
        url="https://civic-protocol-core-ledger.onrender.com/health",
        ok=False,
        classification="render_suspend",
        http_status=503,
        x_render_routing="suspend",
        content_type="text/html; charset=utf-8",
        parsed_json=None,
        error="Render service suspended (x-render-routing: suspend)",
    ).to_snapshot_dict()
    assert snap["ok"] is False
    assert "error" in snap
    assert snap["x_render_routing"] == "suspend"
    assert "ledger_db" not in snap


def test_snapshot_epicon_feed_preserves_entries():
    feed = {"entries": [{"id": "e1", "title": "test"}], "count": 1}
    from scripts.ledger_pulse_probe import PulseProbeResult

    snap = PulseProbeResult(
        url="https://example.com/epicon/feed",
        ok=True,
        classification="ok",
        http_status=200,
        x_render_routing=None,
        content_type="application/json",
        parsed_json=feed,
        error=None,
    ).to_snapshot_dict()
    assert snap["entries"][0]["id"] == "e1"
    assert snap["count"] == 1


def test_probe_unsafe_url_rejects_without_network():
    result = probe_json_url("file:///tmp/x")
    assert result.classification == "unsafe_url"
    assert result.ok is False


@mock.patch("scripts.ledger_pulse_probe._read_http_response")
def test_probe_connection_failure(mock_read: mock.MagicMock) -> None:
    mock_read.side_effect = urllib.error.URLError("connection refused")
    result = probe_json_url("https://example.com/health")
    assert result.classification == "unreachable"
    assert result.ok is False
    snap = result.to_snapshot_dict()
    assert snap["ok"] is False
    assert "error" in snap


@mock.patch("scripts.ledger_pulse_probe._read_http_response")
def test_probe_healthy_json(mock_read: mock.MagicMock) -> None:
    payload = json.dumps(
        {"status": "ok", "ledger_db": {"ok": True, "event_count": 9}}
    ).encode()
    mock_read.return_value = (
        200,
        {"content-type": "application/json"},
        payload,
    )
    result = probe_json_url("https://example.com/health")
    assert result.ok is True
    snap = result.to_snapshot_dict()
    assert snap["ledger_db"]["event_count"] == 9


@mock.patch("scripts.ledger_pulse_probe._read_http_response")
def test_probe_render_suspend_html(mock_read: mock.MagicMock) -> None:
    import io

    mock_read.side_effect = urllib.error.HTTPError(
        "https://example.com/health",
        503,
        "Service Unavailable",
        {"x-render-routing": "suspend", "content-type": "text/html"},
        io.BytesIO(b"<html>suspended</html>"),
    )
    result = probe_json_url("https://example.com/health")
    assert result.classification == "render_suspend"
    snap = result.to_snapshot_dict()
    assert snap["classification"] == "render_suspend"
    assert snap["ok"] is False


@pytest.mark.parametrize(
    "body,expected_classification",
    [
        (b"[1, 2, 3]", "invalid_json_shape"),
        (b'"hello"', "invalid_json_shape"),
        (b"42", "invalid_json_shape"),
        (b"null", "invalid_json_shape"),
    ],
)
@mock.patch("scripts.ledger_pulse_probe._read_http_response")
def test_probe_non_object_json_never_crashes(
    mock_read: mock.MagicMock, body: bytes, expected_classification: str
) -> None:
    mock_read.return_value = (200, {"content-type": "application/json"}, body)
    result = probe_json_url("https://example.com/health")
    assert result.classification == expected_classification
    assert result.ok is False
    assert result.parsed_json is None
    snap = result.to_snapshot_dict()
    assert snap["ok"] is False
    assert snap["error"] == NON_OBJECT_JSON_ERROR
    assert "ledger_db" not in snap


@mock.patch("scripts.ledger_pulse_probe._read_http_response")
def test_probe_http_200_html_includes_error(mock_read: mock.MagicMock) -> None:
    mock_read.return_value = (
        200,
        {"content-type": "text/html; charset=utf-8"},
        b"<html>ok</html>",
    )
    result = probe_json_url("https://example.com/health")
    assert result.classification == "unreachable_or_non_json"
    snap = result.to_snapshot_dict()
    assert snap["error"] == NON_OBJECT_JSON_ERROR


@mock.patch("scripts.ledger_pulse_probe._read_http_response")
def test_probe_malformed_json_includes_error(mock_read: mock.MagicMock) -> None:
    mock_read.return_value = (
        200,
        {"content-type": "application/json"},
        b"{not-json",
    )
    result = probe_json_url("https://example.com/health")
    snap = result.to_snapshot_dict()
    assert snap["error"] == NON_OBJECT_JSON_ERROR


def test_decode_endpoint_json_array():
    parsed, err, invalid = decode_endpoint_json(b"[1]")
    assert parsed is None
    assert err == NON_OBJECT_JSON_ERROR
    assert invalid is True


@mock.patch("scripts.ledger_pulse_probe.probe_json_url")
def test_build_pulse_snapshot_dict_does_not_crash_on_bad_json(
    mock_probe: mock.MagicMock,
) -> None:
    bad = PulseProbeResult(
        url="https://example.com/health",
        ok=False,
        classification="invalid_json_shape",
        http_status=200,
        x_render_routing=None,
        content_type="application/json",
        parsed_json=None,
        error=NON_OBJECT_JSON_ERROR,
    )
    mock_probe.return_value = bad
    out = build_pulse_snapshot_dict(base_url="https://example.com")
    assert out["health"]["classification"] == "invalid_json_shape"
    assert out["health"]["error"] == NON_OBJECT_JSON_ERROR
    assert out["schema"] == "MNS_LEDGER_PULSE_SNAPSHOT_V1"
