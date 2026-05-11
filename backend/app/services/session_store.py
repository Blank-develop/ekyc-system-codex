from __future__ import annotations

import random
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.models.schemas import (
    BiometricAnalysis,
    Challenge,
    ChallengeType,
    CompleteChallengeRequest,
    Decision,
    DocumentAnalysis,
    SelfieAnalysisRequest,
    VerificationResult,
)


ACTIVE_PROMPTS = [
    ("turn_left", "Turn left", "Slowly turn your head to the left."),
    ("turn_right", "Turn right", "Slowly turn your head to the right."),
    ("blink", "Blink twice", "Blink twice while keeping your face visible."),
    ("open_mouth", "Open mouth", "Open your mouth briefly, then close it."),
]

HAND_PROMPTS = [
    ("one", "Show 1", "Raise one finger inside the circle."),
    ("two", "Show 2", "Raise two fingers inside the circle."),
    ("three", "Show 3", "Raise three fingers inside the circle."),
    ("four", "Show 4", "Raise four fingers inside the circle."),
    ("five", "Show 5", "Show an open palm inside the circle."),
    ("ok", "OK sign", "Make the OK gesture inside the circle."),
    ("thumb_down", "Thumb down", "Show a thumbs-down gesture inside the circle."),
    ("i_love_you", "I love you", "Show the I love you hand sign inside the circle."),
]


class VerificationStore:
    def __init__(self) -> None:
        self._sessions: dict[UUID, VerificationResult] = {}
        self._document_face_embeddings: dict[UUID, list[float]] = {}
        self._selfie_face_embeddings: dict[UUID, list[float]] = {}

    def create(self, user_id: str) -> VerificationResult:
        now = datetime.now(timezone.utc)
        active = [
            Challenge(id=key, type=ChallengeType.active_liveness, prompt=prompt, instruction=instruction)
            for key, prompt, instruction in random.sample(ACTIVE_PROMPTS, 3)
        ]
        hands = [
            Challenge(id=key, type=ChallengeType.hand_gesture, prompt=prompt, instruction=instruction)
            for key, prompt, instruction in random.sample(HAND_PROMPTS, 3)
        ]
        result = VerificationResult(
            session_id=uuid4(),
            user_id=user_id.strip(),
            created_at=now,
            updated_at=now,
            active_challenges=active,
            hand_challenges=hands,
        )
        self._sessions[result.session_id] = result
        return result

    def get(self, session_id: UUID) -> VerificationResult:
        return self._sessions[session_id]

    def set_document(self, session_id: UUID, analysis: DocumentAnalysis) -> VerificationResult:
        session = self.get(session_id)
        session.document = analysis
        session.updated_at = datetime.now(timezone.utc)
        return self._decide(session)

    def set_document_face_embedding(self, session_id: UUID, embedding: list[float] | None) -> None:
        if embedding is None:
            self._document_face_embeddings.pop(session_id, None)
        else:
            self._document_face_embeddings[session_id] = embedding

    def get_document_face_embedding(self, session_id: UUID) -> list[float] | None:
        return self._document_face_embeddings.get(session_id)

    def set_selfie_face_embedding(self, session_id: UUID, embedding: list[float] | None) -> None:
        if embedding is None:
            self._selfie_face_embeddings.pop(session_id, None)
        else:
            self._selfie_face_embeddings[session_id] = embedding

    def get_selfie_face_embedding(self, session_id: UUID) -> list[float] | None:
        return self._selfie_face_embeddings.get(session_id)

    def complete_challenge(self, session_id: UUID, payload: CompleteChallengeRequest) -> VerificationResult:
        session = self.get(session_id)
        for challenge in [*session.active_challenges, *session.hand_challenges]:
            if challenge.id == payload.challenge_id:
                challenge.passed = payload.passed
        session.biometric.active_liveness_passed = all(challenge.passed for challenge in session.active_challenges)
        session.biometric.hand_challenge_passed = all(challenge.passed for challenge in session.hand_challenges)
        session.updated_at = datetime.now(timezone.utc)
        return self._decide(session)

    def set_selfie(self, session_id: UUID, payload: SelfieAnalysisRequest) -> VerificationResult:
        session = self.get(session_id)
        score = payload.face_match_score if payload.face_match_score is not None else 0.86
        passive_risk = payload.passive_liveness_risk if payload.passive_liveness_risk is not None else 0.18 if payload.passive_liveness_passed else 0.86
        session.biometric = BiometricAnalysis(
            active_liveness_passed=session.biometric.active_liveness_passed,
            hand_challenge_passed=session.biometric.hand_challenge_passed,
            passive_liveness_passed=payload.passive_liveness_passed,
            face_match_score=round(score, 2),
            passive_liveness_risk=round(passive_risk, 2),
            selfie_quality_score=round(payload.selfie_quality_score or 0.0, 2),
            selfie_checks=payload.selfie_checks,
            selfie_signals=payload.selfie_signals,
        )
        session.updated_at = datetime.now(timezone.utc)
        return self._decide(session)

    def _decide(self, session: VerificationResult) -> VerificationResult:
        settings = get_settings()
        reasons: list[str] = []

        if session.document.status == "rejected":
            reasons.append("DOCUMENT_FRAUD_OR_QUALITY_FAILED")
        for signal in session.document.signals:
            if signal.severity == "high":
                reasons.append(signal.code)
        if session.document.status == "pending":
            reasons.append("DOCUMENT_REQUIRED")
        if session.document.fraud_risk_score > settings.max_document_fraud_risk:
            reasons.append("DOCUMENT_FRAUD_RISK_HIGH")
        if not session.biometric.active_liveness_passed:
            reasons.append("ACTIVE_LIVENESS_REQUIRED")
        if not session.biometric.hand_challenge_passed:
            reasons.append("HAND_GESTURE_REQUIRED")
        for signal in session.biometric.selfie_signals:
            if signal.severity == "high":
                reasons.append(signal.code)
        if session.biometric.face_match_score and session.biometric.face_match_score < settings.min_face_match_score:
            reasons.append("FACE_MATCH_LOW")
        if session.biometric.passive_liveness_risk > settings.max_passive_liveness_risk:
            reasons.append("PASSIVE_LIVENESS_REQUIRED")

        incomplete = {"DOCUMENT_REQUIRED", "ACTIVE_LIVENESS_REQUIRED", "HAND_GESTURE_REQUIRED", "PASSIVE_LIVENESS_REQUIRED"}
        hard_fail = [reason for reason in reasons if reason not in incomplete]

        if hard_fail:
            session.decision = Decision.rejected
        elif not reasons:
            session.decision = Decision.passed
        else:
            session.decision = Decision.pending

        session.reason_codes = reasons
        return session


store = VerificationStore()
