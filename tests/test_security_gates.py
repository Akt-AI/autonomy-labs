import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.server import create_app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "dummy")
    monkeypatch.setenv("ENABLE_TERMINAL", "1")
    monkeypatch.setenv("ENABLE_CODEX", "1")
    monkeypatch.setenv("ENABLE_MCP", "1")
    app = create_app()
    return TestClient(app)


def test_codex_login_status_requires_auth(client: TestClient):
    res = client.get("/api/codex/login/status")
    assert res.status_code == 401


def test_mcp_tools_requires_auth(client: TestClient):
    res = client.get("/api/mcp/tools")
    assert res.status_code == 401


def test_terminal_ws_requires_token(client: TestClient):
    with client.websocket_connect("/ws/terminal") as ws:
        # Server accepts then sends an error + closes.
        try:
            msg = ws.receive_text()
        except WebSocketDisconnect:
            msg = ""
        assert "unauthorized" in msg.lower() or msg == ""


def test_features_can_be_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "dummy")
    monkeypatch.setenv("ENABLE_CODEX", "0")
    app = create_app()
    c = TestClient(app)

    res = c.get("/api/codex/login/status")
    assert res.status_code == 403

