#!/usr/bin/env python3
"""Regenerate scripts/expected_routes.json from the app's own OpenAPI.

This is the source of truth for deploy-drift detection: it records every route
the CURRENT code (origin/main) exposes. The drift checker compares a live
deployment against this manifest. Run after intentionally adding/removing routes:

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


def load_app_paths() -> list[str]:
    # Make the app importable in a stateless way (no Postgres, no persistent disk).
    os.environ.setdefault("LEDGER_ALLOW_EPHEMERAL", "true")
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/cpc_manifest_gen.db")
    os.environ.setdefault("LEDGER_DATA_DIR", "/tmp")

    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Suppress the app's import-time stdout (startup banners) so only JSON is ours.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        from ledger.app.main import app  # noqa: E402

        paths = sorted(app.openapi().get("paths", {}).keys())
    return paths


def main() -> int:
    paths = load_app_paths()
    manifest = {
        "generated_from": "ledger.app.main:app OpenAPI",
        "route_count": len(paths),
        "routes": paths,
        "note": (
            "Source of truth for deploy-drift detection. Regenerate with "
            "scripts/gen_route_manifest.py after intentionally adding/removing routes."
        ),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST} — {len(paths)} routes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
