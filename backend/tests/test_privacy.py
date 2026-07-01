from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.config import get_settings
from app.models.schemas import UserProfile, VerificationResult
from app.services.profile_store import FaceProfileRecord, FaceProfileStore


def _store(tmp_path, name="p.sqlite3") -> FaceProfileStore:
    return FaceProfileStore(database_url=f"sqlite:///{tmp_path}/{name}")


def _seed(store: FaceProfileStore, user_id: str, enrolled_at: datetime, last_login_at=None) -> None:
    profile = UserProfile(
        face_id=uuid4(), user_id=user_id, verification_session_id=uuid4(),
        enrolled_at=enrolled_at, last_login_at=last_login_at,
    )
    with store._sessionmaker().begin() as db:
        record = FaceProfileRecord(face_id=str(profile.face_id))
        store._apply_profile(record, profile, [0.1, 0.2], enrolled_at)
        db.add(record)


# --- Consent ------------------------------------------------------------------

def test_consent_recorded_at_enrollment(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "consent_version", "2026-06-v1")
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    result = VerificationResult(session_id=uuid4(), user_id="u1", created_at=now, updated_at=now)

    profile = store._profile_from_result(result, existing_face_id=None, enrolled_at=now)

    # Every enrolled profile carries an auditable consent record (which terms, when).
    assert profile.consent_version == "2026-06-v1"
    assert profile.consented_at == now


def test_consent_persisted_and_readable(tmp_path) -> None:
    store = _store(tmp_path, "c.sqlite3")
    now = datetime.now(timezone.utc)
    profile = UserProfile(
        face_id=uuid4(), user_id="u2", verification_session_id=uuid4(),
        enrolled_at=now, consent_version="2026-06-v1", consented_at=now,
    )
    record = FaceProfileRecord(face_id=str(profile.face_id))
    store._apply_profile(record, profile, [0.1], now)

    read = store._record_to_dict(record)
    assert read["consent_version"] == "2026-06-v1"
    assert read["consented_at"] == now


# --- Retention (auto-purge) ---------------------------------------------------

def test_purge_removes_stale_keeps_recent(tmp_path) -> None:
    store = _store(tmp_path, "r.sqlite3")
    now = datetime.now(timezone.utc)
    _seed(store, "stale", enrolled_at=now - timedelta(days=400))
    _seed(store, "recent", enrolled_at=now - timedelta(days=10))
    # Enrolled long ago but used recently -> kept (last activity wins).
    _seed(store, "active", enrolled_at=now - timedelta(days=400), last_login_at=now - timedelta(days=5))

    deleted = store.purge_expired_profiles(retention_days=365, now=now)

    assert deleted == 1
    remaining = sorted(p.user_id for p in store.list_profiles())
    assert remaining == ["active", "recent"]


def test_purge_disabled_is_noop(tmp_path) -> None:
    store = _store(tmp_path, "n.sqlite3")
    now = datetime.now(timezone.utc)
    _seed(store, "old", enrolled_at=now - timedelta(days=9999))

    assert store.purge_expired_profiles(retention_days=0, now=now) == 0
    assert len(store.list_profiles()) == 1


# --- Deletion (erasure workflow) ---------------------------------------------

def test_delete_user_erases_profile(tmp_path) -> None:
    store = _store(tmp_path, "d.sqlite3")
    now = datetime.now(timezone.utc)
    _seed(store, "erase-me", enrolled_at=now)

    assert store.delete_user("erase-me") == 1
    assert store.list_profiles() == []
