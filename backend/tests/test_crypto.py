from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from cryptography.fernet import Fernet

from app.services import crypto as crypto_mod
from app.services.crypto import PREFIX, TemplateCipher


def test_cipher_roundtrip_with_key() -> None:
    cipher = TemplateCipher(Fernet.generate_key().decode())
    assert cipher.enabled
    enc = cipher.encrypt_template([0.1, 0.2, -0.3])
    assert isinstance(enc, str) and enc.startswith(PREFIX)
    assert cipher.decrypt_template(enc) == [0.1, 0.2, -0.3]


def test_cipher_noop_without_key() -> None:
    cipher = TemplateCipher("")
    assert not cipher.enabled
    assert cipher.encrypt_template([0.5, 0.6]) == [0.5, 0.6]
    assert cipher.decrypt_template([0.5, 0.6]) == [0.5, 0.6]  # legacy plaintext still readable


def test_decrypt_fails_safe_on_wrong_or_missing_key() -> None:
    enc = TemplateCipher(Fernet.generate_key().decode()).encrypt_template([1.0, 2.0])
    assert TemplateCipher(Fernet.generate_key().decode()).decrypt_template(enc) is None  # wrong key
    assert TemplateCipher("").decrypt_template(enc) is None  # no key


def test_template_encrypted_at_rest_and_decrypts(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.models.schemas import UserProfile
    from app.services.profile_store import FaceProfileRecord, FaceProfileStore

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "encryption_key", key)
    crypto_mod.get_template_cipher.cache_clear()
    try:
        store = FaceProfileStore(database_url=f"sqlite:///{tmp_path}/t.sqlite3")
        profile = UserProfile(
            face_id=uuid4(),
            user_id="u1",
            verification_session_id=uuid4(),
            enrolled_at=datetime.now(timezone.utc),
        )
        record = FaceProfileRecord(face_id=str(profile.face_id))
        store._apply_profile(record, profile, [0.11, 0.22, -0.33], datetime.now(timezone.utc))

        # Stored on the record as an opaque encrypted string, not the raw embedding.
        assert isinstance(record.face_template, str)
        assert record.face_template.startswith(PREFIX)
        assert "0.11" not in record.face_template

        # Reading it back decrypts to the original embedding for matching.
        assert store._record_to_dict(record)["face_template"] == [0.11, 0.22, -0.33]
    finally:
        crypto_mod.get_template_cipher.cache_clear()


def test_blind_index_deterministic_for_uniqueness() -> None:
    cipher = TemplateCipher(Fernet.generate_key().decode())
    a = cipher.blind_index("PA0377243")
    b = cipher.blind_index("  pa0377243 ")  # normalised (strip + upper)
    assert a is not None and a == b
    assert cipher.blind_index("PA9999999") != a
    assert TemplateCipher("").blind_index("PA0377243") is None


def test_pii_encrypted_at_rest_and_recovered(tmp_path, monkeypatch) -> None:
    from datetime import date

    from app.core.config import get_settings
    from app.models.schemas import UserProfile
    from app.services.profile_store import FaceProfileRecord, FaceProfileStore

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "encryption_key", key)
    crypto_mod.get_template_cipher.cache_clear()
    try:
        store = FaceProfileStore(database_url=f"sqlite:///{tmp_path}/pii.sqlite3")
        profile = UserProfile(
            face_id=uuid4(), user_id="u1", verification_session_id=uuid4(),
            full_name="CHILANHOUTH NITVONGKHAY", first_name="Chilanhouth", last_name="Nitvongkhay",
            age=24, date_of_birth=date(2001, 11, 9), nationality="LAO",
            passport_number="PA0377243", passport_expiry=date(2032, 3, 14),
            enrolled_at=datetime.now(timezone.utc),
        )
        rec = FaceProfileRecord(face_id=str(profile.face_id))
        store._apply_profile(rec, profile, [0.1, 0.2], datetime.now(timezone.utc))

        # Plaintext PII columns nulled; values encrypted in the blob; no cleartext PII visible.
        assert rec.passport_number is None and rec.full_name is None and rec.date_of_birth is None
        assert rec.pii_encrypted and rec.pii_encrypted.startswith(PREFIX)
        assert "PA0377243" not in rec.pii_encrypted and "NITVONGKHAY" not in rec.pii_encrypted
        assert rec.passport_number_bidx and rec.passport_number_bidx != "PA0377243"

        # Recovered through the read path.
        recovered = store._public_profile(store._record_to_dict(rec))
        assert recovered.passport_number == "PA0377243"
        assert recovered.full_name == "CHILANHOUTH NITVONGKHAY"
        assert recovered.date_of_birth == date(2001, 11, 9)
        assert recovered.nationality == "LAO"
    finally:
        crypto_mod.get_template_cipher.cache_clear()
