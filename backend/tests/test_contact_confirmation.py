from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import get_settings
from app.main import app
from app.services.session_store import VerificationStore

client = TestClient(app)


def _create() -> tuple[str, dict]:
    body = client.post("/api/verifications", json={"user_id": "contact-test"}).json()
    return body["session_id"], {"X-Session-Token": body["session_token"]}


# --- Endpoint flow ------------------------------------------------------------

def test_request_then_confirm_marks_contact_confirmed(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "notifier_echo_code", True)
    sid, headers = _create()

    req = client.post(f"/api/verifications/{sid}/contact/request",
                      json={"channel": "email", "destination": "alice@example.com"}, headers=headers)
    assert req.status_code == 200
    body = req.json()
    assert body["sent"] is True
    assert body["destination_masked"] == "a***@example.com"
    code = body["debug_code"]
    assert code and len(code) == 6

    conf = client.post(f"/api/verifications/{sid}/contact/confirm",
                       json={"code": code}, headers=headers)
    assert conf.status_code == 200
    assert conf.json()["contact_confirmed"] is True


def test_wrong_code_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "notifier_echo_code", True)
    sid, headers = _create()
    client.post(f"/api/verifications/{sid}/contact/request",
                json={"channel": "sms", "destination": "+8562012345678"}, headers=headers)
    bad = client.post(f"/api/verifications/{sid}/contact/confirm",
                      json={"code": "000000"}, headers=headers)
    assert bad.status_code == 400


def test_confirm_without_a_challenge_is_rejected() -> None:
    sid, headers = _create()
    r = client.post(f"/api/verifications/{sid}/contact/confirm",
                    json={"code": "123456"}, headers=headers)
    assert r.status_code == 400


def test_contact_request_requires_session_token() -> None:
    sid, _headers = _create()
    # No X-Session-Token -> session binding rejects it.
    assert client.post(f"/api/verifications/{sid}/contact/request",
                       json={"channel": "email", "destination": "x@y.com"}).status_code == 403


# --- Store logic: expiry, attempts, and the decision gate ---------------------

def test_code_expires() -> None:
    store = VerificationStore()
    s = store.create("u")
    now = datetime.now(timezone.utc)
    store.set_contact_challenge(s.session_id, "email", "a@b.com", "123456", 10, now=now)
    ok, reason = store.verify_contact_code(s.session_id, "123456", 5, now=now + timedelta(minutes=11))
    assert ok is False and reason == "CODE_EXPIRED"


def test_too_many_attempts_locks_out() -> None:
    store = VerificationStore()
    s = store.create("u")
    store.set_contact_challenge(s.session_id, "email", "a@b.com", "123456", 10)
    assert store.verify_contact_code(s.session_id, "999999", 2)[1] == "CODE_INVALID"
    assert store.verify_contact_code(s.session_id, "999999", 2)[1] == "CODE_INVALID"
    assert store.verify_contact_code(s.session_id, "123456", 2)[1] == "TOO_MANY_ATTEMPTS"


def test_decision_requires_contact_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "require_contact_confirmation", True)
    store = VerificationStore()
    s = store.create("u")

    assert "CONTACT_CONFIRMATION_REQUIRED" in store.reevaluate(s.session_id).reason_codes

    store.set_contact_challenge(s.session_id, "email", "a@b.com", "123456", 10)
    ok, _ = store.verify_contact_code(s.session_id, "123456", 5)
    assert ok is True
    assert "CONTACT_CONFIRMATION_REQUIRED" not in store.reevaluate(s.session_id).reason_codes


def test_reconfirming_a_used_code_fails_gracefully() -> None:
    store = VerificationStore()
    s = store.create("u")
    store.set_contact_challenge(s.session_id, "email", "a@b.com", "123456", 10)
    assert store.verify_contact_code(s.session_id, "123456", 5)[0] is True
    # Second attempt after the code is consumed must not raise (regression).
    ok, reason = store.verify_contact_code(s.session_id, "123456", 5)
    assert ok is False and reason == "CODE_ALREADY_USED"


def test_decision_ignores_contact_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "require_contact_confirmation", False)
    store = VerificationStore()
    s = store.create("u")
    assert "CONTACT_CONFIRMATION_REQUIRED" not in store.reevaluate(s.session_id).reason_codes
