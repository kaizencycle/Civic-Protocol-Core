"""MCP bridge (fastapi-mcp-router) on Civic Ledger API."""

import json
import os

from fastapi.testclient import TestClient

os.environ.setdefault("MOBIUS_MESH_TOKEN", "test-mesh-secret")
os.environ["LEDGER_DATA_DIR"] = "/tmp/ledger_test_mcp"

from ledger.app.main import app  # noqa: E402

client = TestClient(app)
HDR = {"MCP-Protocol-Version": "2025-03-26"}


def _rpc(method: str, params: dict, req_id: int = 1):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
        headers=HDR,
    )


def test_tools_list_six_tools():
    r = _rpc("tools/list", {})
    assert r.status_code == 200
    data = r.json()
    names = [t["name"] for t in data["result"]["tools"]]
    assert len(names) == 6
    assert "get_integrity_snapshot" in names
    assert "post_epicon_entry" in names


def test_post_epicon_gi_gate_blocked(monkeypatch):
    monkeypatch.setenv("GI_STATE_JSON", json.dumps({"global_integrity": 0.5}))
    r = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "post_epicon_entry",
                "arguments": {
                    "title": "Governance title long enough",
                    "category": "governance",
                    "rationale": "Rationale text is definitely long enough here.",
                    "confidence": 0.8,
                },
            },
        },
        headers=HDR,
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    body = json.loads(text)
    assert body["ok"] is False
    assert body["error"] == "gi_gate_blocked"


def test_post_epicon_success_when_gi_high(monkeypatch):
    monkeypatch.setenv("GI_STATE_JSON", json.dumps({"global_integrity": 0.95}))
    r = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "post_epicon_entry",
                "arguments": {
                    "title": "Another governance title here",
                    "category": "governance",
                    "rationale": "Another rationale that is long enough for validation.",
                    "confidence": 0.9,
                },
            },
        },
        headers=HDR,
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    body = json.loads(text)
    assert body["ok"] is True
    assert "entry_id" in body
