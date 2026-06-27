#!/usr/bin/env python3
"""Verify all reserve-block-*.dat files under ledger/reserve-blocks/."""

from __future__ import annotations

from _repo_bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

from ledger.app.reserve_dat import (  # noqa: E402
    DEFAULT_RESERVE_BLOCKS_DIR,
    verify_chain,
)


def main() -> int:
    chain = verify_chain(DEFAULT_RESERVE_BLOCKS_DIR)
    print(f"[DAT] Chain verified: {len(chain)} block(s)")
    for block in chain:
        print(f"  {block['file']} -> {block['hash'][:16]}... ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
