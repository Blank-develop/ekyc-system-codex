from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from app.models.schemas import UserProfile, VerificationResult


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE_STORE_PATH = ROOT / "backend" / "data" / "face_profiles.json"


@dataclass
class FaceLoginMatch:
    profile: UserProfile | None
    score: float


class ProfileEnrollmentConflict(ValueError):
    pass


class FaceProfileStore:
    """Local demo store for verified profiles and face templates.

    This stores face embeddings because the prototype needs local matching.
    Production should encrypt these templates with a managed key, audit all
    access, and enforce consent/deletion/retention policy.
    """

    def __init__(self, path: Path = DEFAULT_PROFILE_STORE_PATH) -> None:
        self.path = path

    def enroll(self, result: VerificationResult, face_template: list[float]) -> UserProfile:
        records = self._read_records()
        now = datetime.now(timezone.utc)
        existing = self._find_existing(records, result)
        profile = self._profile_from_result(result, existing_face_id=existing.get("face_id") if existing else None, enrolled_at=now)
        record = {
            **profile.model_dump(mode="json"),
            "face_template": face_template,
            "template_model": "opencv_yunet_sface",
            "template_dimensions": len(face_template),
            "updated_at": now.isoformat(),
        }

        records = self._without_duplicates(records, profile, existing)
        records.append(record)
        self._write_records(records)
        return profile

    def match(self, face_template: list[float], compare, threshold: float) -> FaceLoginMatch:
        best_record: dict | None = None
        best_score = 0.0
        for record in self._read_records():
            if record.get("active") is False:
                continue
            stored_template = record.get("face_template")
            if not isinstance(stored_template, list):
                continue
            score = float(compare(stored_template, face_template))
            if score > best_score:
                best_score = score
                best_record = record
        if best_record is None or best_score < threshold:
            return FaceLoginMatch(profile=None, score=round(best_score, 2))
        profile = self._public_profile(best_record)
        self._mark_login(profile.face_id)
        profile.last_login_at = datetime.now(timezone.utc)
        return FaceLoginMatch(profile=profile, score=round(best_score, 2))

    def list_profiles(self) -> list[UserProfile]:
        return [self._public_profile(record) for record in self._read_records() if record.get("active", True)]

    def delete_user(self, user_id: str) -> int:
        records = self._read_records()
        kept = [record for record in records if record.get("user_id") != user_id]
        deleted_count = len(records) - len(kept)
        if deleted_count:
            self._write_records(kept)
        return deleted_count

    def delete_all(self) -> int:
        records = self._read_records()
        deleted_count = len(records)
        if self.path.exists():
            self.path.unlink()
        return deleted_count

    def _find_existing(self, records: list[dict], result: VerificationResult) -> dict | None:
        user_id = result.user_id.strip()
        passport_number = result.document.ocr.passport_number
        user_record = next((record for record in records if record.get("user_id") == user_id and record.get("active", True)), None)
        passport_record = next(
            (
                record
                for record in records
                if passport_number and record.get("passport_number") == passport_number and record.get("active", True)
            ),
            None,
        )
        if passport_record and passport_record.get("user_id") and passport_record.get("user_id") != user_id:
            raise ProfileEnrollmentConflict("Passport number is already enrolled to another user_id.")
        if user_record:
            return user_record
        if passport_record:
            return passport_record
        session_id = str(result.session_id)
        for record in records:
            if record.get("verification_session_id") == session_id:
                return record
        return None

    def _without_duplicates(self, records: list[dict], profile: UserProfile, existing: dict | None) -> list[dict]:
        passport_number = profile.passport_number
        existing_face_id = existing.get("face_id") if existing else None
        return [
            record
            for record in records
            if record.get("face_id") != existing_face_id
            and record.get("user_id") != profile.user_id
            and not (passport_number and record.get("passport_number") == passport_number)
        ]

    def _profile_from_result(self, result: VerificationResult, existing_face_id: str | None, enrolled_at: datetime) -> UserProfile:
        ocr = result.document.ocr
        first_name, last_name = self._split_name(ocr.full_name)
        return UserProfile(
            face_id=UUID(existing_face_id) if existing_face_id else uuid4(),
            user_id=result.user_id.strip(),
            active=True,
            verification_session_id=result.session_id,
            full_name=ocr.full_name,
            first_name=first_name,
            last_name=last_name,
            age=self._age(ocr.date_of_birth),
            date_of_birth=ocr.date_of_birth,
            nationality=ocr.nationality,
            passport_number=ocr.passport_number,
            passport_expiry=ocr.expiry_date,
            enrolled_at=enrolled_at,
            last_login_at=None,
        )

    @staticmethod
    def _split_name(full_name: str | None) -> tuple[str | None, str | None]:
        if not full_name:
            return None, None
        parts = [part for part in full_name.replace("<", " ").split() if part]
        if not parts:
            return None, None
        if len(parts) == 1:
            return parts[0].title(), None
        return " ".join(parts[:-1]).title(), parts[-1].title()

    @staticmethod
    def _age(date_of_birth: date | None) -> int | None:
        if date_of_birth is None:
            return None
        today = date.today()
        age = today.year - date_of_birth.year
        if (today.month, today.day) < (date_of_birth.month, date_of_birth.day):
            age -= 1
        return age

    def _mark_login(self, face_id: UUID) -> None:
        records = self._read_records()
        now = datetime.now(timezone.utc).isoformat()
        for record in records:
            if record.get("face_id") == str(face_id):
                record["last_login_at"] = now
                record["updated_at"] = now
                break
        self._write_records(records)

    def _public_profile(self, record: dict) -> UserProfile:
        allowed = set(UserProfile.model_fields)
        payload = {key: value for key, value in record.items() if key in allowed}
        if "user_id" not in payload:
            payload["user_id"] = f"legacy-{record.get('face_id', 'unknown')}"
        if "active" not in payload:
            payload["active"] = True
        return UserProfile.model_validate(payload)

    def _read_records(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _write_records(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(records, indent=2, sort_keys=True))
        temp_path.replace(self.path)


profile_store = FaceProfileStore()
