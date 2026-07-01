"""Tamper-evident audit log (hash-chained append-only trail).

Every security-relevant event (authentication, PII access, admin actions, identity
enrollment/decisions) is appended as a chained record: each entry's hash covers the
*previous* entry's hash plus the entry's own fields, so removing, reordering, or
editing any row breaks the chain and is detectable by verify_chain().

When LALIGENCE_ENCRYPTION_KEY is set the chain is keyed (HMAC-SHA256), so an
attacker who can write to the table still cannot recompute a valid chain without
the key (tamper-*evident* and, with the key protected, tamper-*resistant*). With no
key it falls back to a plain SHA-256 chain (still detects accidental/naive edits).

Design constraints honored: no raw biometric media and no embeddings are logged;
detail payloads carry only minimized, non-sensitive metadata (ids, codes, flags).
Writes are fail-open — an audit failure must never break the request it describes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings

GENESIS_HASH = "0" * 64


class AuditBase(DeclarativeBase):
    pass


class AuditEvent(AuditBase):
    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class AuditLog:
    """Append-only, hash-chained event store."""

    def __init__(self, database_url: str | None = None) -> None:
        self._url = _normalize_url(database_url or get_settings().database_url)
        self._engine = create_engine(self._url, future=True)
        AuditBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)
        self._lock = threading.Lock()
        key = get_settings().encryption_key
        # Derive a dedicated audit key so it isn't the raw cipher key.
        self._hmac_key = hashlib.sha256(key.encode() + b"|audit-chain").digest() if key else None

    def _digest(self, prev_hash: str, canonical: str) -> str:
        message = f"{prev_hash}|{canonical}".encode()
        if self._hmac_key is not None:
            return hmac.new(self._hmac_key, message, hashlib.sha256).hexdigest()
        return hashlib.sha256(message).hexdigest()

    @staticmethod
    def _canonical(event_time: datetime, event_type: str, actor, action: str, subject, detail: dict | None) -> str:
        return json.dumps(
            {
                "t": _iso(event_time),
                "type": event_type,
                "actor": actor,
                "action": action,
                "subject": subject,
                "detail": detail or {},
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def record(
        self,
        event_type: str,
        action: str,
        *,
        actor: str | None = None,
        subject: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Append a chained event. Fail-open: never raises to the caller."""
        if not get_settings().audit_log_enabled:
            return
        try:
            event_time = datetime.now(timezone.utc)
            canonical = self._canonical(event_time, event_type, actor, action, subject, detail)
            with self._lock, self._Session.begin() as db:
                last = db.execute(
                    select(AuditEvent.entry_hash).order_by(AuditEvent.seq.desc()).limit(1)
                ).scalar_one_or_none()
                prev_hash = last or GENESIS_HASH
                entry_hash = self._digest(prev_hash, canonical)
                db.add(AuditEvent(
                    event_time=event_time,
                    event_type=event_type,
                    actor=actor,
                    action=action,
                    subject=subject,
                    detail=json.dumps(detail) if detail else None,
                    prev_hash=prev_hash,
                    entry_hash=entry_hash,
                ))
        except Exception:
            # Audit must never break the operation it records.
            pass

    def list_events(self, limit: int = 100) -> list[dict]:
        with self._Session() as db:
            rows = db.execute(
                select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
            ).scalars().all()
            return [self._to_dict(r) for r in rows]

    def verify_chain(self) -> dict:
        """Recompute the chain in order; report the first break (if any)."""
        with self._Session() as db:
            rows = db.execute(select(AuditEvent).order_by(AuditEvent.seq.asc())).scalars().all()
        prev_hash = GENESIS_HASH
        for row in rows:
            canonical = self._canonical(
                row.event_time, row.event_type, row.actor, row.action, row.subject,
                json.loads(row.detail) if row.detail else None,
            )
            expected = self._digest(prev_hash, canonical)
            if row.prev_hash != prev_hash or row.entry_hash != expected:
                return {"ok": False, "entries": len(rows), "broken_at": row.seq}
            prev_hash = row.entry_hash
        return {"ok": True, "entries": len(rows), "broken_at": None}

    @staticmethod
    def _to_dict(row: AuditEvent) -> dict:
        return {
            "seq": row.seq,
            "event_time": row.event_time,
            "event_type": row.event_type,
            "actor": row.actor,
            "action": row.action,
            "subject": row.subject,
            "detail": json.loads(row.detail) if row.detail else None,
            "entry_hash": row.entry_hash,
        }


def _iso(dt: datetime) -> str:
    """Timestamp string that round-trips identically through SQLite (which drops
    tzinfo) and PostgreSQL, so the hash chain verifies on either backend."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _normalize_url(raw_url: str) -> str:
    # Mirror profile_store: make relative sqlite paths absolute + ensure the dir.
    if raw_url.startswith("sqlite:///") and not raw_url.startswith("sqlite:////"):
        rel = raw_url[len("sqlite:///"):]
        path = Path(rel)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"
    return raw_url


audit_log = AuditLog()
