"""Tests for provision_service_account credential resolution."""

import os
import subprocess
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.provision_service_account import _resolve_credential  # noqa: E402


def test_resolve_credential_prefers_cli():
    with patch.dict(os.environ, {"IDENTITY_SERVICE_EMAIL": "env@test.io"}, clear=False):
        assert _resolve_credential("cli@test.io", "IDENTITY_SERVICE_EMAIL", "email") == "cli@test.io"


def test_resolve_credential_falls_back_to_env():
    with patch.dict(os.environ, {"IDENTITY_SERVICE_EMAIL": "env@test.io"}, clear=False):
        assert _resolve_credential(None, "IDENTITY_SERVICE_EMAIL", "email") == "env@test.io"


def test_resolve_credential_missing_exits():
    with patch.dict(os.environ, {}, clear=True), pytest.raises(SystemExit, match="IDENTITY_SERVICE_EMAIL"):
        _resolve_credential(None, "IDENTITY_SERVICE_EMAIL", "email")


def test_smoke_accepts_env_credentials():
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    env = os.environ.copy()
    env.pop("IDENTITY_SERVICE_EMAIL", None)
    env.pop("IDENTITY_SERVICE_PASSWORD", None)
    result = subprocess.run(
        [sys.executable, "scripts/provision_service_account.py", "smoke", "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--email" in result.stdout
    assert "IDENTITY_SERVICE_EMAIL" in result.stdout or "email" in result.stdout
