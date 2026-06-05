#!/usr/bin/env python3
"""Regenerate scripts/expected_routes.json from the app's own OpenAPI.

This is the source of truth for deploy-drift detection: it records every HTTP
operation (METHOD + path) the CURRENT code (origin/main) exposes. The drift
checker compares a live deployment against this manifest. Run after
intentionally adding/removing routes:

    python3 scripts/gen_route_manifest.py

The app imports cleanly with ephemeral storage + a throwaway sqlite DB, so this
works in CI without Postgres or a persistent disk.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "expected_routes.json"

HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})


def operations_from_openapi(spec: dict) -> list[str]:
    """Return sorted METHOD path strings from an OpenAPI spec."""
    ops: set[str] = set()
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                ops.add(f"{method.upper()} {path}")
    return sorted(ops)


def load_app_operations() -> list[str]:
    # Make the app importable in a stateless way (no Postgres, no persistent disk).
    os.environ.setdefault("LEDGER_ALLOW_EPHEMERAL", "true")
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/cpc_manifest_gen.db")
    os.environ.setdefault("LEDGER_DATA_DIR", "/tmp")

    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Suppress the app's import-time stdout (startup banners).
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        from ledger.app.main import app  # noqa: E402

        return operations_from_openapi(app.openapi())


def main() -> int:
    operations = load_app_operations()
    path_count = len({op.split(" ", 1)[1] for op in operations})
    manifest = {
        "generated_from": "ledger.app.main:app OpenAPI (METHOD + path)",
        "operation_count": len(operations),
        "path_count": path_count,
        "operations": operations,
        "note": (
            "Source of truth for deploy-drift detection. Each entry is "
            "'METHOD /path'. Regenerate with scripts/gen_route_manifest.py "
            "after intentionally adding/removing routes or HTTP methods."
        ),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {MANIFEST} — {len(operations)} operations across {path_count} paths",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
