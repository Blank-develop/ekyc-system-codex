from __future__ import annotations

from app.api.routes import _has_strong_active_replay_evidence, active_liveness_quality_spoof_signals
from app.models.schemas import CompleteChallengeRequest, Decision, DocumentAnalysis, FraudSignal
from app.services.session_store import VerificationStore


def _codes(signals) -> set[str]:
    return {signal.code for signal in signals}


def test_printed_photo_held_at_distance_is_rejected_for_small_face() -> None:
    # Printed photo held at arm's length: small face, high model risk.
    signals, diagnostics = active_liveness_quality_spoof_signals(
        face_width_ratios=[0.13, 0.12, 0.14],
        model_risks=[0.89, 0.92, 0.85],
    )
    assert "ACTIVE_LIVENESS_FACE_TOO_SMALL" in _codes(signals)
    assert diagnostics["active_liveness_small_face_count"] == 3


def test_recurring_model_spoof_blocks_even_with_adequate_face() -> None:
    signals, _ = active_liveness_quality_spoof_signals(
        face_width_ratios=[0.30, 0.31, 0.29],
        model_risks=[0.88, 0.91, 0.40],
    )
    assert "ACTIVE_LIVENESS_MODEL_SPOOF_HIGH" in _codes(signals)


def test_single_model_spike_does_not_block_real_user_burst() -> None:
    # One noisy frame out of three on an adequately sized face is webcam noise.
    signals, _ = active_liveness_quality_spoof_signals(
        face_width_ratios=[0.30, 0.31, 0.29],
        model_risks=[0.90, 0.20, 0.18],
    )
    assert signals == []


def test_clean_real_user_burst_passes_quality_gate() -> None:
    signals, diagnostics = active_liveness_quality_spoof_signals(
        face_width_ratios=[0.30, 0.32, 0.31],
        model_risks=[0.20, 0.18, 0.22],
    )
    assert signals == []
    assert diagnostics["active_liveness_small_face_count"] == 0


def test_generic_challenge_completion_cannot_pass_active_liveness() -> None:
    store = VerificationStore()
    session = store.create("user-active")
    challenge_id = session.active_challenges[0].id

    result = store.complete_challenge(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=True),
    )

    assert result.active_challenges[0].passed is False
    assert result.biometric.active_liveness_passed is False
    assert "ACTIVE_LIVENESS_REQUIRED" in result.reason_codes


def test_active_liveness_replay_signal_blocks_challenge_pass() -> None:
    store = VerificationStore()
    session = store.create("user-replay")
    store.set_document(session.session_id, DocumentAnalysis(status="passed"))
    challenge_id = session.active_challenges[0].id

    result = store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=False),
        checks={"active_liveness_passive_liveness_risk": 0.91},
        signals=[
            FraudSignal(
                code="ACTIVE_LIVENESS_REPLAY_DETECTED",
                label="Possible screen replay detected.",
                severity="high",
                score=0.91,
            )
        ],
    )

    assert result.active_challenges[0].passed is False
    assert result.biometric.active_liveness_passed is False
    assert result.decision == Decision.rejected
    assert "ACTIVE_LIVENESS_REPLAY_DETECTED" in result.reason_codes


def test_active_liveness_replay_rejection_cannot_be_cleared_by_weak_retry() -> None:
    store = VerificationStore()
    session = store.create("user-replay-retry")
    store.set_document(session.session_id, DocumentAnalysis(status="passed"))
    challenge_id = session.active_challenges[0].id

    store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=False),
        checks={"active_liveness_passive_liveness_risk": 0.91},
        signals=[
            FraudSignal(
                code="ACTIVE_LIVENESS_REPLAY_DETECTED",
                label="Possible screen replay detected.",
                severity="high",
                score=0.91,
            )
        ],
    )

    result = store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=True),
        checks={
            "active_liveness_passive_liveness_risk": 0.42,
            "active_liveness_model_spoof_risk": 0.52,
            "active_liveness_screen_frame_score": 0.19,
            "active_liveness_display_surface_score": 0.04,
            "active_liveness_paper_photo_score": 0.03,
            "active_liveness_heuristic_spoof_risk": 0.18,
        },
        signals=[],
    )

    assert result.active_challenges[0].passed is False
    assert result.biometric.active_liveness_passed is False
    assert result.decision == Decision.rejected
    assert "ACTIVE_LIVENESS_REPLAY_DETECTED" in result.reason_codes
    assert result.biometric.active_liveness_signals[0].code == "ACTIVE_LIVENESS_REPLAY_DETECTED"


