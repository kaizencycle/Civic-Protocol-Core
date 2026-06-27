"""CLI shim — canonical module is ledger.app.reserve_dat."""

from _repo_bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

from ledger.app.reserve_dat import *  # noqa: F403, E402
