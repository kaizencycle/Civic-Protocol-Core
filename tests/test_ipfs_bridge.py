"""Unit tests for ledger IPFS bridge (canonical bytes + CIDv0)."""

import json

import pytest

from ledger.ipfs_bridge import (
    canonical_mesh_payload,
    content_digest_sha256,
    digest_to_cidv0,
    cidv0_to_digest_hex,
)


def test_canonical_payload_stable():
    row = {
        "id": "e1",
        "node_id": "n1",
        "node_tier": "contributor",
        "timestamp": "2026-01-01T00:00:00Z",
        "title": "t",
        "sha": "abc",
        "source": "mesh-node",
        "raw": '{"x":1}',
    }
    a = canonical_mesh_payload(row)
    b = canonical_mesh_payload(row)
    assert a == b
    assert b.startswith(b"{")
    parsed = json.loads(b)
    assert parsed["raw"] == {"x": 1}


def test_cidv0_round_trip():
    data = b'{"hello":"world"}'
    digest = content_digest_sha256(data)
    cid = digest_to_cidv0(digest)
    assert len(cid) > 30
    hex_back = cidv0_to_digest_hex(cid)
    assert bytes.fromhex(hex_back) == digest


def test_cidv0_rejects_bad_digest():
    with pytest.raises(ValueError):
        digest_to_cidv0(b"short")
