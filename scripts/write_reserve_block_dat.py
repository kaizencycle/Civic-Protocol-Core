#!/usr/bin/env python3
"""Write one Reserve Block .dat from JSON payload (repository_dispatch / CLI)."""

from __future__ import annotations

import argparse
import json
import sys

from _repo_bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

from ledger.app.reserve_dat import (  # noqa: E402
    build_reserve_block_index,
    write_reserve_block_dat,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Write a Reserve Block .dat canon artifact")
    ap.add_argument(
        "payload_json",
        help="JSON object with cycle, sequence, and block fields",
    )
    args = ap.parse_args()

    data = json.loads(args.payload_json)
    cycle = str(data.get("cycle", "")).strip()
    sequence = int(data.get("sequence", 0))
    if not cycle or sequence < 1:
        print("USAGE: payload must include cycle and sequence >= 1", file=sys.stderr)
        return 2

    payload = data.get("payload") or data
    block_id = payload.get("block_id") or f"reserve-block-{cycle}-{sequence:03d}"
    payload.setdefault("block_id", block_id)
    payload.setdefault("cycle", cycle)
    payload.setdefault("sequence", sequence)

    path = write_reserve_block_dat(payload, cycle=cycle, sequence=sequence)
    index = build_reserve_block_index()
    print(f"[DAT] Wrote {path.name} sha256={path.read_bytes()[-32:].hex()[:16]}...")
    print(f"[INDEX] {index['total_blocks']} block(s) in canon index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
