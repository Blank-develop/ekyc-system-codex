from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint, create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from app.services.crypto import get_template_cipher

from app.core.config import get_settings
from app.models.schemas import UserProfile, VerificationResult


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SQLITE_STORE_PATH = ROOT / "backend" / "data" / "laligence_profiles.sqlite3"
LEGACY_PROFILE_STORE_PATH = ROOT / "backend" / "data" / "face_profiles.json"


@dataclass
class FaceLoginMatch:
    profile: UserProfile | None
    score: float


class ProfileEnrollmentConflict(ValueError):
    pass


class Base(DeclarativeBase):
    pass


class FaceProfileRecord(Base):
    __tablename__ = "face_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_face_profiles_user_id"),
        UniqueConstraint("passport_number", name="uq_face_profiles_passport_number"),
        UniqueConstraint("verification_session_id", name="uq_face_profiles_session_id"),
    )

    face_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verification_session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    passport_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    passport_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    face_template: Mapped[list[float]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    template_model: Mapped[str] = mapped_column(String(64), nullable=False, default="opencv_yunet_sface")
    template_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    # When encryption is enabled the PII columns above are left null and the
    # values live (encrypted) in pii_encrypted; passport_number_bidx is a blind
    # index (keyed hash) so the one-document-one-profile rule still works.
    pii_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    passport_number_bidx: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class FaceProfileStore:
    """SQL-backed store for verified profiles and face templates.

    PostgreSQL is used when DATABASE_URL is set. Local development falls back to
    SQLite so testers do not need a database server. Face templates are biometric
    data; production deployments should add encryption, strict admin auth, audit
    logging, and retention/deletion policy.
    """

    def __init__(self, database_url: str | Path | None = None) -> None:
        self.database_url = self._normalize_database_url(database_url)
        self.path = self._sqlite_path(self.database_url)
        self.engine: Engine | None = None
        self.SessionLocal: sessionmaker[Session] | None = None
        self._active_records_cache: list[dict] | None = None

    def enroll(self, result: VerificationResult, face_template: list[float]) -> UserProfile:
        now = datetime.now(timezone.utc)
        try:
            with self._sessionmaker().begin() as db:
                existing = self._find_existing(db, result)
                profile = self._profile_from_result(
                    result,
                    existing_face_id=existing.face_id if existing else None,
                    enrolled_at=now,
                )
                self._delete_duplicate_records(db, profile, existing)
                record = existing if existing else FaceProfileRecord(face_id=str(profile.face_id))
                self._apply_profile(record, profile, face_template, now)
                db.merge(record)
                self._active_records_cache = None
        except IntegrityError as exc:
            raise ProfileEnrollmentConflict("Profile or identity document is already enrolled.") from exc
        return profile

    def match(self, face_template: list[float], compare, threshold: float) -> FaceLoginMatch:
        best_record: dict | None = None
        best_score = 0.0
        for record in self._active_records():
            stored_template = record.get("face_template")
            if not isinstance(stored_template, list):
                continue
            score = float(compare(stored_template, face_template))
            if score > best_score:
                best_score = score
                best_record = record

        if best_record is None or best_score < threshold:
            return FaceLoginMatch(profile=None, score=round(best_score, 2))

        now = datetime.now(timezone.utc)
        self._mark_login(best_record["face_id"], now)
        best_record["last_login_at"] = now
        best_record["updated_at"] = now
        profile = self._public_profile(best_record)
        profile.last_login_at = now
        return FaceLoginMatch(profile=profile, score=round(best_score, 2))

    def list_profiles(self) -> list[UserProfile]:
        with self._sessionmaker()() as db:
            records = db.scalars(select(FaceProfileRecord).where(FaceProfileRecord.active.is_(True))).all()
            return [self._public_profile(self._record_to_dict(record)) for record in records]

    def prime_cache(self) -> None:
        self._active_records()

    def delete_user(self, user_id: str) -> int:
        with self._sessionmaker().begin() as db:
            result = db.execute(delete(FaceProfileRecord).where(FaceProfileRecord.user_id == user_id))
            self._active_records_cache = None
            return int(result.rowcount or 0)

    def delete_all(self) -> int:
        with self._sessionmaker().begin() as db:
            deleted_count = db.scalar(select(func.count()).select_from(FaceProfileRecord)) or 0
            db.execute(delete(FaceProfileRecord))
            self._active_records_cache = None
            return int(deleted_count)

    def _find_existing(self, db: Session, result: VerificationResult) -> FaceProfileRecord | None:
        user_id = result.user_id.strip()
        passport_number = result.document.ocr.passport_number or result.document.ocr.document_number or result.document.ocr.id_number
        user_record = db.scalar(
            select(FaceProfileRecord).where(FaceProfileRecord.user_id == user_id, FaceProfileRecord.active.is_(True))
        )
        cipher = get_template_cipher()
        passport_record = None
        if passport_number:
            if cipher.enabled:
                passport_filter = FaceProfileRecord.passport_number_bidx == cipher.blind_index(passport_number)
            else:
                passport_filter = FaceProfileRecord.passport_number == passport_number
            passport_record = db.scalar(
                select(FaceProfileRecord).where(passport_filter, FaceProfileRecord.active.is_(True))
            )
        if passport_record and passport_record.user_id and passport_record.user_id != user_id:
            raise ProfileEnrollmentConflict("Identity document number is already enrolled to another user_id.")
        if user_record:
            return user_record
        if passport_record:
            return passport_record
        return db.scalar(select(FaceProfileRecord).where(FaceProfileRecord.verification_session_id == str(result.session_id)))

    def _delete_duplicate_records(self, db: Session, profile: UserProfile, existing: FaceProfileRecord | None) -> None:
        cipher = get_template_cipher()
        conditions = [FaceProfileRecord.user_id == profile.user_id]
        if profile.passport_number:
            if cipher.enabled:
                conditions.append(FaceProfileRecord.passport_number_bidx == cipher.blind_index(profile.passport_number))
            else:
                conditions.append(FaceProfileRecord.passport_number == profile.passport_number)
        for condition in conditions:
            statement = delete(FaceProfileRecord).where(condition)
            if existing:
                statement = statement.where(FaceProfileRecord.face_id != existing.face_id)
            db.execute(statement)

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
            passport_number=ocr.passport_number or ocr.document_number or ocr.id_number,
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

    def _public_profile(self, record: dict) -> UserProfile:
        allowed = set(UserProfile.model_fields)
        payload = {key: value for key, value in record.items() if key in allowed}
        return UserProfile.model_validate(payload)

    def _apply_profile(self, record: FaceProfileRecord, profile: UserProfile, face_template: list[float], updated_at: datetime) -> None:
        cipher = get_template_cipher()
        record.user_id = profile.user_id
        record.active = profile.active
        record.verification_session_id = str(profile.verification_session_id)
        record.enrolled_at = profile.enrolled_at
        record.last_login_at = profile.last_login_at
        record.updated_at = updated_at
        # Encrypt the biometric template at rest (no-op when no key is configured).
        record.face_template = cipher.encrypt_template(face_template)
        record.template_model = "opencv_yunet_sface"
        record.template_dimensions = len(face_template)

        if cipher.enabled:
            # Store PII encrypted; keep the plaintext columns null. passport_number_bidx
            # is a blind index so the uniqueness lookup still works without exposure.
            record.pii_encrypted = cipher.encrypt_json({
                "full_name": profile.full_name,
                "first_name": profile.first_name,
                "last_name": profile.last_name,
                "age": profile.age,
                "date_of_birth": profile.date_of_birth.isoformat() if profile.date_of_birth else None,
                "nationality": profile.nationality,
                "passport_number": profile.passport_number,
                "passport_expiry": profile.passport_expiry.isoformat() if profile.passport_expiry else None,
            })
            record.passport_number_bidx = cipher.blind_index(profile.passport_number)
            record.full_name = record.first_name = record.last_name = None
            record.age = None
            record.date_of_birth = None
            record.nationality = None
            record.passport_number = None
            record.passport_expiry = None
        else:
            record.pii_encrypted = None
            record.passport_number_bidx = None
            record.full_name = profile.full_name
            record.first_name = profile.first_name
            record.last_name = profile.last_name
            record.age = profile.age
            record.date_of_birth = profile.date_of_birth
            record.nationality = profile.nationality
            record.passport_number = profile.passport_number
            record.passport_expiry = profile.passport_expiry

    @staticmethod
    def _record_to_dict(record: FaceProfileRecord) -> dict:
        cipher = get_template_cipher()
        data = {
            "face_id": record.face_id,
            "user_id": record.user_id,
            "active": record.active,
            "verification_session_id": record.verification_session_id,
            "full_name": record.full_name,
            "first_name": record.first_name,
            "last_name": record.last_name,
            "age": record.age,
            "date_of_birth": record.date_of_birth,
            "nationality": record.nationality,
            "passport_number": record.passport_number,
            "passport_expiry": record.passport_expiry,
            "enrolled_at": record.enrolled_at,
            "last_login_at": record.last_login_at,
            "updated_at": record.updated_at,
            "face_template": cipher.decrypt_template(record.face_template),
            "template_model": record.template_model,
            "template_dimensions": record.template_dimensions,
        }
        # Encrypted PII (dates come back as ISO strings; pydantic parses them).
        pii = cipher.decrypt_json(record.pii_encrypted) if record.pii_encrypted else None
        if pii:
            for field in ("full_name", "first_name", "last_name", "age", "date_of_birth",
                          "nationality", "passport_number", "passport_expiry"):
                data[field] = pii.get(field)
        return data

    def _read_records(self) -> list[dict]:
        with self._sessionmaker()() as db:
            records = db.scalars(select(FaceProfileRecord)).all()
            return [self._record_to_dict(record) for record in records]

    def _active_records(self) -> list[dict]:
        if self._active_records_cache is None:
            with self._sessionmaker()() as db:
                records = db.scalars(select(FaceProfileRecord).where(FaceProfileRecord.active.is_(True))).all()
                self._active_records_cache = [self._record_to_dict(record) for record in records]
        return self._active_records_cache

    def _mark_login(self, face_id: str, now: datetime) -> None:
        with self._sessionmaker().begin() as db:
            record = db.get(FaceProfileRecord, face_id)
            if record:
                record.last_login_at = now
                record.updated_at = now

    def _sessionmaker(self) -> sessionmaker[Session]:
        if self.SessionLocal is None:
            connect_args = {"check_same_thread": False} if self.database_url.startswith("sqlite") else {}
            self.engine = create_engine(self.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
            self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
            Base.metadata.create_all(self.engine)
            self._migrate_legacy_json_if_needed()
        return self.SessionLocal

    def _migrate_legacy_json_if_needed(self) -> None:
        if not self.path or self.path != DEFAULT_SQLITE_STORE_PATH or not LEGACY_PROFILE_STORE_PATH.exists():
            return
        with self._sessionmaker()() as db:
            has_records = db.scalar(select(FaceProfileRecord.face_id).limit(1)) is not None
        if has_records:
            return
        try:
            legacy_records = json.loads(LEGACY_PROFILE_STORE_PATH.read_text())
        except json.JSONDecodeError:
            return
        if not isinstance(legacy_records, list):
            return
        now = datetime.now(timezone.utc)
        with self._sessionmaker().begin() as db:
            for legacy in legacy_records:
                try:
                    profile = self._public_profile(legacy)
                    record = FaceProfileRecord(face_id=str(profile.face_id))
                    self._apply_profile(record, profile, legacy.get("face_template") or [], now)
                    db.merge(record)
                except Exception:
                    continue

    @staticmethod
    def _normalize_database_url(database_url: str | Path | None) -> str:
        if isinstance(database_url, Path):
            database_url.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{database_url}"
        raw_url = database_url or get_settings().database_url
        if raw_url.startswith("postgres://"):
            return raw_url.replace("postgres://", "postgresql+psycopg://", 1)
        if raw_url.startswith("postgresql://"):
            return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if raw_url.startswith("sqlite:///"):
            sqlite_path = Path(raw_url.replace("sqlite:///", "", 1))
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return raw_url

    @staticmethod
    def _sqlite_path(database_url: str) -> Path | None:
        if not database_url.startswith("sqlite:///"):
            return None
        return Path(database_url.replace("sqlite:///", "", 1)).resolve()


profile_store = FaceProfileStore()
