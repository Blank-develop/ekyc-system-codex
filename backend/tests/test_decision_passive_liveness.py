from __future__ import annotations

from app.models.schemas import Decision, DocumentAnalysis
from app.services.session_store import VerificationStore


def _session_with_all_steps_passed() -> tuple[VerificationStore, object]:
    store = VerificationStore()
    created = store.create("user-decide")
    store.set_document(created.session_id, DocumentAnalysis(status="passed"))
    sess = store.get(created.session_id)
    for c in sess.active_challenges:
        c.passed = True
    sess.biometric.active_liveness_passed = True
    for c in sess.hand_challenges:
        c.passed = True
    sess.biometric.hand_challenge_passed = True
    sess.biometric.face_match_score = 0.78
    return store, sess


def test_selfie_passed_with_borderline_risk_completes_verification() -> None:
    # Selfie analysis accepted it (passive_liveness_passed=True) even though the
    # raw risk (0.48) is above the old 0.34 decision cutoff. Must now PASS.
    store, sess = _session_with_all_steps_passed()
    sess.biometric.passive_liveness_passed = True
    sess.biometric.passive_liveness_risk = 0.48
    result = store._decide(sess)
    assert "PASSIVE_LIVENESS_REQUIRED" not in result.reason_codes
    assert result.decision == Decision.passed


def test_selfie_not_passed_keeps_pending() -> None:
    store, sess = _session_with_all_steps_passed()
    sess.biometric.passive_liveness_passed = False
    sess.biometric.passive_liveness_risk = 0.48
    result = store._decide(sess)
    assert "PASSIVE_LIVENESS_REQUIRED" in result.reason_codes
    assert result.decision == Decision.pending
