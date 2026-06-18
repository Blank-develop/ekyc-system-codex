from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app

client = TestClient(app)


def test_profiles_disabled_when_no_token(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "admin_api_token", "")
    assert client.get("/api/profiles").status_code == 403
    assert client.delete("/api/profiles").status_code == 403
    assert client.delete("/api/profiles/some-user").status_code == 403


def test_profiles_require_matching_token(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "admin_api_token", "s3cret-token")
    assert client.get("/api/profiles").status_code == 401  # missing header
    assert client.get("/api/profiles", headers={"X-Admin-Token": "wrong"}).status_code == 401
    ok = client.get("/api/profiles", headers={"X-Admin-Token": "s3cret-token"})
    assert ok.status_code == 200
    assert "profiles" in ok.json()
