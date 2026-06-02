"""C-331 contract test: the ledger must refuse ephemeral storage in production.

Reproduces the live failure (event_count=0 while 177 blocks "sealed") by
asserting that an ephemeral data dir + production context aborts startup, while
a persistent mount or an explicit dev opt-in is allowed.

Run: python3 tests/test_persistence_guard.py
"""

import importlib
import os
import sys

# Import the module under test by path so this runs from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ledger", "app"))


def _reload_db(env: dict):
    """Reload db.py with a controlled environment and return the module."""
    for k in (
        "RENDER",
        "RENDER_SERVICE_ID",
        "ENV",
        "ENVIRONMENT",
        "LEDGER_DATA_DIR",
        "LEDGER_ALLOW_EPHEMERAL",
    ):
        os.environ.pop(k, None)
    os.environ.update(env)
    import db  # type: ignore

    return importlib.reload(db)


def expect_raises(fn, label):
    try:
        fn()
    except RuntimeError:
        print(f"ok   - {label} (aborted as expected)")
        return 0
    print(f"FAIL - {label} (should have raised RuntimeError)")
    return 1


def expect_ok(fn, label):
    try:
        fn()
        print(f"ok   - {label}")
        return 0
    except RuntimeError as e:
        print(f"FAIL - {label}: unexpectedly raised: {e}")
        return 1


def main() -> int:
    failures = 0

    # 1. Ephemeral + production → MUST abort (the live bug).
    db = _reload_db({"RENDER": "true", "LEDGER_DATA_DIR": "/tmp/ledger_data"})
    assert db.is_ephemeral_path("/tmp/ledger_data") is True
    assert db.is_production() is True
    failures += expect_raises(
        lambda: db.assert_persistent_storage("/tmp/ledger_data"),
        "ephemeral /tmp in production",
    )

    # 2. Persistent disk + production → MUST start.
    db = _reload_db({"RENDER": "true", "LEDGER_DATA_DIR": "/var/lib/ledger"})
    assert db.is_ephemeral_path("/var/lib/ledger") is False
    failures += expect_ok(
        lambda: db.assert_persistent_storage("/var/lib/ledger"),
        "persistent /var/lib/ledger in production",
    )

    # 3. Ephemeral + explicit dev opt-in → allowed.
    db = _reload_db(
        {
            "RENDER": "true",
            "LEDGER_ALLOW_EPHEMERAL": "true",
            "LEDGER_DATA_DIR": "/tmp/ledger_data",
        }
    )
    assert db.is_production() is False
    failures += expect_ok(
        lambda: db.assert_persistent_storage("/tmp/ledger_data"),
        "ephemeral with LEDGER_ALLOW_EPHEMERAL=true",
    )

    # 4. Ephemeral + local (no prod markers) → allowed.
    db = _reload_db({"LEDGER_DATA_DIR": "/tmp/ledger_data"})
    assert db.is_production() is False
    failures += expect_ok(
        lambda: db.assert_persistent_storage("/tmp/ledger_data"),
        "ephemeral in local dev (no prod markers)",
    )

    # 5. ENV=production also triggers prod detection.
    db = _reload_db({"ENV": "production", "LEDGER_DATA_DIR": "/tmp/x"})
    assert db.is_production() is True
    failures += expect_raises(
        lambda: db.assert_persistent_storage("/tmp/x"),
        "ENV=production + ephemeral",
    )

    # 6. /var/tmp is also recognized as ephemeral.
    db = _reload_db({"RENDER": "true", "LEDGER_DATA_DIR": "/var/tmp/ledger"})
    assert db.is_ephemeral_path("/var/tmp/ledger") is True
    failures += expect_raises(
        lambda: db.assert_persistent_storage("/var/tmp/ledger"),
        "/var/tmp in production",
    )

    print(f"\n{'PASS' if failures == 0 else 'FAIL'}: {6 - failures}/6 checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
