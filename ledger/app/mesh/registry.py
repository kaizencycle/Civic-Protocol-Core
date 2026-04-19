"""Load and cache Mobius-Substrate mesh/registry.json."""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

REGISTRY_URL = os.getenv(
    "MOBIUS_MESH_REGISTRY_URL",
    "https://raw.githubusercontent.com/kaizencycle/Mobius-Substrate/main/mesh/registry.json",
)
CACHE_PATH = os.getenv("MNS_REGISTRY_CACHE_PATH", "/tmp/mns_registry_cache.json")
CACHE_AGE_SEC = int(os.getenv("MNS_REGISTRY_CACHE_SECONDS", "3600"))


def _read_cache_file(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_mesh_registry() -> Tuple[Dict[str, Any], bool]:
    """
    Return (registry dict, fetch_ok).

    fetch_ok is True when registry came from a successful HTTP fetch or a
    non-stale cache of a prior successful fetch. False when falling back to
    empty nodes after a fetch failure (ingest should not hard-fail registered
    nodes in that case).
    """
    if os.path.exists(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < CACHE_AGE_SEC:
            try:
                data = _read_cache_file(CACHE_PATH)
                return data, True
            except (OSError, json.JSONDecodeError):
                pass

    try:
        req = urllib.request.Request(
            REGISTRY_URL,
            headers={"User-Agent": "civic-protocol-core-mns/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            registry = json.loads(response.read().decode("utf-8"))
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f)
        return registry, True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        if os.path.exists(CACHE_PATH):
            try:
                return _read_cache_file(CACHE_PATH), True
            except (OSError, json.JSONDecodeError):
                pass
        return {"nodes": []}, False


def registry_cache_mtime_iso() -> Optional[str]:
    if not os.path.exists(CACHE_PATH):
        return None
    return datetime.fromtimestamp(
        os.path.getmtime(CACHE_PATH), tz=timezone.utc
    ).isoformat()
