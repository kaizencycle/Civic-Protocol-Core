"""Tests for C-355 Reserve Block .dat canon artifacts."""

import json
from pathlib import Path

import pytest

from ledger.app.reserve_dat import (
    build_reserve_block_index,
    load_reserve_block_index,
    read_reserve_block_dat,
    verify_chain,
    write_reserve_block_dat,
)


@pytest.fixture
def dat_dirs(tmp_path: Path, monkeypatch):
    dat_dir = tmp_path / "reserve-blocks"
    index_path = tmp_path / "reserve-block-index.json"
    monkeypatch.setattr("ledger.app.reserve_dat.DEFAULT_RESERVE_BLOCKS_DIR", dat_dir)
    monkeypatch.setattr("ledger.app.reserve_dat.DEFAULT_INDEX_PATH", index_path)
    return dat_dir, index_path


def test_write_read_roundtrip(dat_dirs):
    dat_dir, _ = dat_dirs
    payload = {
        "block_id": "reserve-block-C355-001",
        "cycle": "C355",
        "sequence": 1,
        "gi_at_seal": 0.97,
        "mic_minted": 50.0,
        "quorum_met": True,
        "sealed_at": "2026-06-27T17:00:05Z",
    }
    path = write_reserve_block_dat(payload, cycle="C355", sequence=1, output_dir=dat_dir)
    block = read_reserve_block_dat(path)
    assert block["verified"] is True
    assert block["payload"]["block_id"] == "reserve-block-C355-001"
    assert block["hash"]


def test_hash_mismatch_raises(dat_dirs):
    dat_dir, _ = dat_dirs
    path = write_reserve_block_dat(
        {"block_id": "reserve-block-C355-001", "cycle": "C355", "sequence": 1},
        cycle="C355",
        sequence=1,
        output_dir=dat_dir,
    )
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="Hash mismatch"):
        read_reserve_block_dat(path)


def test_build_index_from_dat(dat_dirs):
    dat_dir, index_path = dat_dirs
    write_reserve_block_dat(
        {
            "block_id": "reserve-block-C355-001",
            "cycle": "C355",
            "sequence": 1,
            "mic_minted": 50.0,
            "quorum_met": True,
            "sealed_at": "2026-06-27T17:00:05Z",
        },
        cycle="C355",
        sequence=1,
        output_dir=dat_dir,
    )
    index = build_reserve_block_index(dat_dir=dat_dir, index_path=index_path)
    assert index["total_blocks"] == 1
    assert index["total_mic_in_canon"] == 50.0
    loaded = json.loads(index_path.read_text())
    assert loaded["blocks"][0]["sha256"]
    assert load_reserve_block_index(index_path)["total_blocks"] == 1


def test_verify_chain_empty_dir(dat_dirs):
    dat_dir, _ = dat_dirs
    dat_dir.mkdir(parents=True, exist_ok=True)
    assert verify_chain(dat_dir) == []
