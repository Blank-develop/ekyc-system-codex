"""Evidence retention for border / immigration deployments.

The standard Kyron product deliberately keeps **no** raw document or selfie
images: only transient embeddings live in session state. Border and airport
immigration systems operate under statutory authority and are instead required
to retain the evidence behind every crossing, so this module adds an
opt-in evidence store (``LALIGENCE_EVIDENCE_ENABLED``) that captures:

* the frames from every step (document, active liveness, hand gesture, selfie),
* an action timeline of what happened during the session, and
* an access log of every time an operator views a traveller's evidence.

Design notes
------------
* **Frames live on disk, metadata in the database.** Blobs in SQLite/Postgres
  bloat the database and make backup/restore painful; an on-premise filesystem
  is also what a government data centre expects.
* **Each frame is encrypted at rest** with the existing key-rotation cipher, so
  a stolen disk yields nothing without the key.
* **Frames are downscaled and re-compressed** on write. At ~500 crossings/day
  that keeps a five-year archive near 1.4 TB rather than several times that.
* **Every write is fail-open.** Evidence capture must never break a traveller's
  verification: a storage failure is logged and swallowed.
* **Frames expire, the crossing record does not** (by default). Immigration
  systems typically keep the record of the encounter permanently and expire only
  the biometric media; ``LALIGENCE_EVIDENCE_PURGE_METADATA`` opts into deleting
  the rows as well.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.core.config import get_settings
from app.services.crypto import get_template_cipher

logger = logging.getLogger(__name__)


class EvidenceBase(DeclarativeBase):
    pass


class EvidenceFrameRecord(EvidenceBase):
    """One captured frame belonging to a verification session."""

    __tablename__ = "verification_evidence_frames"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    step: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class EvidenceEventRecord(EvidenceBase):
    """Timeline of what happened during a session (what an auditor reads)."""

    __tablename__ = "verification_evidence_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason_codes: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON object
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class EvidenceAccessRecord(EvidenceBase):
    """Who viewed which traveller's evidence, and when.

    Border systems are audited hard on exactly this, so every read of a frame is
    recorded even while a single operator role exists.
    """

    __tablename__ = "verification_evidence_access"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    frame_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceStore:
    def __init__(self, database_url: str | None = None, root: str | None = None) -> None:
        settings = get_settings()
        self._url = _normalize_url(database_url or settings.database_url)
        self._engine = create_engine(self._url, future=True)
        EvidenceBase.metadata.create_all(self._engine)
        self._root = Path(root or settings.evidence_root)

    # ------------------------------------------------------------------ writes
    def store_frames(
        self,
        session_id: UUID | str,
        step: str,
        frames: list[bytes],
        *,
        user_id: str | None = None,
        label: str | None = None,
    ) -> int:
        """Persist the frames for one step. Returns how many were written.

        Fail-open: any storage problem is logged and swallowed so evidence
        capture can never block a traveller's verification.
        """
        settings = get_settings()
        if not settings.evidence_enabled or not frames:
            return 0
        try:
            now = _utcnow()
            expires_at = (
                now + timedelta(days=settings.evidence_retention_days)
                if settings.evidence_retention_days > 0
                else None
            )
            directory = self._root / f"{now:%Y/%m/%d}" / str(session_id)
            directory.mkdir(parents=True, exist_ok=True)
            cipher = get_template_cipher()
            written = 0
            with Session(self._engine) as db:
                for index, raw in enumerate(frames):
                    if not raw:
                        continue
                    payload = self._compress(raw, settings)
                    digest = hashlib.sha256(payload).hexdigest()
                    blob = cipher.encrypt_bytes(payload)
                    name = f"{step}_{label or 'frame'}_{index + 1}.jpg".replace("/", "-")
                    target = directory / name
                    target.write_bytes(blob)
                    db.add(
                        EvidenceFrameRecord(
                            id=str(uuid4()),
                            session_id=str(session_id),
                            user_id=user_id,
                            step=step,
                            label=label,
                            sequence=index,
                            path=str(target),
                            sha256=digest,
                            byte_size=len(blob),
                            encrypted=cipher.enabled,
                            captured_at=now,
                            expires_at=expires_at,
                        )
                    )
                    written += 1
                db.commit()
            return written
        except Exception:  # noqa: BLE001 - never break verification
            logger.exception("evidence frame storage failed for session %s", session_id)
            return 0

    def record_event(
        self,
        session_id: UUID | str,
        step: str,
        action: str,
        *,
        outcome: str | None = None,
        reason_codes: list[str] | None = None,
        detail: dict | None = None,
        duration_ms: float | None = None,
    ) -> None:
        settings = get_settings()
        if not settings.evidence_enabled:
            return
        try:
            with Session(self._engine) as db:
                db.add(
                    EvidenceEventRecord(
                        id=str(uuid4()),
                        session_id=str(session_id),
                        step=step,
                        action=action,
                        outcome=outcome,
                        reason_codes=json.dumps(reason_codes) if reason_codes else None,
                        detail=json.dumps(detail) if detail else None,
                        duration_ms=duration_ms,
                        occurred_at=_utcnow(),
                    )
                )
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("evidence event write failed for session %s", session_id)

    def record_access(
        self,
        session_id: UUID | str,
        actor: str,
        action: str,
        *,
        frame_id: str | None = None,
        client_ip: str | None = None,
    ) -> None:
        try:
            with Session(self._engine) as db:
                db.add(
                    EvidenceAccessRecord(
                        id=str(uuid4()),
                        session_id=str(session_id),
                        frame_id=frame_id,
                        actor=actor,
                        action=action,
                        client_ip=client_ip,
                        occurred_at=_utcnow(),
                    )
                )
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("evidence access log failed for session %s", session_id)

    # ------------------------------------------------------------------- reads
    def list_frames(self, session_id: UUID | str) -> list[EvidenceFrameRecord]:
        with Session(self._engine) as db:
            return list(
                db.scalars(
                    select(EvidenceFrameRecord)
                    .where(EvidenceFrameRecord.session_id == str(session_id))
                    .order_by(EvidenceFrameRecord.captured_at, EvidenceFrameRecord.sequence)
                )
            )

    def list_events(self, session_id: UUID | str) -> list[EvidenceEventRecord]:
        with Session(self._engine) as db:
            return list(
                db.scalars(
                    select(EvidenceEventRecord)
                    .where(EvidenceEventRecord.session_id == str(session_id))
                    .order_by(EvidenceEventRecord.occurred_at)
                )
            )

    def list_access(self, session_id: UUID | str) -> list[EvidenceAccessRecord]:
        with Session(self._engine) as db:
            return list(
                db.scalars(
                    select(EvidenceAccessRecord)
                    .where(EvidenceAccessRecord.session_id == str(session_id))
                    .order_by(EvidenceAccessRecord.occurred_at.desc())
                )
            )

    def get_frame(self, frame_id: str) -> EvidenceFrameRecord | None:
        with Session(self._engine) as db:
            return db.get(EvidenceFrameRecord, frame_id)

    def read_frame_bytes(self, record: EvidenceFrameRecord) -> bytes | None:
        """Decrypt a stored frame for display. Returns None when unreadable."""
        try:
            blob = Path(record.path).read_bytes()
        except OSError:
            logger.warning("evidence frame missing on disk: %s", record.path)
            return None
        if not record.encrypted:
            return blob
        return get_template_cipher().decrypt_bytes(blob)

    def summary(self) -> dict:
        settings = get_settings()
        with Session(self._engine) as db:
            frames = list(db.scalars(select(EvidenceFrameRecord)))
        total_bytes = sum(frame.byte_size for frame in frames)
        sessions = {frame.session_id for frame in frames}
        return {
            "enabled": settings.evidence_enabled,
            "frame_count": len(frames),
            "session_count": len(sessions),
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "retention_days": settings.evidence_retention_days,
            "encrypted": get_template_cipher().enabled,
        }

    # --------------------------------------------------------------- retention
    def purge_expired(self) -> dict:
        """Delete frames past their retention date.

        The crossing metadata row is preserved unless
        ``LALIGENCE_EVIDENCE_PURGE_METADATA`` is set, because immigration
        systems normally keep the record of the encounter and expire only the
        biometric media.
        """
        settings = get_settings()
        now = _utcnow()
        removed_files = 0
        removed_rows = 0
        with Session(self._engine) as db:
            expired = list(
                db.scalars(
                    select(EvidenceFrameRecord).where(
                        EvidenceFrameRecord.expires_at.is_not(None),
                        EvidenceFrameRecord.expires_at <= now,
                    )
                )
            )
            for record in expired:
                try:
                    Path(record.path).unlink(missing_ok=True)
                    removed_files += 1
                except OSError:
                    logger.warning("could not delete evidence file %s", record.path)
            if expired:
                if settings.evidence_purge_metadata:
                    db.execute(
                        delete(EvidenceFrameRecord).where(
                            EvidenceFrameRecord.id.in_([r.id for r in expired])
                        )
                    )
                    removed_rows = len(expired)
                else:
                    # Keep the row as proof the media existed and was disposed of.
                    for record in expired:
                        record.path = ""
                        record.byte_size = 0
                db.commit()
        return {"files_removed": removed_files, "rows_removed": removed_rows}

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _compress(raw: bytes, settings) -> bytes:
        """Downscale + re-encode so the archive stays affordable."""
        try:
            from PIL import Image, ImageOps

            image = ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGB")
            longest = max(image.size)
            cap = settings.evidence_max_frame_px
            if cap and longest > cap:
                scale = cap / longest
                image = image.resize((round(image.width * scale), round(image.height * scale)))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=settings.evidence_jpeg_quality, optimize=True)
            return buffer.getvalue()
        except Exception:  # noqa: BLE001 - store the original rather than nothing
            return raw


evidence_store = EvidenceStore()
