"""C-347-E: MIC redemption stub tests."""

import os
import sys
import tempfile

import jwt
import pytest
from fastapi.testclient import TestClient

MIC_WALLET_ROOT = os.path.join(os.path.dirname(__file__), "..", "mic-wallet")
sys.path.insert(0, MIC_WALLET_ROOT)

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp(prefix='mic_wallet_redeem_')}/test.db"
os.environ["SECRET_KEY"] = "test-secret-key-for-redeem"

from app import main as wallet_main  # noqa: E402

client = TestClient(wallet_main.app)
SECRET = os.environ["SECRET_KEY"]


def _token(user_id: str = "user-redeem-1", civic_id: str | None = None) -> str:
    return jwt.encode(
        {"user_id": user_id, "civic_id": civic_id or f"mobius-test-{user_id}"},
        SECRET,
        algorithm="HS256",
    )


def _auth_headers(user_id: str = "user-redeem-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _seed_balance(user_id: str, amount: float) -> None:
    sessions = int(amount // 5) + 1
    for _ in range(sessions):
        r = client.post(
            "/mic/earn",
            headers=_auth_headers(user_id),
            json={"source": "oaa_tutor_session_complete"},
        )
        assert r.status_code == 201, r.text


def test_redeem_rejects_unknown_item():
    _seed_balance("user-unknown-item", 15)
    resp = client.post(
        "/mic/redeem",
        headers=_auth_headers("user-unknown-item"),
        json={"item_id": "not-a-real-item"},
    )
    assert resp.status_code == 400


def test_redeem_rejects_insufficient_balance():
    resp = client.post(
        "/mic/redeem",
        headers=_auth_headers("user-poor"),
        json={"item_id": "realm-of-self"},
    )
    assert resp.status_code == 402


def test_redeem_unlocks_realm_and_is_idempotent():
    user = "user-rich"
    for _ in range(3):
        r = client.post(
            "/mic/earn",
            headers=_auth_headers(user),
            json={"source": "oaa_tutor_session_complete"},
        )
        assert r.status_code == 201, r.text

    first = client.post(
        "/mic/redeem",
        headers=_auth_headers(user),
        json={"item_id": "realm-of-self", "idempotency_key": "idem-1"},
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["item_id"] == "realm-of-self"
    assert body["unlock_token"]
    assert body["already_redeemed"] is False
    assert body["new_balance"] == 5.0  # 15 - 10

    second = client.post(
        "/mic/redeem",
        headers=_auth_headers(user),
        json={"item_id": "realm-of-self", "idempotency_key": "idem-1"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["already_redeemed"] is True
    assert second.json()["unlock_token"] == body["unlock_token"]
    assert second.json()["new_balance"] == 5.0

    unlocks = client.get("/mic/unlocks", headers=_auth_headers(user))
    assert unlocks.status_code == 200
    assert "realm-of-self" in unlocks.json()["unlocks"]
