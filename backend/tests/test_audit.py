from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.services.audit import AuditEvent, AuditLog

client = TestClient(app)


def _log(tmp_path, name="audit.sqlite3") -> AuditLog:
    return AuditLog(database_url=f"sqlite:///{tmp_path}/{name}")


def test_records_are_hash_chained(tmp_path) -> None:
    log = _log(tmp_path)
    log.record("auth", "login", actor="alice", detail={"success": True})
    log.record("pii_access", "list_profiles", actor="10.0.0.1", detail={"count": 3})
    log.record("erasure", "delete_profile", actor="10.0.0.1", subject="user-9")

    events = log.list_events()
    assert len(events) == 3
    # Newest first; each stored entry links to the previous one (verified below).
    assert [e["action"] for e in events] == ["delete_profile", "list_profiles", "login"]
    assert log.verify_chain() == {"ok": True, "entries": 3, "broken_at": None}


def test_verify_detects_tampering(tmp_path) -> None:
    log = _log(tmp_path, "tamper.sqlite3")
    log.record("auth", "login", actor="alice")
    log.record("auth", "login", actor="bob")
    log.record("auth", "login", actor="carol")

    # Tamper with the middle row's content without recomputing the chain.
    with log._Session.begin() as db:
        row = db.query(AuditEvent).filter(AuditEvent.actor == "bob").one()
        row.actor = "attacker"

    result = log.verify_chain()
    assert result["ok"] is False
    assert result["broken_at"] is not None


def test_deleting_a_row_breaks_the_chain(tmp_path) -> None:
    log = _log(tmp_path, "delete.sqlite3")
    for name in ("a", "b", "c"):
        log.record("auth", "login", actor=name)
    with log._Session.begin() as db:
        db.query(AuditEvent).filter(AuditEvent.actor == "b").delete()

    assert log.verify_chain()["ok"] is False


def test_keyed_chain_differs_from_unkeyed(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings

    unkeyed = _log(tmp_path, "plain.sqlite3")
    unkeyed.record("auth", "login", actor="alice")
    plain_hash = unkeyed.list_events()[0]["entry_hash"]

    monkeypatch.setattr(get_settings(), "encryption_key", "unit-test-key")
    keyed = _log(tmp_path, "keyed.sqlite3")
    keyed.record("auth", "login", actor="alice")
    keyed_hash = keyed.list_events()[0]["entry_hash"]

    assert keyed._hmac_key is not None
    assert keyed_hash != plain_hash  # same event, different (keyed) digest


def test_disabled_is_noop(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "audit_log_enabled", False)
    log = _log(tmp_path, "off.sqlite3")
    log.record("auth", "login", actor="alice")
    assert log.list_events() == []


# --- Endpoints ---------------------------------------------------------------

def test_audit_endpoints_require_admin(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "admin_api_token", "")
    monkeypatch.setattr(routes.settings, "jwt_secret", "")
    assert client.get("/api/audit").status_code == 403
    assert client.get("/api/audit/verify").status_code == 403


def test_audit_endpoints_work_with_admin_token(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "admin_api_token", "s3cret")
    headers = {"X-Admin-Token": "s3cret"}
    listing = client.get("/api/audit", headers=headers)
    assert listing.status_code == 200 and "events" in listing.json()
    verify = client.get("/api/audit/verify", headers=headers)
    assert verify.status_code == 200 and verify.json()["ok"] is True