def test_active_liveness_replay_rejection_cannot_be_cleared_by_strong_display_retry() -> None:
    store = VerificationStore()
    session = store.create("user-replay-display-retry")
    store.set_document(session.session_id, DocumentAnalysis(status="passed"))
    challenge_id = session.active_challenges[0].id

    store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=False),
        checks={"active_liveness_passive_liveness_risk": 0.91},
        signals=[
            FraudSignal(
                code="ACTIVE_LIVENESS_REPLAY_DETECTED",
                label="Possible screen replay detected.",
                severity="high",
                score=0.91,
            )
        ],
    )

    result = store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=True),
        checks={
            "active_liveness_passive_liveness_risk": 0.78,
            "active_liveness_model_spoof_risk": 0.86,
            "active_liveness_screen_frame_score": 0.36,
            "active_liveness_display_surface_score": 0.64,
            "active_liveness_paper_photo_score": 0.02,
            "active_liveness_heuristic_spoof_risk": 0.36,
        },
        signals=[],
    )

    assert result.active_challenges[0].passed is False
    assert result.biometric.active_liveness_passed is False
    assert result.decision == Decision.rejected
    assert "ACTIVE_LIVENESS_REPLAY_DETECTED" in result.reason_codes
    assert result.biometric.active_liveness_checks["active_liveness_replay_lock"] is True


def test_active_liveness_medium_display_retry_can_recover_real_user() -> None:
    store = VerificationStore()
    session = store.create("user-replay-medium-display-retry")
    store.set_document(session.session_id, DocumentAnalysis(status="passed"))
    challenge_id = session.active_challenges[0].id

    store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=False),
        checks={"active_liveness_passive_liveness_risk": 0.91},
        signals=[
            FraudSignal(
                code="ACTIVE_LIVENESS_REPLAY_DETECTED",
                label="Possible screen replay detected.",
                severity="high",
                score=0.91,
            )
        ],
    )

    result = store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=True),
        checks={
            "active_liveness_passive_liveness_risk": 0.72,
            "active_liveness_model_spoof_risk": 0.84,
            "active_liveness_screen_frame_score": 0.08,
            "active_liveness_display_surface_score": 0.46,
            "active_liveness_paper_photo_score": 0.02,
            "active_liveness_heuristic_spoof_risk": 0.28,
        },
        signals=[],
    )

    assert result.active_challenges[0].passed is True
    assert result.biometric.active_liveness_signals == []
    assert result.biometric.active_liveness_checks["active_liveness_replay_recovered"] is True


def test_active_liveness_clean_real_face_retry_can_recover_after_replay() -> None:
    store = VerificationStore()
    session = store.create("user-replay-clean-retry")
    store.set_document(session.session_id, DocumentAnalysis(status="passed"))
    challenge_id = session.active_challenges[0].id

    store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=False),
        checks={"active_liveness_passive_liveness_risk": 0.91},
        signals=[
            FraudSignal(
                code="ACTIVE_LIVENESS_REPLAY_DETECTED",
                label="Possible screen replay detected.",
                severity="high",
                score=0.91,
            )
        ],
    )

    result = store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=True),
        checks={
            "active_liveness_passive_liveness_risk": 0.08,
            "active_liveness_model_spoof_risk": 0.12,
            "active_liveness_screen_frame_score": 0.02,
            "active_liveness_display_surface_score": 0.01,
            "active_liveness_paper_photo_score": 0.01,
            "active_liveness_heuristic_spoof_risk": 0.04,
        },
        signals=[],
    )

    assert result.active_challenges[0].passed is True
    assert result.biometric.active_liveness_signals == []
    assert result.biometric.active_liveness_checks["active_liveness_replay_recovered"] is True


