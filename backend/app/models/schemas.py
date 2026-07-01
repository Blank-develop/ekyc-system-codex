from datetime import date, datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Decision(str, Enum):
    pending = "pending"
    passed = "passed"
    rejected = "rejected"


class ChallengeType(str, Enum):
    active_liveness = "active_liveness"
    hand_gesture = "hand_gesture"


class Challenge(BaseModel):
    id: str
    type: ChallengeType
    prompt: str
    instruction: str
    passed: bool = False
    # Server-issued one-time token; the client must echo it to complete the
    # challenge. Consumed on use (set to None) so a completion cannot be replayed.
    nonce: str | None = None


class OcrResult(BaseModel):
    document_type: Literal["passport", "lao_id_card"] = "passport"
    full_name: str | None = None
    document_number: str | None = None
    id_number: str | None = None
    passport_number: str | None = None
    nationality: str | None = None
    date_of_birth: date | None = None
    expiry_date: date | None = None
    confidence: float = 0.0
    mrz_text: str | None = None
    mrz_valid: bool | None = None
    mrz_check_digits_valid: bool | None = None
    extracted_fields: dict[str, str] = Field(default_factory=dict)


class FraudSignal(BaseModel):
    code: str
    label: str
    severity: Literal["low", "medium", "high"]
    score: float = Field(ge=0.0, le=1.0)


class DocumentAnalysis(BaseModel):
    status: Literal["pending", "passed", "rejected"] = "pending"
    image_quality_score: float = 0.0
    fraud_risk_score: float = 0.0
    document_likeness_score: float = 0.0
    recapture_risk_score: float = 0.0
    tamper_risk_score: float = 0.0
    ocr: OcrResult = Field(default_factory=OcrResult)
    signals: list[FraudSignal] = Field(default_factory=list)
    checks: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class BiometricAnalysis(BaseModel):
    active_liveness_passed: bool = False
    hand_challenge_passed: bool = False
    active_liveness_checks: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    active_liveness_signals: list[FraudSignal] = Field(default_factory=list)
    passive_liveness_passed: bool = False
    face_match_score: float = 0.0
    passive_liveness_risk: float = 1.0
    selfie_quality_score: float = 0.0
    selfie_checks: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    selfie_signals: list[FraudSignal] = Field(default_factory=list)


class VerificationResult(BaseModel):
    session_id: UUID
    user_id: str
    created_at: datetime
    updated_at: datetime
    decision: Decision = Decision.pending
    reason_codes: list[str] = Field(default_factory=list)
    document: DocumentAnalysis = Field(default_factory=DocumentAnalysis)
    biometric: BiometricAnalysis = Field(default_factory=BiometricAnalysis)
    active_challenges: list[Challenge] = Field(default_factory=list)
    hand_challenges: list[Challenge] = Field(default_factory=list)
    # Client-binding token, returned only when the session is created. Must be sent
    # back in the X-Session-Token header on subsequent session-scoped requests.
    session_token: str | None = None


class CreateVerificationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)


class CompleteChallengeRequest(BaseModel):
    challenge_id: str
    passed: bool
    nonce: str | None = None


class SelfieAnalysisRequest(BaseModel):
    passive_liveness_passed: bool = True
    face_match_score: float | None = Field(default=None, ge=0.0, le=1.0)
    passive_liveness_risk: float | None = Field(default=None, ge=0.0, le=1.0)
    selfie_quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    selfie_checks: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    selfie_signals: list[FraudSignal] = Field(default_factory=list)


class UserProfile(BaseModel):
    face_id: UUID
    user_id: str
    active: bool = True
    verification_session_id: UUID
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    age: int | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    passport_number: str | None = None
    passport_expiry: date | None = None
    enrolled_at: datetime
    last_login_at: datetime | None = None
    consent_version: str | None = None
    consented_at: datetime | None = None


class FaceEnrollmentResponse(BaseModel):
    enrolled: bool
    profile: UserProfile


class UserProfileListResponse(BaseModel):
    profiles: list[UserProfile] = Field(default_factory=list)


class DeleteProfileResponse(BaseModel):
    deleted: bool
    deleted_count: int = 0


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


class AuthUserInfo(BaseModel):
    username: str
    role: str


class AuditEventOut(BaseModel):
    seq: int
    event_time: datetime
    event_type: str
    actor: str | None = None
    action: str
    subject: str | None = None
    detail: dict | None = None
    entry_hash: str


class AuditListResponse(BaseModel):
    events: list[AuditEventOut] = Field(default_factory=list)


class AuditVerifyResponse(BaseModel):
    ok: bool
    entries: int
    broken_at: int | None = None


class ConsentInfo(BaseModel):
    version: str
    notice: str


class SelfServiceExportResponse(BaseModel):
    verified: bool
    match_score: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)
    profile: UserProfile | None = None


class SelfServiceDeleteResponse(BaseModel):
    verified: bool
    deleted: bool = False
    user_id: str | None = None
    reason_codes: list[str] = Field(default_factory=list)


class FaceLoginResponse(BaseModel):
    decision: Decision
    matched: bool
    match_score: float = Field(ge=0.0, le=1.0)
    passive_liveness_risk: float = Field(ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)
    profile: UserProfile | None = None
    checks: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    signals: list[FraudSignal] = Field(default_factory=list)
