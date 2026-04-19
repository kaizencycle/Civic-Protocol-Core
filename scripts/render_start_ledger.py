#!/usr/bin/env python3
"""
Civic Ledger — Render / uvicorn entrypoint.

Render (and some shells) may use a cwd that is not the git root, which breaks
`import ledger`. We chdir to the repo root and prepend it to sys.path, then
start uvicorn with a string app ref so the import runs after path setup.

Dashboard override: if the service still runs `uvicorn ledger.app.main:app`
directly, change Start Command to:

  python3 scripts/render_start_ledger.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    os.chdir(_ROOT)
    rp = str(_ROOT)
    if rp not in sys.path:
        sys.path.insert(0, rp)

    port = int(os.environ.get("PORT", "8000"))
    import uvicorn

    uvicorn.run(
        "ledger.app.main:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
