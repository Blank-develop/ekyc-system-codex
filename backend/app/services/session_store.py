from __future__ import annotations

import hashlib
import hmac
import random
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.models.schemas import (
    BiometricAnalysis,
    Challenge,
    ChallengeType,
    CompleteChallengeRequest,
    Decision,
    DocumentAnalysis,
    FraudSignal,
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
    ("point", "Point up", "Point one finger inside the circle."),
    ("peace", "Peace sign", "Show a peace sign inside the circle."),
    ("victory", "Victory sign", "Show a V sign inside the circle."),
    ("open_palm", "Open palm", "Show your open palm inside the circle."),
    ("high_five", "High five", "Show a high-five palm inside the circle."),
    ("stop", "Stop sign", "Show a stop hand inside the circle."),
    ("fist", "Fist", "Close your hand into a fist inside the circle."),
    ("thumb_up", "Thumb up", "Show a thumbs-up gesture inside the circle."),
    ("ok", "OK sign", "Make the OK gesture inside the circle."),
    ("pinch", "Pinch", "Touch your thumb and index finger inside the circle."),
    ("small_ok", "Small OK", "Make a small OK sign inside the circle."),
    ("rock_on", "Rock on", "Show index and pinky fingers inside the circle."),
    ("call_me", "Call me", "Show thumb and pinky inside the circle."),
    ("thumb_down", "Thumb down", "Show a thumbs-down gesture inside the circle."),
    ("i_love_you", "I love you", "Show the I love you hand sign inside the circle."),
    ("l_shape", "L shape", "Make an L with your thumb and index finger inside the circle."),
    ("pinched_fingers", "Pinched fingers", "Bring all your fingertips together pointing up inside the circle."),
    ("crossed_fingers", "Crossed fingers", "Cross your index and middle fingers inside the circle."),
]

# Gestures that need finger dexterity many users find awkward. Each session keeps
# at most one of these so the challenge stays easy to complete.
TRICKY_HAND_GESTURE_IDS = {"rock_on", "call_me", "i_love_you", "thumb_down", "crossed_fingers"}


def sample_hand_prompts(count: int = 3) -> list[tuple[str, str, str]]:
    easy = [prompt for prompt in HAND_PROMPTS if prompt[0] not in TRICKY_HAND_GESTURE_IDS]
    picks = random.sample(easy, min(count - 1, len(easy)))
    remaining = [prompt for prompt in HAND_PROMPTS if prompt not in picks]
    picks.extend(random.sample(remaining, count - len(picks)))
    random.shuffle(picks)
    return picks


