from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.models.schemas import UserProfile

client = TestClient(app)

FILE = {"file": ("selfie.jpg", b"\xff\xd8\xff\xe0dummy", "image/jpeg")}


def _profile(user_id: str = "alice") -> UserProfile:
    return UserProfile(
        face_id=uuid4(), user_id=user_id, verification_session_id=uuid4(),
        full_name="Alice Example", passport_number="PA0000001", nationality="LAO",
        enrolled_at=datetime.now(timezone.utc), consent_version="2026-06-v1",
    )


def _stub_owner(monkeypatch, profile, reason_codes=None, score=0.9):
    async def fake(content):
        return profile, reason_codes or [], score
    monkeypatch.setattr(routes, "_authenticate_face_owner", fake)


# --- Consent ------------------------------------------------------------------

def test_consent_endpoint_returns_version_and_notice() -> None:
    r = client.get("/api/consent")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == routes.settings.consent_version
    assert "biometric" in body["notice"].lower() and len(body["notice"]) > 40


# --- Self-service export (data access / portability) --------------------------

def test_export_returns_own_profile_when_face_verified(monkeypatch) -> None:
    _stub_owner(monkeypatch, _profile("alice"))
    r = client.post("/api/self-service/export", files=FILE)
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True
    # The owner gets their FULL data back (unredacted) — it's their own DSAR.
    assert body["profile"]["user_id"] == "alice"
    assert body["profile"]["passport_number"] == "PA0000001"


def test_export_denied_when_no_face_match(monkeypatch) -> None:
    _stub_owner(monkeypatch, None, reason_codes=["NO_MATCH"], score=0.2)
    r = client.post("/api/self-service/export", files=FILE)
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is False and body["profile"] is None
    assert "NO_MATCH" in body["reason_codes"]


# --- Self-service erasure (right to be forgotten) -----------------------------

def test_delete_erases_own_profile_when_verified(monkeypatch) -> None:
    _stub_owner(monkeypatch, _profile("bob"))
    monkeypatch.setattr(routes.profile_store, "delete_user", lambda uid: 1)
    r = client.post("/api/self-service/delete", files=FILE)
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True and body["deleted"] is True and body["user_id"] == "bob"


def test_delete_denied_when_not_verified(monkeypatch) -> None:
    _stub_owner(monkeypatch, None, reason_codes=["LIVENESS_FAILED"])
    called = {"n": 0}
    monkeypatch.setattr(routes.profile_store, "delete_user", lambda uid: called.__setitem__("n", called["n"] + 1) or 1)
    r = client.post("/api/self-service/delete", files=FILE)
    body = r.json()
    assert body["verified"] is False and body["deleted"] is False
    assert called["n"] == 0  # nothing is deleted without a verified owner
