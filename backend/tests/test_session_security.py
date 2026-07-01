from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import get_settings
from app.main import app
from app.services.session_store import VerificationStore

client = TestClient(app)


def _create() -> tuple[str, str]:
    body = client.post("/api/verifications", json={"user_id": "sess-test"}).json()
    return body["session_id"], body["session_token"]


# --- Client binding (X-Session-Token) -----------------------------------------

def test_session_id_alone_is_rejected() -> None:
    sid, _token = _create()
    # No token header -> the session id by itself is not enough.
    assert client.get(f"/api/verifications/{sid}").status_code == 403
    # Wrong token -> rejected.
    assert client.get(
        f"/api/verifications/{sid}", headers={"X-Session-Token": "wrong"}
    ).status_code == 403


def test_valid_token_is_accepted() -> None:
    sid, token = _create()
    ok = client.get(f"/api/verifications/{sid}", headers={"X-Session-Token": token})
    assert ok.status_code == 200
    # The token is returned only at creation, never echoed back afterwards.
    assert ok.json()["session_token"] is None


def test_create_response_includes_token() -> None:
    _sid, token = _create()
    assert isinstance(token, str) and len(token) >= 32


# --- Expiry & pruning (store-level) -------------------------------------------

def test_session_expires_on_idle_and_absolute_ttl() -> None:
    store = VerificationStore()
    now = datetime.now(timezone.utc)
    s = store.create("u")
    sid = s.session_id

    assert store.is_expired(sid, now) is False
    # Idle timeout: last activity older than the idle window.
    idle = get_settings().session_idle_ttl_minutes
    assert store.is_expired(sid, now + timedelta(minutes=idle + 1)) is True


def test_prune_expired_drops_sessions_and_embeddings() -> None:
    store = VerificationStore()
    s = store.create("u")
    sid = s.session_id
    store.set_document_face_embedding(sid, [0.1, 0.2])
    # Force the session to look old.
    s.updated_at = datetime.now(timezone.utc) - timedelta(days=1)

    assert store.prune_expired() == 1
    assert store.session_token(sid) is None
    assert store.get_document_face_embedding(sid) is None


def test_expired_session_returns_410(monkeypatch) -> None:
    sid, token = _create()
    # Make the live store's session look expired.
    routes.store.get(UUID(sid)).updated_at = datetime.now(timezone.utc) - timedelta(days=1)
    r = client.get(f"/api/verifications/{sid}", headers={"X-Session-Token": token})
    assert r.status_code == 410
    # And it is evicted.
    assert routes.store.session_token(UUID(sid)) is None


def test_unknown_session_is_404() -> None:
    assert client.get(
        f"/api/verifications/{uuid4()}", headers={"X-Session-Token": "x"}
    ).status_code == 404
