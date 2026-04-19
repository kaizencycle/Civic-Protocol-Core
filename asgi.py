"""
ASGI entrypoint for Render and other hosts where cwd is not the repo root.

Uvicorn loads this module by name; we ensure the repository root is on
sys.path before importing the real FastAPI app.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ledger.app.main import app  # noqa: E402

__all__ = ["app"]
