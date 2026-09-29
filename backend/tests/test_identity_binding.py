"""Identity binding across the interactive verification steps.

Without this binding the pipeline only proves that *a* live human completed the
liveness/gesture challenges and that *someone* matching the passport took the
selfie -- so one person could perform the challenges and another supply the
selfie. Every interactive step is therefore matched back to the document
portrait, which transitively binds the whole session to a single identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.api.routes import _bind_step_to_document_face, store
from app.services.selfie import LIVE_STEP_FACE_MATCH_THRESHOLD


@dataclass
class _FaceResult:
    """Minimal stand-in for OpenCvFaceRecognizer's result."""

    embedding: list[float] | None = None
    checks: dict = field(default_factory=dict)


def _unit(*values: float) -> list[float]:
    norm = sum(value * value for value in values) ** 0.5
    return [value / norm for value in values]


def _seed_document_face(embedding: list[float]):
    session_id = uuid4()
    store.set_document_face_embedding(session_id, embedding)
    return session_id


def test_matching_face_binds_step_to_document():
    reference = _unit(1.0, 0.0, 0.0)
    session_id = _seed_document_face(reference)

    score, signal, checks = _bind_step_to_document_face(
        session_id, [_FaceResult(embedding=reference)], "active_liveness"
    )

    assert signal is None
    assert score is not None and score >= LIVE_STEP_FACE_MATCH_THRESHOLD
    assert checks["active_liveness_face_match_checked"] is True


def test_different_person_is_rejected_with_high_severity():
    """Mr. B performing the challenge on Mr. A's document must hard-fail."""
    session_id = _seed_document_face(_unit(1.0, 0.0, 0.0))

    # Orthogonal embedding -> cosine 0 -> similarity 0.5, below the threshold.
    score, signal, _ = _bind_step_to_document_face(
        session_id, [_FaceResult(embedding=_unit(0.0, 1.0, 0.0))], "active_liveness"
    )

    assert signal is not None, "a mismatched face must raise a signal"
    assert signal.code == "ACTIVE_LIVENESS_FACE_MISMATCH"
    assert signal.severity == "high", "mismatch must hard-fail the step"
    assert score is not None and score < LIVE_STEP_FACE_MATCH_THRESHOLD


def test_best_matching_frame_wins():
    """A genuine user may have one poor frame; the best frame should decide."""
    reference = _unit(1.0, 0.0, 0.0)
    session_id = _seed_document_face(reference)

    score, signal, _ = _bind_step_to_document_face(
        session_id,
        [_FaceResult(embedding=_unit(0.0, 1.0, 0.0)), _FaceResult(embedding=reference)],
        "active_liveness",
    )

    assert signal is None
    assert score is not None and score >= LIVE_STEP_FACE_MATCH_THRESHOLD


def test_gesture_step_uses_its_own_reason_code():
    session_id = _seed_document_face(_unit(1.0, 0.0, 0.0))

    _, signal, _ = _bind_step_to_document_face(
        session_id, [_FaceResult(embedding=_unit(0.0, 1.0, 0.0))], "hand_gesture"
    )

    assert signal is not None
    assert signal.code == "HAND_GESTURE_FACE_MISMATCH"


def test_no_face_in_step_is_not_a_mismatch():
    """The hand can occlude the face mid-gesture; absence of a face is not proof
    of a different person, and is handled by the per-step presence checks."""
    session_id = _seed_document_face(_unit(1.0, 0.0, 0.0))

    score, signal, checks = _bind_step_to_document_face(
        session_id, [_FaceResult(embedding=None)], "hand_gesture"
    )

    assert signal is None
    assert score is None
    assert checks["hand_gesture_face_match_checked"] is False


def test_missing_document_portrait_does_not_crash():
    score, signal, checks = _bind_step_to_document_face(
        uuid4(), [_FaceResult(embedding=_unit(1.0, 0.0, 0.0))], "active_liveness"
    )

    assert signal is None
    assert score is None
    assert checks["active_liveness_face_match_checked"] is False
