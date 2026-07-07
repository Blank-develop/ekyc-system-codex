"""Persistent log of every eKYC verification attempt (for the admin portal).

VerificationStore (session_store.py) holds live sessions in memory only — restart
the process and the history is gone, and there is no way to answer "how many
attempts today, how many passed, who was rejected and why." This store fills that
gap: one row per session_id, upserted after every step, so the admin portal can
list/filter attempts and show pass/pending/reject counts.

Deliberately minimal for privacy: no raw images, no biometric embeddings, and no
document PII (name/DOB/passport number) are persisted here — only the decision,
reason codes, per-step scores/flags, and identifiers already used elsewhere
(user_id, client IP). This mirrors the data-minimization principle used by the
audit log and profile store. Writes are fail-open: recording an attempt must never
break the verification request it describes.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, delete, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.models.schemas import VerificationResult


class AttemptBase(DeclarativeBase):
    pass


class VerificationAttemptRecord(AttemptBase):
    __tablename__ = "verification_attempts"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reason_codes: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    document_fraud_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_liveness_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hand_challenge_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    passive_liveness_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    face_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passive_liveness_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    contact_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AttemptStore:
    def __init__(self, database_url: str | None = None) -> None:
        self._url = _normalize_url(database_url or get_settings().database_url)
        self._engine = create_engine(self._url, future=True)
        AttemptBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)
        self._lock = threading.Lock()

    def record(self, result: VerificationResult, client_ip: str | None = None) -> None:
        """Upsert the current state of a session. Fail-open: never raises."""
        try:
            now = datetime.now(timezone.utc)
            with self._lock, self._Session.begin() as db:
                rec = db.get(VerificationAttemptRecord, str(result.session_id))
                if rec is None:
                    rec = VerificationAttemptRecord(
                        session_id=str(result.session_id), created_at=result.created_at, step_count=0
                    )
                    db.add(rec)
                rec.user_id = result.user_id
                rec.decision = result.decision.value
                rec.reason_codes = json.dumps(result.reason_codes)
                rec.document_type = result.document.ocr.document_type
                rec.document_status = result.document.status
                rec.document_fraud_risk = result.document.fraud_risk_score
                rec.active_liveness_passed = result.biometric.active_liveness_passed
                rec.hand_challenge_passed = result.biometric.hand_challenge_passed
                rec.passive_liveness_passed = result.biometric.passive_liveness_passed
                rec.face_match_score = result.biometric.face_match_score
                rec.passive_liveness_risk = result.biometric.passive_liveness_risk
                rec.contact_confirmed = result.contact_confirmed
                if client_ip:
                    rec.client_ip = client_ip
                rec.step_count = (rec.step_count or 0) + 1
                rec.updated_at = now
        except Exception:
            pass

    def list_attempts(
        self, limit: int = 50, offset: int = 0, decision: str | None = None, user_id: str | None = None
    ) -> tuple[list[dict], int]:
        with self._Session() as db:
            query = select(VerificationAttemptRecord)
            count_query = select(func.count()).select_from(VerificationAttemptRecord)
            if decision:
                query = query.where(VerificationAttemptRecord.decision == decision)
                count_query = count_query.where(VerificationAttemptRecord.decision == decision)
            if user_id:
                query = query.where(VerificationAttemptRecord.user_id == user_id)
                count_query = count_query.where(VerificationAttemptRecord.user_id == user_id)
            total = db.scalar(count_query) or 0
            rows = db.execute(
                query.order_by(VerificationAttemptRecord.updated_at.desc()).limit(limit).offset(offset)
            ).scalars().all()
            return [self._to_dict(r) for r in rows], int(total)

    def summary(self) -> dict:
        with self._Session() as db:
            rows = db.execute(
                select(VerificationAttemptRecord.decision, func.count())
                .group_by(VerificationAttemptRecord.decision)
            ).all()
        counts = {"passed": 0, "pending": 0, "rejected": 0}
        for decision, count in rows:
            counts[decision] = int(count)
        return {"total": sum(counts.values()), **counts}

    def purge_older_than(self, days: int, now: datetime | None = None) -> int:
        if days <= 0:
            return 0
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
        with self._Session.begin() as db:
            result = db.execute(delete(VerificationAttemptRecord).where(VerificationAttemptRecord.updated_at < cutoff))
            return int(result.rowcount or 0)

    @staticmethod
    def _to_dict(row: VerificationAttemptRecord) -> dict:
        return {
            "session_id": row.session_id,
            "user_id": row.user_id,
            "decision": row.decision,
            "reason_codes": json.loads(row.reason_codes) if row.reason_codes else [],
            "document_type": row.document_type,
            "document_status": row.document_status,
            "document_fraud_risk": row.document_fraud_risk,
            "active_liveness_passed": row.active_liveness_passed,
            "hand_challenge_passed": row.hand_challenge_passed,
            "passive_liveness_passed": row.passive_liveness_passed,
            "face_match_score": row.face_match_score,
            "passive_liveness_risk": row.passive_liveness_risk,
            "contact_confirmed": row.contact_confirmed,
            "client_ip": row.client_ip,
            "step_count": int(row.step_count or 0),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


def _normalize_url(raw_url: str) -> str:
    # Mirror profile_store/audit: make relative sqlite paths absolute + ensure the dir.
    if raw_url.startswith("sqlite:///") and not raw_url.startswith("sqlite:////"):
        rel = raw_url[len("sqlite:///"):]
        path = Path(rel)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"
    return raw_url


attempt_store = AttemptStore()
