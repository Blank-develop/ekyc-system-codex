"""Evidence retention for border / immigration deployments.

Covers the properties that matter for an official system of record: capture is
opt-in, frames are encrypted at rest, viewing is audited, and media expires on
schedule while the crossing record survives.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from app.core.config import get_settings
from app.services.evidence_store import EvidenceStore


def _jpeg(width: int = 900, height: int = 700) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (120, 90, 60)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def store(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "evidence_enabled", True, raising=False)
    monkeypatch.setattr(settings, "evidence_retention_days", 1825, raising=False)
    monkeypatch.setattr(settings, "evidence_purge_metadata", False, raising=False)
    monkeypatch.setattr(settings, "evidence_max_frame_px", 640, raising=False)
    db_url = f"sqlite:///{tmp_path / 'evidence.sqlite3'}"
    return EvidenceStore(database_url=db_url, root=str(tmp_path / "evidence"))


def test_capture_is_opt_in(tmp_path, monkeypatch):
    """The standard product must keep its no-raw-image-retention property."""
    settings = get_settings()
    monkeypatch.setattr(settings, "evidence_enabled", False, raising=False)
    store = EvidenceStore(
        database_url=f"sqlite:///{tmp_path / 'off.sqlite3'}", root=str(tmp_path / "off")
    )

    written = store.store_frames(uuid4(), "document", [_jpeg()])

    assert written == 0, "evidence must not be retained unless explicitly enabled"


def test_frames_are_stored_and_readable(store):
    session_id = uuid4()

    written = store.store_frames(session_id, "document", [_jpeg()], user_id="traveller-1")

    assert written == 1
    frames = store.list_frames(session_id)
    assert len(frames) == 1
    assert frames[0].step == "document"
    assert store.read_frame_bytes(frames[0]) is not None


def test_frames_are_downscaled_to_bound_the_archive(store):
    """At ~500 crossings/day the archive size is dominated by frame size."""
    session_id = uuid4()
    original = _jpeg(3000, 2200)

    store.store_frames(session_id, "document", [original])

    stored = store.list_frames(session_id)[0]
    assert stored.byte_size < len(original), "frames should be re-compressed on write"
    image = Image.open(BytesIO(store.read_frame_bytes(stored)))
    assert max(image.size) <= 640


def test_every_step_can_be_captured(store):
    session_id = uuid4()
    for step in ("document", "active_liveness", "hand_gesture", "selfie"):
        store.store_frames(session_id, step, [_jpeg()], label="blink")

    steps = {frame.step for frame in store.list_frames(session_id)}
    assert steps == {"document", "active_liveness", "hand_gesture", "selfie"}


def test_timeline_records_the_action_sequence(store):
    session_id = uuid4()
    store.record_event(session_id, "document", "upload", outcome="passed")
    store.record_event(session_id, "active_liveness", "blink", outcome="rejected",
                       reason_codes=["ACTIVE_LIVENESS_FACE_MISMATCH"])

    events = store.list_events(session_id)
    assert [event.action for event in events] == ["upload", "blink"]
    assert events[1].outcome == "rejected"


def test_viewing_evidence_is_audited(store):
    """Border systems are audited on who accessed a traveller's record."""
    session_id = uuid4()
    store.record_access(session_id, "officer-1", "view", client_ip="10.0.0.5")

    access = store.list_access(session_id)
    assert len(access) == 1
    assert access[0].actor == "officer-1"
    assert access[0].client_ip == "10.0.0.5"


def test_expired_media_is_deleted_but_the_crossing_record_survives(store):
    """Five-year media expiry must not erase the record that a crossing happened."""
    session_id = uuid4()
    store.store_frames(session_id, "document", [_jpeg()])
    frame = store.list_frames(session_id)[0]
    path = Path(frame.path)
    assert path.exists()

    # Simulate the retention window elapsing.
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(store._engine) as db:  # noqa: SLF001 - test reaches into storage on purpose
        record = db.get(type(frame), frame.id)
        record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

    result = store.purge_expired()

    assert result["files_removed"] == 1
    assert not path.exists(), "expired biometric media must be deleted from disk"
    remaining = store.list_frames(session_id)
    assert len(remaining) == 1, "the crossing record itself is retained"
    assert remaining[0].path == "" and remaining[0].byte_size == 0


def test_unexpired_media_is_left_alone(store):
    session_id = uuid4()
    store.store_frames(session_id, "document", [_jpeg()])

    result = store.purge_expired()

    assert result["files_removed"] == 0
    assert Path(store.list_frames(session_id)[0].path).exists()


def test_storage_failure_never_breaks_verification(store, monkeypatch):
    """Evidence capture is fail-open: a full disk must not stop a traveller."""
    monkeypatch.setattr(store, "_root", Path("/proc/cannot/write/here"))

    assert store.store_frames(uuid4(), "document", [_jpeg()]) == 0


def test_summary_reports_archive_size(store):
    session_id = uuid4()
    store.store_frames(session_id, "document", [_jpeg(), _jpeg()])

    summary = store.summary()

    assert summary["enabled"] is True
    assert summary["frame_count"] == 2
    assert summary["session_count"] == 1
    assert summary["retention_days"] == 1825
