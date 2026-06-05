"""Tests for OPT-6 IdentityTokenClient."""

import base64
import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from sdk.python.identity_client import IdentityTokenClient, _jwt_exp_unix


def _make_jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": exp, "user_id": "u1"}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def test_jwt_exp_unix_decodes_exp():
    exp = int(time.time()) + 3600
    token = _make_jwt(exp)
    assert _jwt_exp_unix(token) == exp


def test_jwt_exp_unix_invalid_returns_none():
    assert _jwt_exp_unix("not-a-jwt") is None


def test_get_token_logs_in_when_cache_empty():
    client = IdentityTokenClient("https://identity.test", "svc@test.io", "secret")
    exp = int(time.time()) + 86_400
    token = _make_jwt(exp)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "access_token": token,
        "token_type": "bearer",
        "user": {"civic_id": "civic::abc"},
    }

    with patch("sdk.python.identity_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        assert client.get_token() == token
        mock_client.post.assert_called_once_with(
            "https://identity.test/auth/login",
            json={"email": "svc@test.io", "password": "secret"},
        )


def test_get_token_reuses_cache_when_not_near_expiry():
    client = IdentityTokenClient(
        "https://identity.test", "svc@test.io", "secret", refresh_margin_seconds=3600
    )
    exp = int(time.time()) + 86_400
    token = _make_jwt(exp)
    client._token = token
    client._expires_at = exp

    with patch("sdk.python.identity_client.httpx.Client") as mock_client_cls:
        assert client.get_token() == token
        mock_client_cls.assert_not_called()


def test_attest_retries_on_401_with_force_refresh():
    client = IdentityTokenClient("https://identity.test", "svc@test.io", "secret")
    exp = int(time.time()) + 86_400
    token = _make_jwt(exp)

    login_response = MagicMock()
    login_response.raise_for_status = MagicMock()
    login_response.json.return_value = {"access_token": token, "token_type": "bearer", "user": {}}

    fail_response = MagicMock()
    fail_response.status_code = 401
    fail_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unauthorized", request=MagicMock(), response=fail_response
    )

    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.raise_for_status = MagicMock()
    ok_response.json.return_value = {"event_id": "e1", "event_hash": "abc", "confirmed": True}

    with patch("sdk.python.identity_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = [login_response, fail_response, login_response, ok_response]
        mock_client_cls.return_value = mock_client

        # First attest: login + 401; retry path calls login again + 200
        with patch.object(client, "attest", wraps=client.attest):
            result = client.attest(
                "https://ledger.test",
                event_type="seal.immortalize",
                civic_id="mobius-civic-ai-terminal",
                payload={"seal_id": "s1"},
            )
        assert result["event_hash"] == "abc"


def test_from_env_missing_raises():
    with patch.dict("os.environ", {}, clear=True), pytest.raises(ValueError, match="IDENTITY_API_BASE"):
        IdentityTokenClient.from_env()
