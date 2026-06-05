"""Tests for deploy-drift allowlist detection."""

from scripts import check_deploy_drift as drift


def test_body_indicates_inbound_ip_block():
    assert drift._body_indicates_inbound_ip_block(403, b"Host not in allowlist")
    assert drift._body_indicates_inbound_ip_block(403, b'{"error":"not in allowlist"}')
    assert not drift._body_indicates_inbound_ip_block(404, b"Host not in allowlist")
    assert not drift._body_indicates_inbound_ip_block(403, b"Forbidden")
