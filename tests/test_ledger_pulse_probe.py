"""Unit tests for scripts/ledger_pulse_probe.classify_probe."""

from scripts.ledger_pulse_probe import classify_probe


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