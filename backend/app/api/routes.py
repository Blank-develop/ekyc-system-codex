import time
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.models.schemas import (
    CompleteChallengeRequest,
    CreateVerificationRequest,
    DeleteProfileResponse,
    Decision,
    FaceEnrollmentResponse,
    FaceLoginResponse,
    FraudSignal,
    SelfieAnalysisRequest,
    UserProfileListResponse,
    VerificationResult,
)
from app.services.face_biometrics import OpenCvFaceRecognizer
from app.services.fraud import PassportFraudAnalyzer
from app.services.profile_store import ProfileEnrollmentConflict, profile_store
from app.services.selfie import SelfieAnalyzer
from app.services.session_store import store

router = APIRouter()
settings = get_settings()
analyzer = PassportFraudAnalyzer()
face_recognizer = OpenCvFaceRecognizer()
selfie_analyzer = SelfieAnalyzer(face_recognizer=face_recognizer)


def _get_session(session_id: UUID) -> VerificationResult:
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc


async def _read_upload(file: UploadFile) -> bytes:
    content_type = (file.content_type or "").split(";")[0].lower()
    if content_type and content_type not in settings.allowed_upload_content_types:
        raise HTTPException(status_code=415, detail="Unsupported image type. Use JPG, PNG, or WebP.")
    content = await file.read()
    if len(content) > settings.max_upload_size_bytes:
        max_mb = settings.max_upload_size_bytes / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Upload is too large. Maximum size is {max_mb:.0f} MB.")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    return content


def _signal(code: str, label: str, severity: str, score: float) -> FraudSignal:
    return FraudSignal(code=code, label=label, severity=severity, score=max(0.0, min(score, 1.0)))


@router.post("/verifications", response_model=VerificationResult)
async def create_verification(payload: CreateVerificationRequest) -> VerificationResult:
    return store.create(payload.user_id)


@router.get("/verifications/{session_id}", response_model=VerificationResult)
async def get_verification(session_id: UUID) -> VerificationResult:
    return _get_session(session_id)


@router.post("/verifications/{session_id}/document", response_model=VerificationResult)
async def upload_document(
    session_id: UUID,
    file: UploadFile = File(...),
    ocr_text: str | None = Form(default=None),
) -> VerificationResult:
    _get_session(session_id)
    content = await _read_upload(file)
    analysis = await run_in_threadpool(analyzer.analyze, content, file.filename or "passport-upload", ocr_text)
    face_result = await run_in_threadpool(face_recognizer.extract, content, "document")
    analysis.checks.update(face_result.checks)
    if face_result.embedding is not None:
        store.set_document_face_embedding(session_id, face_result.embedding)
    else:
        store.set_document_face_embedding(session_id, None)
        analysis.signals.extend(face_result.signals)
        if analysis.status == "passed":
            analysis.status = "rejected"
    return store.set_document(session_id, analysis)


@router.post("/verifications/{session_id}/challenge", response_model=VerificationResult)
async def complete_challenge(session_id: UUID, payload: CompleteChallengeRequest) -> VerificationResult:
    _get_session(session_id)
    return store.complete_challenge(session_id, payload)


@router.post("/verifications/{session_id}/selfie", response_model=VerificationResult)
async def analyze_selfie(
    session_id: UUID,
    file: UploadFile = File(...),
) -> VerificationResult:
    _get_session(session_id)
    content = await _read_upload(file)
    reference_embedding = store.get_document_face_embedding(session_id)
    analysis = await run_in_threadpool(
        selfie_analyzer.analyze,
        content,
        file.filename or "selfie-capture.jpg",
        reference_embedding,
    )
    selfie_face = await run_in_threadpool(face_recognizer.extract, content, "selfie")
    store.set_selfie_face_embedding(session_id, selfie_face.embedding if analysis.passive_liveness_passed else None)
    return store.set_selfie(session_id, analysis)


@router.post("/verifications/{session_id}/enroll-face", response_model=FaceEnrollmentResponse)
async def enroll_face(session_id: UUID) -> FaceEnrollmentResponse:
    session = _get_session(session_id)
    if session.decision != Decision.passed:
        raise HTTPException(status_code=409, detail="Verification must pass before face enrollment.")
    selfie_embedding = store.get_selfie_face_embedding(session_id)
    if selfie_embedding is None:
        raise HTTPException(status_code=409, detail="A verified live selfie template is required before enrollment.")
    try:
        profile = await run_in_threadpool(profile_store.enroll, session, selfie_embedding)
    except ProfileEnrollmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FaceEnrollmentResponse(enrolled=True, profile=profile)


