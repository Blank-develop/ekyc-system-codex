from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.models.schemas import BiometricAnalysis, DocumentAnalysis, OcrResult, VerificationResult
from app.services.attempt_store import AttemptStore

client = TestClient(app)


def _result(session_id=None, user_id="alice", decision="pending", doc_status="pending",
            active_liveness=False, hand=False, passive=False, face_score=0.0, doc_type="passport") -> VerificationResult:
    now = datetime.now(timezone.utc)
    return VerificationResult(
        session_id=session_id or uuid4(), user_id=user_id, created_at=now, updated_at=now,
        decision=decision, reason_codes=["DOCUMENT_REQUIRED"] if decision == "pending" else [],
        document=DocumentAnalysis(status=doc_status, fraud_risk_score=0.1, ocr=OcrResult(document_type=doc_type)),
        biometric=BiometricAnalysis(active_liveness_passed=active_liveness, hand_challenge_passed=hand,
                                    passive_liveness_passed=passive, face_match_score=face_score),
    )


def _store(name="attempts.sqlite3", tmp_path=None) -> AttemptStore:
    return AttemptStore(database_url=f"sqlite:///{tmp_path}/{name}")


# --- Store unit tests ----------------------------------------------------------

def test_record_upserts_by_session_id(tmp_path) -> None:
    store = _store(tmp_path=tmp_path)
    sid = uuid4()
    store.record(_result(sid, decision="pending"), client_ip="10.0.0.1")
    store.record(_result(sid, decision="passed", active_liveness=True, hand=True, passive=True, face_score=0.9), client_ip="10.0.0.1")

    attempts, total = store.list_attempts()
    assert total == 1
    assert attempts[0]["decision"] == "passed"
    assert attempts[0]["step_count"] == 2  # two record() calls on the same session
    assert attempts[0]["face_match_score"] == 0.9


def test_summary_counts_by_decision(tmp_path) -> None:
    store = _store(tmp_path=tmp_path)
    store.record(_result(decision="passed"))
    store.record(_result(decision="passed"))
    store.record(_result(decision="pending"))
    store.record(_result(decision="rejected"))

    summary = store.summary()
    assert summary == {"total": 4, "passed": 2, "pending": 1, "rejected": 1}


def test_list_attempts_filters_by_decision_and_user(tmp_path) -> None:
    store = _store(tmp_path=tmp_path)
    store.record(_result(user_id="alice", decision="passed"))
    store.record(_result(user_id="bob", decision="rejected"))

    only_passed, total_passed = store.list_attempts(decision="passed")
    assert total_passed == 1 and only_passed[0]["user_id"] == "alice"

    only_bob, total_bob = store.list_attempts(user_id="bob")
    assert total_bob == 1 and only_bob[0]["decision"] == "rejected"


def test_purge_older_than_removes_stale_keeps_recent(tmp_path) -> None:
    store = _store(tmp_path=tmp_path)
    now = datetime.now(timezone.utc)
    old = _result(decision="passed")
    store.record(old)
    # Force this row's updated_at into the past.
    with store._Session.begin() as db:
        from app.services.attempt_store import VerificationAttemptRecord
        row = db.get(VerificationAttemptRecord, str(old.session_id))
        row.updated_at = now - timedelta(days=100)
    store.record(_result(decision="passed"))  # recent

    deleted = store.purge_older_than(30, now=now)
    assert deleted == 1
    _, total = store.list_attempts()
    assert total == 1


def test_purge_disabled_is_noop(tmp_path) -> None:
    store = _store(tmp_path=tmp_path)
    store.record(_result())
    assert store.purge_older_than(0) == 0


def test_record_never_raises_on_bad_input(tmp_path) -> None:
    store = _store(tmp_path=tmp_path)
    store.record(None)  # type: ignore[arg-type]  # fail-open: must not raise


# --- Endpoints (admin-gated) ---------------------------------------------------

def test_attempts_endpoint_requires_admin(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "admin_api_token", "")
    monkeypatch.setattr(routes.settings, "jwt_secret", "")
    assert client.get("/api/attempts").status_code == 403
    assert client.get("/api/admin/overview").status_code == 403


def test_attempts_and_overview_endpoints_work_with_admin_token(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "admin_api_token", "s3cret")
    headers = {"X-Admin-Token": "s3cret"}

    created = client.post("/api/verifications", json={"user_id": "attempt-endpoint-test"}).json()
    sid = created["session_id"]

    listing = client.get("/api/attempts", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] >= 1
    assert any(a["session_id"] == sid for a in body["attempts"])

    overview = client.get("/api/admin/overview", headers=headers)
    assert overview.status_code == 200
    ov = overview.json()
    assert "attempts" in ov and "enrolled_face_ids" in ov and "audit_chain_ok" in ov


def test_purge_expired_attempts_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "admin_api_token", "s3cret")
    r = client.post("/api/attempts/purge-expired", headers={"X-Admin-Token": "s3cret"})
    assert r.status_code == 200
    assert "deleted_count" in r.json()
