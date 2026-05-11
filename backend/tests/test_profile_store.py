from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from app.models.schemas import Decision, DocumentAnalysis, OcrResult, VerificationResult
from app.services.profile_store import FaceProfileStore


def test_enroll_stores_verified_profile_and_matches_returning_face(tmp_path) -> None:
    store = FaceProfileStore(tmp_path / "profiles.json")
    result = VerificationResult(
        session_id=uuid4(),
        user_id="user-savath",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        decision=Decision.passed,
        document=DocumentAnalysis(
            status="passed",
            ocr=OcrResult(
                full_name="SAVATH SAYPADITH",
                passport_number="PA0178358",
                nationality="LAO",
                date_of_birth=date(1994, 8, 29),
                expiry_date=date(2027, 8, 16),
            ),
        ),
    )

    profile = store.enroll(result, [1.0, 0.0, 0.0])
    match = store.match([0.9, 0.1, 0.0], lambda stored, probe: 0.93, threshold=0.72)

    assert profile.first_name == "Savath"
    assert profile.last_name == "Saypadith"
    assert profile.user_id == "user-savath"
    assert profile.nationality == "LAO"
    assert match.profile is not None
    assert match.profile.face_id == profile.face_id
    assert match.score == 0.93


def test_match_returns_none_below_threshold(tmp_path) -> None:
    store = FaceProfileStore(tmp_path / "profiles.json")
    result = VerificationResult(
        session_id=uuid4(),
        user_id="user-test",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        decision=Decision.passed,
        document=DocumentAnalysis(status="passed", ocr=OcrResult(full_name="TEST USER")),
    )
    store.enroll(result, [1.0, 0.0, 0.0])

    match = store.match([0.0, 1.0, 0.0], lambda stored, probe: 0.42, threshold=0.72)

    assert match.profile is None
    assert match.score == 0.42


def test_enroll_updates_existing_user_instead_of_creating_duplicate(tmp_path) -> None:
    store = FaceProfileStore(tmp_path / "profiles.json")
    first = VerificationResult(
        session_id=uuid4(),
        user_id="user-001",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        decision=Decision.passed,
        document=DocumentAnalysis(status="passed", ocr=OcrResult(full_name="FIRST USER", passport_number="PA1111111")),
    )
    second = VerificationResult(
        session_id=uuid4(),
        user_id="user-001",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        decision=Decision.passed,
        document=DocumentAnalysis(status="passed", ocr=OcrResult(full_name="FIRST USER", passport_number="PA2222222")),
    )

    first_profile = store.enroll(first, [1.0, 0.0, 0.0])
    second_profile = store.enroll(second, [0.0, 1.0, 0.0])

    assert second_profile.face_id == first_profile.face_id
    assert len(store._read_records()) == 1
    assert store._read_records()[0]["passport_number"] == "PA2222222"


def test_enroll_rejects_passport_already_bound_to_another_user(tmp_path) -> None:
    store = FaceProfileStore(tmp_path / "profiles.json")
    first = VerificationResult(
        session_id=uuid4(),
        user_id="user-001",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        decision=Decision.passed,
        document=DocumentAnalysis(status="passed", ocr=OcrResult(full_name="FIRST USER", passport_number="PA1111111")),
    )
    second = VerificationResult(
        session_id=uuid4(),
        user_id="user-002",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        decision=Decision.passed,
        document=DocumentAnalysis(status="passed", ocr=OcrResult(full_name="SECOND USER", passport_number="PA1111111")),
    )

    store.enroll(first, [1.0, 0.0, 0.0])

    try:
        store.enroll(second, [0.0, 1.0, 0.0])
    except ValueError as exc:
        assert "already enrolled" in str(exc)
    else:
        raise AssertionError("Expected passport reuse to be rejected")


def test_list_and_delete_profiles_for_retesting(tmp_path) -> None:
    store = FaceProfileStore(tmp_path / "profiles.json")
    first = VerificationResult(
        session_id=uuid4(),
        user_id="user-001",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        decision=Decision.passed,
        document=DocumentAnalysis(status="passed", ocr=OcrResult(full_name="FIRST USER", passport_number="PA1111111")),
    )
    second = VerificationResult(
        session_id=uuid4(),
        user_id="user-002",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        decision=Decision.passed,
        document=DocumentAnalysis(status="passed", ocr=OcrResult(full_name="SECOND USER", passport_number="PA2222222")),
    )
    store.enroll(first, [1.0, 0.0, 0.0])
    store.enroll(second, [0.0, 1.0, 0.0])

    assert {profile.user_id for profile in store.list_profiles()} == {"user-001", "user-002"}
    assert store.delete_user("user-001") == 1
    assert {profile.user_id for profile in store.list_profiles()} == {"user-002"}
    assert store.delete_all() == 1
    assert store.list_profiles() == []
