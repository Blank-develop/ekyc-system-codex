from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from app.api.routes import _mask_document_number, _redact_profile
from app.models.schemas import UserProfile


def _profile() -> UserProfile:
    return UserProfile(
        face_id=uuid4(),
        user_id="user-123",
        verification_session_id=uuid4(),
        full_name="CHILANHOUTH NITVONGKHAY",
        first_name="Chilanhouth",
        last_name="Nitvongkhay",
        age=24,
        date_of_birth=date(2001, 11, 9),
        nationality="LAO",
        passport_number="PA0377243",
        passport_expiry=date(2032, 3, 14),
        enrolled_at=datetime(2026, 5, 11, 4, 3, 1),
    )


def test_mask_document_number() -> None:
    assert _mask_document_number("PA0377243") == "PA•••••43"
    assert _mask_document_number("AB12") == "••••"
    assert _mask_document_number(None) is None


def test_redact_profile_drops_sensitive_pii() -> None:
    redacted = _redact_profile(_profile())
    # Sensitive identity fields removed
    assert redacted.full_name is None
    assert redacted.last_name is None
    assert redacted.date_of_birth is None
    assert redacted.passport_expiry is None
    # Document number masked, not exposed in full
    assert redacted.passport_number == "PA•••••43"
    assert "0377" not in (redacted.passport_number or "")
    # Greeting fields kept for the returning-user UX
    assert redacted.first_name == "Chilanhouth"
    assert redacted.nationality == "LAO"
    assert redacted.age == 24