def test_active_liveness_clean_retry_can_recover_despite_model_false_positive() -> None:
    store = VerificationStore()
    session = store.create("user-replay-clean-model-noise")
    store.set_document(session.session_id, DocumentAnalysis(status="passed"))
    challenge_id = session.active_challenges[0].id

    store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=False),
        checks={"active_liveness_passive_liveness_risk": 0.91},
        signals=[
            FraudSignal(
                code="ACTIVE_LIVENESS_REPLAY_DETECTED",
                label="Possible screen replay detected.",
                severity="high",
                score=0.91,
            )
        ],
    )

    result = store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=True),
        checks={
            "active_liveness_passive_liveness_risk": 0.96,
            "active_liveness_model_spoof_risk": 0.96,
            "active_liveness_screen_frame_score": 0.05,
            "active_liveness_display_surface_score": 0.04,
            "active_liveness_paper_photo_score": 0.02,
            "active_liveness_heuristic_spoof_risk": 0.09,
        },
        signals=[],
    )

    assert result.active_challenges[0].passed is True
    assert result.biometric.active_liveness_signals == []
    assert result.biometric.active_liveness_checks["active_liveness_replay_recovered"] is True


def test_active_liveness_evidence_can_pass_current_challenge() -> None:
    store = VerificationStore()
    session = store.create("user-live")
    store.set_document(session.session_id, DocumentAnalysis(status="passed"))
    challenge_id = session.active_challenges[0].id

    result = store.complete_active_challenge_with_evidence(
        session.session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=True),
        checks={"active_liveness_passive_liveness_risk": 0.12},
        signals=[],
    )

    assert result.active_challenges[0].passed is True
    assert result.biometric.active_liveness_checks["active_liveness_passive_liveness_risk"] == 0.12
    assert result.biometric.active_liveness_signals == []


def test_active_liveness_model_risk_alone_does_not_block_real_user() -> None:
    assert _has_strong_active_replay_evidence(
        {
            "passive_spoof_screen_frame_score": 0.08,
            "passive_spoof_paper_photo_score": 0.05,
            "passive_spoof_model_risk": 0.9,
            "passive_spoof_heuristic_risk": 0.08,
        },
        risk=0.9,
    ) is False


def test_active_liveness_extreme_model_risk_alone_does_not_block_real_user() -> None:
    assert _has_strong_active_replay_evidence(
        {
            "passive_spoof_screen_frame_score": 0.08,
            "passive_spoof_display_surface_score": 0.04,
            "passive_spoof_paper_photo_score": 0.05,
            "passive_spoof_model_risk": 0.99,
            "passive_spoof_heuristic_risk": 0.08,
        },
        risk=0.99,
    ) is False


def test_active_liveness_extreme_model_risk_with_strong_display_cue_blocks_screen_replay() -> None:
    assert _has_strong_active_replay_evidence(
        {
            "passive_spoof_screen_frame_score": 0.34,
            "passive_spoof_display_surface_score": 0.64,
            "passive_spoof_paper_photo_score": 0.05,
            "passive_spoof_model_risk": 0.94,
            "passive_spoof_heuristic_risk": 0.34,
        },
        risk=0.94,
    ) is True


def test_active_liveness_possible_screen_frame_with_elevated_risk_blocks_replay() -> None:
    assert _has_strong_active_replay_evidence(
        {
            "passive_spoof_screen_frame_score": 0.45,
            "passive_spoof_paper_photo_score": 0.05,
            "passive_spoof_model_risk": 0.2,
            "passive_spoof_heuristic_risk": 0.43,
        },
        risk=0.52,
    ) is True


def test_active_liveness_display_surface_alone_does_not_block_real_user() -> None:
    assert _has_strong_active_replay_evidence(
        {
            "passive_spoof_screen_frame_score": 0.08,
            "passive_spoof_display_surface_score": 0.48,
            "passive_spoof_paper_photo_score": 0.03,
            "passive_spoof_model_risk": 0.18,
            "passive_spoof_heuristic_risk": 0.46,
        },
        risk=0.55,
    ) is False


def test_active_liveness_display_surface_with_screen_cue_blocks_replay() -> None:
    assert _has_strong_active_replay_evidence(
        {
            "passive_spoof_screen_frame_score": 0.34,
            "passive_spoof_display_surface_score": 0.64,
            "passive_spoof_paper_photo_score": 0.03,
            "passive_spoof_model_risk": 0.18,
            "passive_spoof_heuristic_risk": 0.46,
        },
        risk=0.65,
    ) is True


def test_active_liveness_strong_screen_evidence_blocks_replay() -> None:
    assert _has_strong_active_replay_evidence(
        {
            "passive_spoof_screen_frame_score": 0.7,
            "passive_spoof_paper_photo_score": 0.05,
            "passive_spoof_model_risk": 0.2,
            "passive_spoof_heuristic_risk": 0.1,
        },
        risk=0.7,
    ) is True
