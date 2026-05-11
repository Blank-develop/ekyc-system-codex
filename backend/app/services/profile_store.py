from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Integer, String, UniqueConstraint, create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

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
        connect_args = {"check_same_thread": False} if self.database_url.startswith("sqlite") else {}
        self.engine = create_engine(self.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(self.engine)
        self._migrate_legacy_json_if_needed()

    def enroll(self, result: VerificationResult, face_template: list[float]) -> UserProfile:
        now = datetime.now(timezone.utc)
        try:
            with self.SessionLocal.begin() as db:
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
        except IntegrityError as exc:
            raise ProfileEnrollmentConflict("Profile or passport is already enrolled.") from exc
        return profile

    def match(self, face_template: list[float], compare, threshold: float) -> FaceLoginMatch:
        best_record: FaceProfileRecord | None = None
        best_score = 0.0
        with self.SessionLocal() as db:
            records = db.scalars(select(FaceProfileRecord).where(FaceProfileRecord.active.is_(True))).all()
            for record in records:
                if not isinstance(record.face_template, list):
                    continue
                score = float(compare(record.face_template, face_template))
                if score > best_score:
                    best_score = score
                    best_record = record

            if best_record is None or best_score < threshold:
                return FaceLoginMatch(profile=None, score=round(best_score, 2))

            now = datetime.now(timezone.utc)
            best_record.last_login_at = now
            best_record.updated_at = now
            db.commit()
            profile = self._public_profile(self._record_to_dict(best_record))
            profile.last_login_at = now
            return FaceLoginMatch(profile=profile, score=round(best_score, 2))

    def list_profiles(self) -> list[UserProfile]:
        with self.SessionLocal() as db:
            records = db.scalars(select(FaceProfileRecord).where(FaceProfileRecord.active.is_(True))).all()
            return [self._public_profile(self._record_to_dict(record)) for record in records]

    def delete_user(self, user_id: str) -> int:
        with self.SessionLocal.begin() as db:
            result = db.execute(delete(FaceProfileRecord).where(FaceProfileRecord.user_id == user_id))
            return int(result.rowcount or 0)

    def delete_all(self) -> int:
        with self.SessionLocal.begin() as db:
            deleted_count = db.scalar(select(func.count()).select_from(FaceProfileRecord)) or 0
            db.execute(delete(FaceProfileRecord))
            return int(deleted_count)

    def _find_existing(self, db: Session, result: VerificationResult) -> FaceProfileRecord | None:
        user_id = result.user_id.strip()
        passport_number = result.document.ocr.passport_number
        user_record = db.scalar(
            select(FaceProfileRecord).where(FaceProfileRecord.user_id == user_id, FaceProfileRecord.active.is_(True))
        )
        passport_record = None
        if passport_number:
            passport_record = db.scalar(
                select(FaceProfileRecord).where(
                    FaceProfileRecord.passport_number == passport_number,
                    FaceProfileRecord.active.is_(True),
                )
            )
        if passport_record and passport_record.user_id and passport_record.user_id != user_id:
            raise ProfileEnrollmentConflict("Passport number is already enrolled to another user_id.")
        if user_record:
            return user_record
        if passport_record:
            return passport_record
        return db.scalar(select(FaceProfileRecord).where(FaceProfileRecord.verification_session_id == str(result.session_id)))

    def _delete_duplicate_records(self, db: Session, profile: UserProfile, existing: FaceProfileRecord | None) -> None:
        conditions = [FaceProfileRecord.user_id == profile.user_id]
        if profile.passport_number:
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

    def _public_profile(self, record: dict) -> UserProfile:
        allowed = set(UserProfile.model_fields)
        payload = {key: value for key, value in record.items() if key in allowed}
        return UserProfile.model_validate(payload)

    def _apply_profile(self, record: FaceProfileRecord, profile: UserProfile, face_template: list[float], updated_at: datetime) -> None:
        record.user_id = profile.user_id
        record.active = profile.active
        record.verification_session_id = str(profile.verification_session_id)
        record.full_name = profile.full_name
        record.first_name = profile.first_name
        record.last_name = profile.last_name
        record.age = profile.age
        record.date_of_birth = profile.date_of_birth
        record.nationality = profile.nationality
        record.passport_number = profile.passport_number
        record.passport_expiry = profile.passport_expiry
        record.enrolled_at = profile.enrolled_at
        record.last_login_at = profile.last_login_at
        record.updated_at = updated_at
        record.face_template = [float(value) for value in face_template]
        record.template_model = "opencv_yunet_sface"
        record.template_dimensions = len(face_template)

    @staticmethod
    def _record_to_dict(record: FaceProfileRecord) -> dict:
        return {
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
            "face_template": record.face_template,
            "template_model": record.template_model,
            "template_dimensions": record.template_dimensions,
        }

    def _read_records(self) -> list[dict]:
        with self.SessionLocal() as db:
            records = db.scalars(select(FaceProfileRecord)).all()
            return [self._record_to_dict(record) for record in records]

    def _migrate_legacy_json_if_needed(self) -> None:
        if not self.path or self.path != DEFAULT_SQLITE_STORE_PATH or not LEGACY_PROFILE_STORE_PATH.exists():
            return
        with self.SessionLocal() as db:
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
        with self.SessionLocal.begin() as db:
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
