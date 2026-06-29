from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app

client = TestClient(app)


def test_open_when_no_api_keys_configured(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "api_keys", ())
    r = client.post("/api/verifications", json={"user_id": "open-mode"})
    assert r.status_code == 200


def test_requires_key_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "api_keys", ("key-aaa", "key-bbb"))
    # missing key
    assert client.post("/api/verifications", json={"user_id": "x"}).status_code == 401
    # wrong key
    assert client.post(
        "/api/verifications", json={"user_id": "x"}, headers={"X-API-Key": "nope"}
    ).status_code == 401
    # valid key (either configured key works)
    ok = client.post("/api/verifications", json={"user_id": "x"}, headers={"X-API-Key": "key-bbb"})
    assert ok.status_code == 200


def test_health_is_not_gated(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "api_keys", ("key-aaa",))
    # /health is on the app, not the /api router, so it stays open for probes.
    assert client.get("/health").status_code == 200
