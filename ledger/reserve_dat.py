"""C-355: portable Reserve Block .dat read/write/verify (MOBIUS01 format)."""

from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAGIC = b"MOBIUS01"
VERSION = b"\x00\x01"

_LEDGER_PKG = Path(__file__).resolve().parent
DEFAULT_RESERVE_BLOCKS_DIR = _LEDGER_PKG / "reserve-blocks"
DEFAULT_INDEX_PATH = _LEDGER_PKG / "reserve-block-index.json"


def _parse_cycle_number(cycle: str) -> int:
    return int(cycle.lstrip("Cc"))


def _block_filename(cycle: str, sequence: int) -> str:
    return f"reserve-block-{cycle}-{sequence:03d}.dat"


def write_reserve_block_dat(
    payload: dict[str, Any],
    cycle: str,
    sequence: int,
    output_dir: Path | None = None,
) -> Path:
    """Write a sealed Reserve Block to a self-verifying .dat file."""
    output_dir = output_dir or DEFAULT_RESERVE_BLOCKS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    cycle_num = _parse_cycle_number(cycle)
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    payload_length = len(payload_bytes)

    header = (
        MAGIC
        + VERSION
        + struct.pack(">I", cycle_num)
        + struct.pack(">I", sequence)
        + struct.pack(">I", payload_length)
    )
    content = header + payload_bytes
    digest = hashlib.sha256(content).digest()

    filepath = output_dir / _block_filename(cycle, sequence)
    filepath.write_bytes(content + digest)
    return filepath


def read_reserve_block_dat(filepath: Path) -> dict[str, Any]:
    """Read and verify a .dat file. Raises ValueError on hash or magic mismatch."""
    data = filepath.read_bytes()
    if len(data) < 54:
        raise ValueError(f"[DAT] File too short: {filepath.name}")

    stored_hash = data[-32:]
    content = data[:-32]
    computed_hash = hashlib.sha256(content).digest()
    if stored_hash != computed_hash:
        raise ValueError(
            f"[DAT] Hash mismatch on {filepath.name}. File is corrupted or tampered."
        )

    magic = content[:8]
    if magic != MAGIC:
        raise ValueError(f"[DAT] Invalid magic bytes in {filepath.name}")

    cycle_num = struct.unpack(">I", content[10:14])[0]
    sequence = struct.unpack(">I", content[14:18])[0]
    payload_length = struct.unpack(">I", content[18:22])[0]
    payload_bytes = content[22 : 22 + payload_length]

    return {
        "cycle": f"C{cycle_num}",
        "sequence": sequence,
        "payload": json.loads(payload_bytes.decode("utf-8")),
        "hash": stored_hash.hex(),
        "verified": True,
        "file": str(filepath),
    }


def verify_chain(dat_dir: Path | None = None) -> list[dict[str, Any]]:
    """Verify every reserve-block-*.dat in dat_dir; raise on first failure."""
    dat_dir = dat_dir or DEFAULT_RESERVE_BLOCKS_DIR
    if not dat_dir.exists():
        return []

    chain: list[dict[str, Any]] = []
    for filepath in sorted(dat_dir.glob("reserve-block-*.dat")):
        block = read_reserve_block_dat(filepath)
        chain.append(
            {
                "file": filepath.name,
                "cycle": block["cycle"],
                "sequence": block["sequence"],
                "hash": block["hash"],
                "verified": True,
            }
        )
    return chain


def build_reserve_block_index(
    dat_dir: Path | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    """Rebuild reserve-block-index.json from verified .dat artifacts."""
    dat_dir = dat_dir or DEFAULT_RESERVE_BLOCKS_DIR
    index_path = index_path or DEFAULT_INDEX_PATH

    blocks: list[dict[str, Any]] = []
    total_mic = 0.0

    if dat_dir.exists():
        for filepath in sorted(dat_dir.glob("reserve-block-*.dat")):
            block = read_reserve_block_dat(filepath)
            payload = block["payload"]
            mic = float(payload.get("mic_minted", 0) or 0)
            total_mic += mic
            rel_file = f"ledger/reserve-blocks/{filepath.name}"
            blocks.append(
                {
                    "block_id": payload.get("block_id")
                    or f"reserve-block-{block['cycle']}-{block['sequence']:03d}",
                    "cycle": block["cycle"],
                    "sequence": block["sequence"],
                    "file": rel_file,
                    "sha256": block["hash"],
                    "gi_at_seal": payload.get("gi_at_seal"),
                    "mic_minted": mic,
                    "sealed_at": payload.get("sealed_at"),
                    "quorum_met": bool(payload.get("quorum_met", False)),
                    "replay_available": True,
                }
            )

    index = {
        "version": "1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "blocks": blocks,
        "chain_verified": True,
        "total_mic_in_canon": total_mic,
        "total_blocks": len(blocks),
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index


def load_reserve_block_index(index_path: Path | None = None) -> dict[str, Any]:
    """Load index JSON; return empty scaffold when missing."""
    index_path = index_path or DEFAULT_INDEX_PATH
    if not index_path.exists():
        return {
            "version": "1",
            "blocks": [],
            "chain_verified": False,
            "total_mic_in_canon": 0.0,
            "total_blocks": 0,
        }
    return json.loads(index_path.read_text(encoding="utf-8"))
