"""C-332 OPT-8: devnode CORS allowlist behavior."""
import importlib.util
from pathlib import Path

DEVNODE_PATH = Path(__file__).resolve().parents[1] / "sdk" / "python" / "devnode.py"


def _load_devnode(monkeypatch, env_value: str | None):
    if env_value is None:
        monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", env_value)
    spec = importlib.util.spec_from_file_location("devnode_c332", DEVNODE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cors_allow_origin_wildcard_when_unset(monkeypatch):
    mod = _load_devnode(monkeypatch, None)
    assert mod.cors_allow_origin(None) == "*"
    assert mod.cors_allow_origin("https://evil.example") == "*"


def test_cors_allow_origin_reflects_allowlist(monkeypatch):
    mod = _load_devnode(monkeypatch, "https://a.app,https://b.app")
    assert mod.cors_allow_origin("https://b.app") == "https://b.app"
    assert mod.cors_allow_origin("https://unknown.app") == "https://a.app"