class VerificationStore:
    def __init__(self) -> None:
        self._sessions: dict[UUID, VerificationResult] = {}
        self._document_face_embeddings: dict[UUID, list[float]] = {}
        self._selfie_face_embeddings: dict[UUID, list[float]] = {}
        # Per-session client-binding tokens (never persisted on the result object).
        self._tokens: dict[UUID, str] = {}
        # Per-session contact-confirmation challenges (IAL2 enrollment code).
        self._contact_challenges: dict[UUID, dict] = {}

    @staticmethod
    def _hash_code(session_id: UUID, code: str) -> str:
        return hashlib.sha256(f"{session_id}:{code}".encode()).hexdigest()

    def set_contact_challenge(self, session_id: UUID, channel: str, destination: str,
                              code: str, ttl_minutes: int, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._contact_challenges[session_id] = {
            "channel": channel,
            "destination": destination,
            "code_hash": self._hash_code(session_id, code),
            "expires_at": now + timedelta(minutes=ttl_minutes),
            "attempts": 0,
        }

    def verify_contact_code(self, session_id: UUID, code: str, max_attempts: int,
                            now: datetime | None = None) -> tuple[bool, str]:
        now = now or datetime.now(timezone.utc)
        challenge = self._contact_challenges.get(session_id)
        if challenge is None:
            return False, "NO_CONTACT_CHALLENGE"
        if now > challenge["expires_at"]:
            self._contact_challenges.pop(session_id, None)
            return False, "CODE_EXPIRED"
        if challenge["attempts"] >= max_attempts:
            self._contact_challenges.pop(session_id, None)
            return False, "TOO_MANY_ATTEMPTS"
        code_hash = challenge.get("code_hash")
        if not code_hash:
            # Already consumed by a successful confirmation.
            return False, "CODE_ALREADY_USED"
        challenge["attempts"] += 1
        if not hmac.compare_digest(code_hash, self._hash_code(session_id, code)):
            return False, "CODE_INVALID"
        session = self._sessions.get(session_id)
        if session is not None:
            session.contact_confirmed = True
            session.updated_at = now
        # Keep the destination for the notification-of-proofing step; drop the code.
        challenge.pop("code_hash", None)
        return True, "OK"

    def contact_destination(self, session_id: UUID) -> tuple[str, str] | None:
        challenge = self._contact_challenges.get(session_id)
        if challenge is None:
            return None
        return challenge["channel"], challenge["destination"]

    def reevaluate(self, session_id: UUID) -> VerificationResult:
        """Re-run the decision engine after a non-store-mediated state change."""
        return self._decide(self._sessions[session_id])

    # --- Session lifecycle / security ----------------------------------------

    def session_token(self, session_id: UUID) -> str | None:
        return self._tokens.get(session_id)

    def validate_token(self, session_id: UUID, token: str | None) -> bool:
        expected = self._tokens.get(session_id)
        if not expected or not token:
            return False
        return secrets.compare_digest(token, expected)

    def is_expired(self, session_id: UUID, now: datetime | None = None) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return True
        now = now or datetime.now(timezone.utc)
        settings = get_settings()
        idle = timedelta(minutes=settings.session_idle_ttl_minutes)
        absolute = timedelta(minutes=settings.session_absolute_ttl_minutes)
        return (now - session.updated_at) > idle or (now - session.created_at) > absolute

    def drop(self, session_id: UUID) -> None:
        self._sessions.pop(session_id, None)
        self._tokens.pop(session_id, None)
        self._contact_challenges.pop(session_id, None)
        self._document_face_embeddings.pop(session_id, None)
        self._selfie_face_embeddings.pop(session_id, None)

    def prune_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        expired = [sid for sid in list(self._sessions) if self.is_expired(sid, now)]
        for sid in expired:
            self.drop(sid)
        return len(expired)

    def create(self, user_id: str) -> VerificationResult:
        self.prune_expired()  # bound memory: sweep stale sessions on each creation
        now = datetime.now(timezone.utc)
        active = [
            Challenge(id=key, type=ChallengeType.active_liveness, prompt=prompt, instruction=instruction)
            for key, prompt, instruction in random.sample(ACTIVE_PROMPTS, 3)
        ]
        hands = [
            Challenge(
                id=key,
                type=ChallengeType.hand_gesture,
                prompt=prompt,
                instruction=instruction,
                image_url=f"/gestures/{key}.png",
                nonce=secrets.token_urlsafe(16),
            )
            for key, prompt, instruction in sample_hand_prompts(3)
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
        self._tokens[result.session_id] = secrets.token_urlsafe(32)
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
        for challenge in session.hand_challenges:
            if challenge.id == payload.challenge_id:
                challenge.passed = payload.passed
                if payload.passed:
                    # Consume the one-time nonce so the completion cannot be replayed.
                    challenge.nonce = None
        session.biometric.hand_challenge_passed = all(challenge.passed for challenge in session.hand_challenges)
        session.updated_at = datetime.now(timezone.utc)
        return self._decide(session)

    def complete_active_challenge_with_evidence(
        self,
        session_id: UUID,
        payload: CompleteChallengeRequest,
        checks: dict[str, float | int | str | bool | None],
        signals: list[FraudSignal],
    ) -> VerificationResult:
        session = self.get(session_id)
        previous_replay_signals = [
            signal
            for signal in session.biometric.active_liveness_signals
            if signal.code == "ACTIVE_LIVENESS_REPLAY_DETECTED" and signal.severity == "high"
        ]
        if previous_replay_signals:
            if self._is_clean_active_liveness_recovery(payload, checks, signals):
                checks = {**checks, "active_liveness_replay_recovered": True}
                signals = []
            else:
                checks = {
                    **checks,
                    "active_liveness_replay_lock": True,
                    "active_liveness_replay_lock_reason": previous_replay_signals[0].code,
                }
                signals = [*previous_replay_signals, *[signal for signal in signals if signal.code != "ACTIVE_LIVENESS_REPLAY_DETECTED"]]
        session.biometric.active_liveness_checks = checks
        session.biometric.active_liveness_signals = signals
        for challenge in session.active_challenges:
            if challenge.id == payload.challenge_id:
                challenge.passed = payload.passed and not signals
        session.biometric.active_liveness_passed = all(challenge.passed for challenge in session.active_challenges)
        session.updated_at = datetime.now(timezone.utc)
        return self._decide(session)

    @staticmethod
    def _active_check(checks: dict[str, float | int | str | bool | None], key: str, default: float = 1.0) -> float:
        value = checks.get(key)
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        return default

    @classmethod
    def _is_clean_active_liveness_recovery(
        cls,
        payload: CompleteChallengeRequest,
        checks: dict[str, float | int | str | bool | None],
        signals: list[FraudSignal],
    ) -> bool:
        if not payload.passed or signals:
            return False
        return (
            cls._active_check(checks, "active_liveness_screen_frame_score") <= 0.24
            and cls._active_check(checks, "active_liveness_display_surface_score") <= 0.6
            and cls._active_check(checks, "active_liveness_paper_photo_score") <= 0.34
            and cls._active_check(checks, "active_liveness_heuristic_spoof_risk") <= 0.44
        )

    def set_selfie(self, session_id: UUID, payload: SelfieAnalysisRequest) -> VerificationResult:
        session = self.get(session_id)
        score = payload.face_match_score if payload.face_match_score is not None else 0.86
        passive_risk = payload.passive_liveness_risk if payload.passive_liveness_risk is not None else 0.18 if payload.passive_liveness_passed else 0.86
        session.biometric = BiometricAnalysis(
            active_liveness_passed=session.biometric.active_liveness_passed,
            hand_challenge_passed=session.biometric.hand_challenge_passed,
            active_liveness_checks=session.biometric.active_liveness_checks,
            active_liveness_signals=session.biometric.active_liveness_signals,
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
        for signal in session.biometric.active_liveness_signals:
            if signal.severity == "high":
                reasons.append(signal.code)
        if not session.biometric.hand_challenge_passed:
            reasons.append("HAND_GESTURE_REQUIRED")
        for signal in session.biometric.selfie_signals:
            if signal.severity == "high":
                reasons.append(signal.code)
        if session.biometric.face_match_score and session.biometric.face_match_score < settings.min_face_match_score:
            reasons.append("FACE_MATCH_LOW")
        # Trust the selfie analysis's holistic verdict (which already applies the
        # risk cap plus every hard anti-spoof cue) instead of re-thresholding the
        # raw risk with a different, stricter cutoff — those two disagreeing left
        # genuine selfies stuck "pending".
        if not session.biometric.passive_liveness_passed:
            reasons.append("PASSIVE_LIVENESS_REQUIRED")
        # IAL2 step 5: confirmed address/phone (only when enabled).
        if settings.require_contact_confirmation and not session.contact_confirmed:
            reasons.append("CONTACT_CONFIRMATION_REQUIRED")

        incomplete = {"DOCUMENT_REQUIRED", "ACTIVE_LIVENESS_REQUIRED", "HAND_GESTURE_REQUIRED",
                      "PASSIVE_LIVENESS_REQUIRED", "CONTACT_CONFIRMATION_REQUIRED"}
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
