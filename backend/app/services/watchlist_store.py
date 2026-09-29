"""Government watchlist ("blacklist") screening for border / immigration use.

A border authority supplies a list of flagged people (name, date of birth,
nationality, passport numbers, and — later — face photos) under its own legal
mandate. Kyron is the *engine*: it screens each verification against that list
and raises an alert for an officer to adjudicate. This module is the biographic
leg — matching the document data Kyron already reads against the list. The
biometric (1:N face) leg is a separate, later addition.

Design
------
* **Two tables.** ``watchlist_subjects`` holds the imported list;
  ``watchlist_hits`` records every match for the officer alert panel and audit.
* **Screening is fail-open.** A screening error is logged and swallowed so it can
  never break a traveller's verification.
* **Alert, don't silently auto-clear.** A hit is recorded as ``pending`` and an
  officer confirms or dismisses it. Kyron also refuses to auto-pass a session
  that hit the list (a high-severity signal is emitted upstream), but the
  actionable surface is the alert panel, not a black-box rejection.
* **High precision first.** Passport-number matches are near-exact; name matches
  require a corroborating date of birth (or a near-exact spelling) to keep the
  false-positive rate low — a false biographic hit accuses an innocent traveller.

The watchlist necessarily contains PII (that is its purpose and its legal basis).
Protect the database the same way as the evidence store: on-premise, encrypted at
rest at the volume level, admin-only access, every view audited.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, String, Text, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.services.crypto import get_template_cipher

logger = logging.getLogger(__name__)


class WatchlistBase(DeclarativeBase):
    pass


class WatchlistSubjectRecord(WatchlistBase):
    """One flagged person from the government list."""

    __tablename__ = "watchlist_subjects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ISO yyyy-mm-dd
    nationality: Mapped[str | None] = mapped_column(String(3), nullable=True)
    passport_numbers: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list, normalized
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="high")
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)  # list name / version
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Face (biometric) leg: an L2-normalized SFace embedding (JSON) plus an
    # encrypted copy of the enrolment photo for the officer's side-by-side.
    face_embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    face_photo_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class WatchlistHitRecord(WatchlistBase):
    """One screening match, surfaced to an officer for adjudication."""

    __tablename__ = "watchlist_hits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    subject_name: Mapped[str] = mapped_column(String(256), nullable=False)
    matched_on: Mapped[str] = mapped_column(String(32), nullable=False)  # passport_number | name_dob | name
    matched_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="high")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    adjudicated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    adjudicated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Face hits keep an encrypted copy of the probe image (the uploaded face)
    # so the officer can compare it against the matched watchlist photo.
    probe_path: Mapped[str | None] = mapped_column(Text, nullable=True)


@dataclass
class WatchlistMatch:
    subject_id: str
    subject_name: str
    matched_on: str          # passport_number | name_dob | name
    matched_value: str | None
    confidence: float
    severity: str
    reason: str | None
    source_ref: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def normalize_passport(value: str | None) -> str:
    """Uppercase and strip every non-alphanumeric character."""
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def normalize_name(value: str | None) -> str:
    """Uppercase, keep letters only, sort tokens so name order does not matter.

    "SMITH MURRAY ROSS" and "Murray Ross Smith" both normalize to
    "MURRAY ROSS SMITH", so MRZ (surname-first) and printed (given-first) order
    compare equal.
    """
    if not value:
        return ""
    tokens = re.findall(r"[A-Z]+", value.upper())
    return " ".join(sorted(tokens))


def _iso_dob(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10] or None


class WatchlistStore:
    def __init__(self, database_url: str | None = None, root: str | None = None) -> None:
        settings = get_settings()
        self._url = _normalize_url(database_url or settings.database_url)
        self._engine = create_engine(self._url, future=True)
        WatchlistBase.metadata.create_all(self._engine)
        self._ensure_columns()
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)
        self._root = Path(root or settings.watchlist_root)

    def _ensure_columns(self) -> None:
        """Add the face columns to a table created before this leg existed.

        create_all() never ALTERs an existing table, so a watchlist DB from the
        biographic-only version would miss face_embedding/face_photo_path/
        probe_path. SQLite/Postgres both support ADD COLUMN IF NOT EXISTS-style
        upgrades; we add each only when absent.
        """
        wanted = {
            "watchlist_subjects": [("face_embedding", "TEXT"), ("face_photo_path", "TEXT")],
            "watchlist_hits": [("probe_path", "TEXT")],
        }
        try:
            with self._engine.begin() as conn:
                for table, cols in wanted.items():
                    existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
                    for name, sqltype in cols:
                        if name not in existing:
                            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}")
        except Exception:  # noqa: BLE001 — non-SQLite backends create_all correctly
            logger.debug("watchlist column check skipped", exc_info=True)

    # --------------------------------------------------------------- ingestion
    def import_subjects(self, records: list[dict], *, source: str | None = None, replace: bool = False) -> int:
        """Bulk-import list entries. Each record accepts:

            full_name (required), date_of_birth (yyyy-mm-dd), nationality,
            passport_numbers (list[str] or comma string), source_ref, reason,
            severity, notes.

        ``replace=True`` clears the existing list first (a fresh government feed).
        Returns the number of subjects written.
        """
        now = _utcnow()
        written = 0
        with self._Session() as db:
            if replace:
                db.query(WatchlistSubjectRecord).delete()
            for rec in records:
                full_name = (rec.get("full_name") or "").strip()
                if not full_name:
                    continue
                raw_passports = rec.get("passport_numbers") or []
                if isinstance(raw_passports, str):
                    raw_passports = [p for p in re.split(r"[,;|]", raw_passports)]
                passports = sorted({normalize_passport(p) for p in raw_passports if normalize_passport(p)})
                db.add(WatchlistSubjectRecord(
                    id=str(uuid4()),
                    source_ref=(rec.get("source_ref") or None),
                    full_name=full_name,
                    name_normalized=normalize_name(full_name),
                    date_of_birth=_iso_dob(rec.get("date_of_birth")),
                    nationality=((rec.get("nationality") or "").strip().upper()[:3] or None),
                    passport_numbers=json.dumps(passports),
                    reason=(rec.get("reason") or None),
                    severity=(rec.get("severity") or "high"),
                    source=(rec.get("source") or source),
                    active=bool(rec.get("active", True)),
                    added_at=now,
                    notes=(rec.get("notes") or None),
                ))
                written += 1
            db.commit()
        return written

    # -------------------------------------------------------------- face leg
    def _store_photo(self, folder: str, name: str, image_bytes: bytes) -> str:
        directory = self._root / folder
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}.jpg"
        target.write_bytes(get_template_cipher().encrypt_bytes(image_bytes))
        return str(target)

    def add_face_subject(
        self,
        *,
        full_name: str,
        embedding: list[float],
        photo_bytes: bytes,
        date_of_birth: str | None = None,
        nationality: str | None = None,
        reason: str | None = None,
        severity: str = "high",
        source: str | None = None,
        source_ref: str | None = None,
    ) -> dict:
        """Enrol one person by face. Stores the L2-normalized embedding and an
        encrypted copy of the photo for the officer side-by-side."""
        subject_id = str(uuid4())
        photo_path = self._store_photo("subjects", subject_id, photo_bytes)
        with self._Session() as db:
            record = WatchlistSubjectRecord(
                id=subject_id,
                source_ref=source_ref,
                full_name=(full_name or "Unnamed subject").strip(),
                name_normalized=normalize_name(full_name),
                date_of_birth=_iso_dob(date_of_birth),
                nationality=((nationality or "").strip().upper()[:3] or None),
                passport_numbers="[]",
                reason=reason,
                severity=severity,
                source=source,
                active=True,
                added_at=_utcnow(),
                face_embedding=json.dumps([float(v) for v in embedding]),
                face_photo_path=photo_path,
            )
            db.add(record)
            db.commit()
            return self._subject_dict(record)

    def screen_face(self, embedding: list[float] | None) -> list[WatchlistMatch]:
        """1:N face screen. Returns matches at/above the face threshold, best first.

        Similarity is the same (cosine+1)/2 in [0,1] the selfie<->document match
        uses, so the threshold is comparable across the product.
        """
        settings = get_settings()
        if not settings.watchlist_enabled or not embedding:
            return []
        try:
            threshold = settings.watchlist_face_threshold
            matches: list[WatchlistMatch] = []
            with self._Session() as db:
                subjects = db.scalars(
                    select(WatchlistSubjectRecord).where(
                        WatchlistSubjectRecord.active.is_(True),
                        WatchlistSubjectRecord.face_embedding.is_not(None),
                    )
                ).all()
            for s in subjects:
                gallery = json.loads(s.face_embedding or "[]")
                if len(gallery) != len(embedding):
                    continue
                dot = sum(a * b for a, b in zip(embedding, gallery))
                score = max(0.0, min(1.0, (dot + 1.0) / 2.0))
                if score >= threshold:
                    matches.append(WatchlistMatch(
                        subject_id=s.id, subject_name=s.full_name,
                        matched_on="face", matched_value=None,
                        confidence=round(score, 3), severity=s.severity,
                        reason=s.reason, source_ref=s.source_ref,
                    ))
            return sorted(matches, key=lambda m: m.confidence, reverse=True)
        except Exception:  # noqa: BLE001 — screening must never break verification
            logger.exception("watchlist face screening failed")
            return []

    def record_face_hit(self, session_id, user_id: str | None, match: WatchlistMatch,
                        probe_bytes: bytes | None = None) -> str | None:
        """Record a face hit, de-duplicated per (session, subject) so a match at
        both the document and selfie steps yields one alert (highest score)."""
        with self._Session() as db:
            existing = db.scalars(
                select(WatchlistHitRecord).where(
                    WatchlistHitRecord.session_id == str(session_id),
                    WatchlistHitRecord.subject_id == match.subject_id,
                    WatchlistHitRecord.matched_on == "face",
                )
            ).first()
            if existing is not None:
                if match.confidence > existing.confidence:
                    existing.confidence = match.confidence
                    if probe_bytes and not existing.probe_path:
                        existing.probe_path = self._store_photo("probes", existing.id, probe_bytes)
                    db.commit()
                return existing.id
            hit_id = str(uuid4())
            probe_path = self._store_photo("probes", hit_id, probe_bytes) if probe_bytes else None
            db.add(WatchlistHitRecord(
                id=hit_id, session_id=str(session_id), user_id=user_id,
                subject_id=match.subject_id, subject_name=match.subject_name,
                matched_on="face", matched_value=None, confidence=match.confidence,
                severity=match.severity, reason=match.reason, status="pending",
                created_at=_utcnow(), probe_path=probe_path,
            ))
            db.commit()
            return hit_id

    def read_subject_photo(self, subject_id: str) -> bytes | None:
        with self._Session() as db:
            subject = db.get(WatchlistSubjectRecord, subject_id)
        return self._read_encrypted(subject.face_photo_path if subject else None)

    def read_hit_probe(self, hit_id: str) -> bytes | None:
        with self._Session() as db:
            hit = db.get(WatchlistHitRecord, hit_id)
        return self._read_encrypted(hit.probe_path if hit else None)

    @staticmethod
    def _read_encrypted(path: str | None) -> bytes | None:
        if not path:
            return None
        try:
            blob = Path(path).read_bytes()
        except OSError:
            return None
        return get_template_cipher().decrypt_bytes(blob)

    # --------------------------------------------------------------- screening
    def screen(
        self,
        *,
        passport_number: str | None,
        full_name: str | None,
        date_of_birth=None,
        nationality: str | None = None,
    ) -> list[WatchlistMatch]:
        """Biographic screen. Returns matches (highest confidence first).

        Precision rules:
          * passport number exact (normalized)  -> confidence 0.98
          * name close + same DOB               -> confidence up to 0.95
          * name near-exact, DOB unknown        -> confidence up to 0.80 (weaker)
        """
        settings = get_settings()
        if not settings.watchlist_enabled:
            return []
        try:
            probe_passport = normalize_passport(passport_number)
            probe_name = normalize_name(full_name)
            probe_dob = _iso_dob(date_of_birth)
            threshold = settings.watchlist_name_similarity

            matches: dict[str, WatchlistMatch] = {}
            with self._Session() as db:
                subjects = db.scalars(
                    select(WatchlistSubjectRecord).where(WatchlistSubjectRecord.active.is_(True))
                ).all()

            for s in subjects:
                # 1) Passport number — the strongest, near-exact signal.
                if probe_passport:
                    numbers = set(json.loads(s.passport_numbers or "[]"))
                    if probe_passport in numbers:
                        self._keep(matches, WatchlistMatch(
                            subject_id=s.id, subject_name=s.full_name,
                            matched_on="passport_number", matched_value=probe_passport,
                            confidence=0.98, severity=s.severity, reason=s.reason,
                            source_ref=s.source_ref,
                        ))
                        continue

                # 2) Name similarity, corroborated by DOB where available.
                if probe_name and s.name_normalized:
                    sim = SequenceMatcher(None, probe_name, s.name_normalized).ratio()
                    dob_match = bool(probe_dob and s.date_of_birth and probe_dob == s.date_of_birth)
                    if dob_match and sim >= threshold:
                        self._keep(matches, WatchlistMatch(
                            subject_id=s.id, subject_name=s.full_name,
                            matched_on="name_dob", matched_value=s.full_name,
                            confidence=round(min(0.95, 0.6 + 0.35 * sim), 3),
                            severity=s.severity, reason=s.reason, source_ref=s.source_ref,
                        ))
                    elif sim >= 0.95:
                        # Near-exact name with no DOB corroboration: weaker, still
                        # worth an officer's eyes, but flagged as lower confidence.
                        self._keep(matches, WatchlistMatch(
                            subject_id=s.id, subject_name=s.full_name,
                            matched_on="name", matched_value=s.full_name,
                            confidence=round(min(0.80, 0.55 + 0.25 * sim), 3),
                            severity=s.severity, reason=s.reason, source_ref=s.source_ref,
                        ))

            return sorted(matches.values(), key=lambda m: m.confidence, reverse=True)
        except Exception:  # noqa: BLE001 — screening must never break verification
            logger.exception("watchlist screening failed")
            return []

    @staticmethod
    def _keep(matches: dict[str, WatchlistMatch], candidate: WatchlistMatch) -> None:
        existing = matches.get(candidate.subject_id)
        if existing is None or candidate.confidence > existing.confidence:
            matches[candidate.subject_id] = candidate

    # -------------------------------------------------------------------- hits
    def record_hit(self, session_id, user_id: str | None, match: WatchlistMatch) -> str:
        hit_id = str(uuid4())
        with self._Session() as db:
            db.add(WatchlistHitRecord(
                id=hit_id,
                session_id=str(session_id),
                user_id=user_id,
                subject_id=match.subject_id,
                subject_name=match.subject_name,
                matched_on=match.matched_on,
                matched_value=match.matched_value,
                confidence=match.confidence,
                severity=match.severity,
                reason=match.reason,
                status="pending",
                created_at=_utcnow(),
            ))
            db.commit()
        return hit_id

    def has_hits(self, session_id) -> bool:
        """True if this session produced any watchlist hit — used to hard-stop
        the rest of the flow. A dismissed (false-alarm) hit no longer blocks."""
        if not get_settings().watchlist_enabled:
            return False
        with self._Session() as db:
            found = db.scalars(
                select(WatchlistHitRecord.id).where(
                    WatchlistHitRecord.session_id == str(session_id),
                    WatchlistHitRecord.status != "dismissed",
                ).limit(1)
            ).first()
        return found is not None

    def list_hits(self, *, status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._Session() as db:
            stmt = select(WatchlistHitRecord)
            if status:
                stmt = stmt.where(WatchlistHitRecord.status == status)
            stmt = stmt.order_by(WatchlistHitRecord.created_at.desc()).limit(limit).offset(offset)
            return [self._hit_dict(h) for h in db.scalars(stmt).all()]

    def adjudicate_hit(self, hit_id: str, status: str, actor: str, note: str | None = None) -> bool:
        if status not in {"confirmed", "dismissed", "pending"}:
            return False
        with self._Session() as db:
            hit = db.get(WatchlistHitRecord, hit_id)
            if hit is None:
                return False
            hit.status = status
            hit.adjudicated_by = actor
            hit.adjudicated_at = _utcnow()
            if note is not None:
                hit.note = note
            db.commit()
        return True

    def remove_subject(self, subject_id: str) -> bool:
        """Delete one person from the list and their encrypted photo. Past hits
        are kept (their subject_name is denormalized) so the audit trail stands."""
        with self._Session() as db:
            subject = db.get(WatchlistSubjectRecord, subject_id)
            if subject is None:
                return False
            if subject.face_photo_path:
                try:
                    Path(subject.face_photo_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("could not delete watchlist photo %s", subject.face_photo_path)
            db.delete(subject)
            db.commit()
        return True

    def list_subjects(self, *, query: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._Session() as db:
            stmt = select(WatchlistSubjectRecord)
            if query:
                like = f"%{normalize_name(query)}%"
                stmt = stmt.where(WatchlistSubjectRecord.name_normalized.like(like))
            stmt = stmt.order_by(WatchlistSubjectRecord.added_at.desc()).limit(limit).offset(offset)
            return [self._subject_dict(s) for s in db.scalars(stmt).all()]

    def summary(self) -> dict:
        settings = get_settings()
        with self._Session() as db:
            subjects = db.scalar(select(func.count()).select_from(WatchlistSubjectRecord)) or 0
            active = db.scalar(
                select(func.count()).select_from(WatchlistSubjectRecord)
                .where(WatchlistSubjectRecord.active.is_(True))
            ) or 0
            pending = db.scalar(
                select(func.count()).select_from(WatchlistHitRecord)
                .where(WatchlistHitRecord.status == "pending")
            ) or 0
            total_hits = db.scalar(select(func.count()).select_from(WatchlistHitRecord)) or 0
        return {
            "enabled": settings.watchlist_enabled,
            "subject_count": subjects,
            "active_subject_count": active,
            "pending_hits": pending,
            "total_hits": total_hits,
        }

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _hit_dict(h: WatchlistHitRecord) -> dict:
        return {
            "id": h.id,
            "session_id": h.session_id,
            "user_id": h.user_id,
            "subject_id": h.subject_id,
            "subject_name": h.subject_name,
            "matched_on": h.matched_on,
            "matched_value": h.matched_value,
            "confidence": round(h.confidence, 3),
            "severity": h.severity,
            "reason": h.reason,
            "status": h.status,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "adjudicated_by": h.adjudicated_by,
            "adjudicated_at": h.adjudicated_at.isoformat() if h.adjudicated_at else None,
            "note": h.note,
            "has_probe": bool(h.probe_path),
        }

    @staticmethod
    def _subject_dict(s: WatchlistSubjectRecord) -> dict:
        return {
            "id": s.id,
            "source_ref": s.source_ref,
            "full_name": s.full_name,
            "date_of_birth": s.date_of_birth,
            "nationality": s.nationality,
            "passport_numbers": json.loads(s.passport_numbers or "[]"),
            "reason": s.reason,
            "severity": s.severity,
            "source": s.source,
            "active": s.active,
            "added_at": s.added_at.isoformat() if s.added_at else None,
            "notes": s.notes,
            "has_face": bool(s.face_embedding),
        }


watchlist_store = WatchlistStore()