@router.get("/profiles", response_model=UserProfileListResponse)
async def list_profiles() -> UserProfileListResponse:
    profiles = await run_in_threadpool(profile_store.list_profiles)
    return UserProfileListResponse(profiles=profiles)


@router.delete("/profiles/{user_id}", response_model=DeleteProfileResponse)
async def delete_profile(user_id: str) -> DeleteProfileResponse:
    deleted_count = await run_in_threadpool(profile_store.delete_user, user_id)
    return DeleteProfileResponse(deleted=deleted_count > 0, deleted_count=deleted_count)


@router.delete("/profiles", response_model=DeleteProfileResponse)
async def delete_profiles() -> DeleteProfileResponse:
    deleted_count = await run_in_threadpool(profile_store.delete_all)
    return DeleteProfileResponse(deleted=deleted_count > 0, deleted_count=deleted_count)


@router.post("/face-login", response_model=FaceLoginResponse)
async def face_login(file: UploadFile = File(...)) -> FaceLoginResponse:
    started_at = time.perf_counter()
    content = await _read_upload(file)
    face_started_at = time.perf_counter()
    face_result = await run_in_threadpool(face_recognizer.extract, content, "login")
    face_elapsed_ms = round((time.perf_counter() - face_started_at) * 1000, 2)
    passive_started_at = time.perf_counter()
    passive_result = await run_in_threadpool(selfie_analyzer.passive_spoof.analyze, content, face_result.face_box)
    passive_elapsed_ms = round((time.perf_counter() - passive_started_at) * 1000, 2)
    signals = [*face_result.signals, *passive_result.signals]
    reason_codes: list[str] = []

    if face_result.embedding is None:
        reason_codes.append("FACE_LOGIN_FACE_NOT_FOUND")
    if face_result.face_confidence and face_result.face_confidence < 0.82:
        reason_codes.append("FACE_LOGIN_FACE_CONFIDENCE_LOW")
        signals.append(_signal("FACE_LOGIN_FACE_CONFIDENCE_LOW", "Login face confidence is too low.", "high", 0.86))
    if int(face_result.checks.get("login_face_count") or 0) > 1:
        reason_codes.append("FACE_LOGIN_MULTIPLE_FACES")
        signals.append(_signal("FACE_LOGIN_MULTIPLE_FACES", "Multiple faces detected during face login.", "high", 0.86))
    if not passive_result.passed or passive_result.risk > settings.max_passive_liveness_risk:
        reason_codes.append("FACE_LOGIN_LIVENESS_FAILED")
    for signal in signals:
        if signal.severity == "high" and signal.code not in reason_codes:
            reason_codes.append(signal.code)

    match = None
    match_score = 0.0
    match_elapsed_ms = 0.0
    if not reason_codes and face_result.embedding is not None:
        match_started_at = time.perf_counter()
        match = await run_in_threadpool(
            profile_store.match,
            face_result.embedding,
            face_recognizer.compare,
            settings.face_login_match_threshold,
        )
        match_elapsed_ms = round((time.perf_counter() - match_started_at) * 1000, 2)
        match_score = match.score
        if match.profile is None:
            reason_codes.append("FACE_LOGIN_NO_MATCH")

    profile = match.profile if match else None
    return FaceLoginResponse(
        decision=Decision.passed if profile and not reason_codes else Decision.rejected,
        matched=profile is not None,
        match_score=match_score,
        passive_liveness_risk=round(passive_result.risk, 2),
        reason_codes=reason_codes,
        profile=profile,
        checks={
            "face_login_match_threshold": settings.face_login_match_threshold,
            "face_login_total_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "face_login_face_extract_ms": face_elapsed_ms,
            "face_login_passive_liveness_ms": passive_elapsed_ms,
            "face_login_profile_match_ms": match_elapsed_ms,
            **face_result.checks,
            **passive_result.checks,
        },
        signals=signals,
    )
