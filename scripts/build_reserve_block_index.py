#!/usr/bin/env python3
"""Rebuild ledger/reserve-block-index.json from verified .dat artifacts."""

from __future__ import annotations

from _repo_bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

from ledger.app.reserve_dat import build_reserve_block_index, verify_chain  # noqa: E402


def main() -> int:
    verify_chain()
    index = build_reserve_block_index()
    print(
        f"[INDEX] Built: {index['total_blocks']} block(s), "
        f"{index['total_mic_in_canon']} MIC in canon"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
