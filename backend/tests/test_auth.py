from __future__ import annotations

import secrets

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.services import auth as auth_service

client = TestClient(app)

SECRET = "test-jwt-secret-0123456789"


def _seed_admin(monkeypatch, username="admin", password="pw", role="admin"):
    monkeypatch.setattr(routes.settings, "jwt_secret", SECRET)
    monkeypatch.setattr(routes.settings, "jwt_expire_minutes", 60)
    entry = f"{username}:{auth_service.hash_password(password)}:{role}"
    monkeypatch.setattr(routes.settings, "auth_users", (entry,))


# --- Auth service units -------------------------------------------------------

def test_password_hash_roundtrip() -> None:
    h = auth_service.hash_password("correct horse")
    assert h.startswith("pbkdf2_sha256$")
    assert auth_service.verify_password("correct horse", h)
    assert not auth_service.verify_password("wrong", h)


def test_jwt_roundtrip_and_tamper_detection() -> None:
    token = auth_service.create_access_token(SECRET, "alice", "admin", 60)
    claims = auth_service.decode_token(SECRET, token)
    assert claims and claims["sub"] == "alice" and claims["role"] == "admin"
    assert auth_service.decode_token("other-secret", token) is None  # wrong key
    assert auth_service.decode_token(SECRET, token + "x") is None  # tampered


def test_jwt_rejects_expired() -> None:
    token = auth_service.create_access_token(SECRET, "bob", "user", -1)  # already expired
    assert auth_service.decode_token(SECRET, token) is None


def test_load_users_parses_hash_with_dollar_separators() -> None:
    h = auth_service.hash_password("x")
    users = auth_service.load_users((f"admin:{h}:admin", "bad-entry"))
    assert set(users) == {"admin"}
    assert users["admin"].role == "admin" and users["admin"].password_hash == h


# --- Token endpoint -----------------------------------------------------------

def test_token_endpoint_issues_jwt(monkeypatch) -> None:
    _seed_admin(monkeypatch)
    resp = client.post("/api/auth/token", data={"username": "admin", "password": "pw"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer" and body["role"] == "admin"
    assert auth_service.decode_token(SECRET, body["access_token"])["sub"] == "admin"


def test_token_endpoint_rejects_bad_password(monkeypatch) -> None:
    _seed_admin(monkeypatch)
    assert client.post("/api/auth/token", data={"username": "admin", "password": "nope"}).status_code == 401


def test_token_endpoint_503_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "jwt_secret", "")
    assert client.post("/api/auth/token", data={"username": "a", "password": "b"}).status_code == 503


# --- /auth/me -----------------------------------------------------------------

def test_me_requires_valid_bearer(monkeypatch) -> None:
    _seed_admin(monkeypatch)
    assert client.get("/api/auth/me").status_code == 401
    token = auth_service.create_access_token(SECRET, "admin", "admin", 60)
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json() == {"username": "admin", "role": "admin"}


# --- Admin endpoints via JWT --------------------------------------------------

def test_admin_endpoint_accepts_admin_jwt(monkeypatch) -> None:
    _seed_admin(monkeypatch)
    monkeypatch.setattr(routes.settings, "admin_api_token", "")  # no static token
    token = auth_service.create_access_token(SECRET, "admin", "admin", 60)
    ok = client.get("/api/profiles", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200 and "profiles" in ok.json()


def test_admin_endpoint_rejects_non_admin_role(monkeypatch) -> None:
    _seed_admin(monkeypatch)
    monkeypatch.setattr(routes.settings, "admin_api_token", "")
    token = auth_service.create_access_token(SECRET, "joe", "operator", 60)
    assert client.get("/api/profiles", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_admin_static_token_still_works_alongside_jwt(monkeypatch) -> None:
    _seed_admin(monkeypatch)
    monkeypatch.setattr(routes.settings, "admin_api_token", "s3cret")
    assert client.get("/api/profiles", headers={"X-Admin-Token": "s3cret"}).status_code == 200
    assert client.get("/api/profiles", headers={"X-Admin-Token": "wrong"}).status_code == 401
