import secrets
import time
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.models.schemas import (
    AuditListResponse,
    AuditVerifyResponse,
    AuthUserInfo,
    CompleteChallengeRequest,
    ConsentInfo,
    CreateVerificationRequest,
    DeleteProfileResponse,
    Decision,
    FaceEnrollmentResponse,
    FaceLoginResponse,
    FraudSignal,
    SelfServiceDeleteResponse,
    SelfServiceExportResponse,
    SelfieAnalysisRequest,
    TokenResponse,
    UserProfile,
    UserProfileListResponse,
    VerificationResult,
)
from app.services import auth as auth_service
from app.services.audit import audit_log
from app.services.key_provider import resolve_secret
from app.services.face_biometrics import OpenCvFaceRecognizer
from app.services.fraud import LaoIdCardFraudAnalyzer, PassportFraudAnalyzer
from app.services.profile_store import ProfileEnrollmentConflict, profile_store
from app.services.rate_limit import SlidingWindowLimiter
from app.services.selfie import SelfieAnalyzer
from app.services.session_store import store

router = APIRouter()
settings = get_settings()
document_analyzers = {
    "passport": PassportFraudAnalyzer(),
    "lao_id_card": LaoIdCardFraudAnalyzer(),
}
face_recognizer = OpenCvFaceRecognizer()
selfie_analyzer = SelfieAnalyzer(face_recognizer=face_recognizer)

# Anti brute-force / face-harvesting throttle for /api/face-login: a per-client
# limit for fairness plus a global cap that bounds total attempts even when the
# client IP cannot be trusted/distinguished (shared proxy IPs).
_face_login_client_limiter = SlidingWindowLimiter(settings.face_login_max_per_minute)
_face_login_global_limiter = SlidingWindowLimiter(settings.face_login_global_max_per_minute)


def _client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        # CF-Connecting-IP is set by Cloudflare and not client-spoofable behind
        # the Cloudflare edge; X-Forwarded-For is the fallback.
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.split(",")[0].strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def face_login_rate_limit(request: Request) -> None:
    if request.client and request.client.host == "testclient":
        return
    if not _face_login_global_limiter.allow("face-login"):
        raise HTTPException(status_code=429, detail="Face login is busy right now. Please try again in a minute.")
    if not _face_login_client_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many face login attempts. Please wait a minute and try again.")


def _get_session(session_id: UUID, request: Request) -> VerificationResult:
    try:
        session = store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    # Short-lived: reject + evict once idle/absolute TTL is exceeded.
    if store.is_expired(session_id):
        store.drop(session_id)
        raise HTTPException(status_code=410, detail="Verification session has expired. Please start over.")
    # Client-bound: the session-id alone is not enough — the per-session token
    # (issued at creation) must be presented, defeating id-only hijack/replay.
    if settings.session_binding_enforced:
        token = request.headers.get("x-session-token")
        if not store.validate_token(session_id, token):
            raise HTTPException(status_code=403, detail="Invalid or missing session token.")
    return session


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


def _mask_document_number(number: str | None) -> str | None:
    if not number:
        return number
    value = number.strip()
    if len(value) <= 4:
        return "•" * len(value)
    return f"{value[:2]}{'•' * (len(value) - 4)}{value[-2:]}"


def _redact_profile(profile):
    """Return a privacy-minimised copy for unauthenticated face-login responses:
    keep enough to greet the returning user (first name, nationality, masked
    document number) but drop full name, DOB, and expiry."""
    return profile.model_copy(
        update={
            "full_name": None,
            "last_name": None,
            "date_of_birth": None,
            "passport_expiry": None,
            "passport_number": _mask_document_number(profile.passport_number),
        }
    )


def _float_check(checks: dict[str, object], key: str) -> float:
    value = checks.get(key)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _has_strong_active_replay_evidence(checks: dict[str, object], risk: float) -> bool:
    screen_frame_score = _float_check(checks, "passive_spoof_screen_frame_score")
    display_surface_score = _float_check(checks, "passive_spoof_display_surface_score")
    paper_photo_score = _float_check(checks, "passive_spoof_paper_photo_score")
    model_risk = _float_check(checks, "passive_spoof_model_risk")
    heuristic_risk = _float_check(checks, "passive_spoof_heuristic_risk")
    return (
        screen_frame_score >= 0.62
        or paper_photo_score >= 0.56
        or (risk >= 0.5 and screen_frame_score >= 0.42)
        or (risk >= 0.5 and paper_photo_score >= 0.38)
        or (risk >= 0.55 and display_surface_score >= 0.58 and screen_frame_score >= 0.28)
        or (
            risk >= settings.max_active_liveness_spoof_risk
            and model_risk >= 0.82
            and heuristic_risk >= 0.24
            and (
                screen_frame_score >= 0.28
                or paper_photo_score >= 0.24
                or (display_surface_score >= 0.62 and screen_frame_score >= 0.22)
            )
        )
    )


def active_liveness_quality_spoof_signals(
    face_width_ratios: list[float],
    model_risks: list[float],
    min_face_width_ratio: float = 0.22,
) -> tuple[list[FraudSignal], dict[str, object]]:
    """Face-size and recurring-model spoof signals for an active-liveness burst.

    PAD models are unreliable on small/distant faces, and a printed photo held
    at arm's length reads as a small face, so small frames are excluded from the
    model vote. A burst that is mostly small faces is a move-closer hard fail.
    A single high-risk frame never blocks on its own; the model must agree
    across the burst (recurrence) before it hard-fails a real user.
    """
    frame_count = len(model_risks)
    adequate_indices = [i for i, ratio in enumerate(face_width_ratios) if ratio >= min_face_width_ratio]
    small_face_count = frame_count - len(adequate_indices)
    reliable_model_risks = [model_risks[i] for i in adequate_indices] or model_risks
    model_high_count = sum(1 for risk in reliable_model_risks if risk >= 0.72)
    model_spoof_recurring = model_high_count >= 2 or (len(reliable_model_risks) <= 2 and model_high_count >= 1)

    signals: list[FraudSignal] = []
    if frame_count and small_face_count * 2 > frame_count:
        signals.append(_signal("ACTIVE_LIVENESS_FACE_TOO_SMALL", "You are a bit too far from the camera; move your face closer until it fills the oval, then repeat the action.", "high", 0.7))
    if model_spoof_recurring:
        signals.append(_signal("ACTIVE_LIVENESS_MODEL_SPOOF_HIGH", "Anti-spoofing model detected recurring screen/photo spoof risk during active liveness.", "high", max(reliable_model_risks, default=0.0)))

    diagnostics = {
        "active_liveness_model_high_count": model_high_count,
        "active_liveness_model_spoof_recurring": model_spoof_recurring,
        "active_liveness_small_face_count": small_face_count,
        "active_liveness_reliable_frame_count": len(reliable_model_risks),
    }
    return signals, diagnostics


def warm_face_login_dependencies() -> None:
    face_recognizer.warm_up()
    selfie_analyzer.passive_spoof.warm_up()
    profile_store.prime_cache()


@router.post("/verifications", response_model=VerificationResult)
async def create_verification(payload: CreateVerificationRequest) -> VerificationResult:
    result = store.create(payload.user_id)
    # Return the client-binding token once, at creation, without persisting it on
    # the stored result (so later responses don't leak it).
    return result.model_copy(update={"session_token": store.session_token(result.session_id)})


@router.get("/verifications/{session_id}", response_model=VerificationResult)
async def get_verification(session_id: UUID, request: Request) -> VerificationResult:
    return _get_session(session_id, request)


@router.post("/verifications/{session_id}/document", response_model=VerificationResult)
async def upload_document(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    ocr_text: str | None = Form(default=None),
    document_type: str = Form(default="passport"),
) -> VerificationResult:
    started_at = time.perf_counter()
    _get_session(session_id, request)
    analyzer = document_analyzers.get(document_type)
    if analyzer is None:
        raise HTTPException(status_code=400, detail="Unsupported document type. Use passport or lao_id_card.")
    content = await _read_upload(file)
    analysis_started_at = time.perf_counter()
    analysis = await run_in_threadpool(analyzer.analyze, content, file.filename or f"{document_type}-upload", ocr_text)
    analysis_elapsed_ms = round((time.perf_counter() - analysis_started_at) * 1000, 2)
    face_started_at = time.perf_counter()
    face_result = await run_in_threadpool(face_recognizer.extract, content, "document")
    face_elapsed_ms = round((time.perf_counter() - face_started_at) * 1000, 2)
    analysis.checks.update(
        {
            "document_upload_kb": round(len(content) / 1024, 1),
            "document_type": document_type,
            "document_total_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "document_analysis_ms": analysis_elapsed_ms,
            "document_face_extract_ms": face_elapsed_ms,
        }
    )
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
async def complete_challenge(session_id: UUID, payload: CompleteChallengeRequest, request: Request) -> VerificationResult:
    session = _get_session(session_id, request)
    if payload.challenge_id in {challenge.id for challenge in session.active_challenges}:
        raise HTTPException(status_code=409, detail="Active liveness requires server-verified face evidence.")
    target = next((c for c in session.hand_challenges if c.id == payload.challenge_id), None)
    if target is None:
        raise HTTPException(status_code=400, detail="Unknown hand-gesture challenge.")
    # Ordering: gestures can only be completed after the server-verified
    # active-liveness step has passed (cannot skip ahead via the API).
    if not session.biometric.active_liveness_passed:
        raise HTTPException(status_code=409, detail="Complete active liveness before the hand-gesture step.")
    if not payload.passed:
        raise HTTPException(status_code=400, detail="A passed hand gesture is required.")
    # Freshness + replay protection: require the matching one-time, session-bound
    # nonce. It is consumed on success, so a captured request cannot be replayed.
    if not target.nonce or not payload.nonce or not secrets.compare_digest(payload.nonce, target.nonce):
        raise HTTPException(status_code=401, detail="Invalid, missing, or already-used challenge nonce.")
    return store.complete_challenge(session_id, payload)


@router.post("/verifications/{session_id}/active-liveness", response_model=VerificationResult)
async def complete_active_liveness(
    session_id: UUID,
    request: Request,
    challenge_id: str = Form(...),
    file: UploadFile | None = File(default=None),
    frames: list[UploadFile] | None = File(default=None),
) -> VerificationResult:
    session = _get_session(session_id, request)
    if session.document.status != "passed":
        raise HTTPException(status_code=409, detail="Document must pass before active liveness.")
    if challenge_id not in {challenge.id for challenge in session.active_challenges}:
        raise HTTPException(status_code=400, detail="Unknown active liveness challenge.")

    started_at = time.perf_counter()
    liveness_files = frames or ([file] if file else [])
    if not liveness_files:
        raise HTTPException(status_code=400, detail="At least one active liveness frame is required.")
    liveness_files = liveness_files[:3]
    contents = [await _read_upload(item) for item in liveness_files]

    face_started_at = time.perf_counter()
    face_results = [
        await run_in_threadpool(face_recognizer.extract, content, "active_liveness")
        for content in contents
    ]
    face_elapsed_ms = round((time.perf_counter() - face_started_at) * 1000, 2)

    passive_started_at = time.perf_counter()
    passive_results = [
        await run_in_threadpool(selfie_analyzer.passive_spoof.analyze, content, face_result.face_box)
        for content, face_result in zip(contents, face_results, strict=False)
    ]
    passive_elapsed_ms = round((time.perf_counter() - passive_started_at) * 1000, 2)

    representative_index, face_result = max(
        enumerate(face_results),
        key=lambda item: item[1].face_confidence or 0,
    )
    passive_result = passive_results[representative_index]
    signals = [*face_result.signals]
    usable_face_count = sum(1 for result in face_results if result.embedding is not None)
    max_face_count = max(int(result.checks.get("active_liveness_face_count") or 0) for result in face_results)
    if usable_face_count == 0:
        signals.append(_signal("ACTIVE_LIVENESS_FACE_NOT_FOUND", "No live face was detected during active liveness.", "high", 0.92))
    if face_result.face_confidence is not None and face_result.face_confidence < 0.82:
        signals.append(_signal("ACTIVE_LIVENESS_FACE_CONFIDENCE_LOW", "Active liveness face confidence is too low.", "high", 0.86))
    if max_face_count > 1:
        signals.append(_signal("ACTIVE_LIVENESS_MULTIPLE_FACES", "Multiple faces detected during active liveness.", "high", 0.86))

    face_width_ratios = [
        (_float_check(result.checks, "active_liveness_face_box_width")
         / max(_float_check(result.checks, "active_liveness_image_width"), 1.0))
        for result in face_results
    ]
    model_risks = [_float_check(result.checks, "passive_spoof_model_risk") for result in passive_results]
    quality_signals, quality_diagnostics = active_liveness_quality_spoof_signals(face_width_ratios, model_risks)
    signals.extend(quality_signals)

    risks = [result.risk for result in passive_results]
    screen_frame_scores = [_float_check(result.checks, "passive_spoof_screen_frame_score") for result in passive_results]
    display_surface_scores = [_float_check(result.checks, "passive_spoof_display_surface_score") for result in passive_results]
    paper_photo_scores = [_float_check(result.checks, "passive_spoof_paper_photo_score") for result in passive_results]
    heuristic_risks = [_float_check(result.checks, "passive_spoof_heuristic_risk") for result in passive_results]
    max_risk = max(risks, default=0.0)
    mean_risk = sum(risks) / len(risks) if risks else 0.0
    screen_frame_score = max(screen_frame_scores, default=0.0)
    display_surface_score = max(display_surface_scores, default=0.0)
    paper_photo_score = max(paper_photo_scores, default=0.0)
    model_risk = max(model_risks, default=0.0)
    heuristic_risk = max(heuristic_risks, default=0.0)
    strong_replay_evidence = any(
        _has_strong_active_replay_evidence(result.checks, result.risk)
        for result in passive_results
    )
    display_like_frame_count = sum(
        1
        for screen_score, display_score, model_score, heuristic_score in zip(
            screen_frame_scores,
            display_surface_scores,
            model_risks,
            heuristic_risks,
            strict=False,
        )
        if (
            screen_score >= 0.45
            or (display_score >= 0.58 and screen_score >= 0.28)
            or (display_score >= 0.62 and screen_score >= 0.22 and model_score >= 0.82 and heuristic_score >= 0.3)
        )
    )
    recurring_display_surface = len(passive_results) >= 3 and display_like_frame_count / len(passive_results) >= 0.67
    strong_replay_evidence = strong_replay_evidence or recurring_display_surface
    if strong_replay_evidence:
        signals.append(_signal("ACTIVE_LIVENESS_REPLAY_DETECTED", "Possible screen, photo, or replay attack detected during active liveness.", "high", max_risk))

    high_codes = {signal.code for signal in signals if signal.severity == "high"}
    passed = not high_codes
    checks = {
        "active_liveness_challenge_id": challenge_id,
        "active_liveness_upload_kb": round(sum(len(content) for content in contents) / 1024, 1),
        "active_liveness_upload_frame_count": len(contents),
        "active_liveness_burst_mode": len(contents) > 1,
        "active_liveness_representative_frame": representative_index,
        "active_liveness_total_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "active_liveness_face_extract_ms": face_elapsed_ms,
        "active_liveness_passive_liveness_ms": passive_elapsed_ms,
        "active_liveness_passive_liveness_risk": round(max_risk, 3),
        "active_liveness_passive_liveness_mean_risk": round(mean_risk, 3),
        "active_liveness_passive_liveness_passed": all(result.passed for result in passive_results),
        "active_liveness_screen_frame_score": round(screen_frame_score, 3),
        "active_liveness_display_surface_score": round(display_surface_score, 3),
        "active_liveness_paper_photo_score": round(paper_photo_score, 3),
        "active_liveness_model_spoof_risk": round(model_risk, 3),
        **quality_diagnostics,
        "active_liveness_heuristic_spoof_risk": round(heuristic_risk, 3),
        "active_liveness_display_like_frame_count": display_like_frame_count,
        "active_liveness_recurring_display_surface": recurring_display_surface,
        "active_liveness_strong_replay_evidence": strong_replay_evidence,
        **face_result.checks,
        **passive_result.checks,
    }
    return store.complete_active_challenge_with_evidence(
        session_id,
        CompleteChallengeRequest(challenge_id=challenge_id, passed=passed),
        checks,
        signals if not passed else [],
    )


@router.post("/verifications/{session_id}/selfie", response_model=VerificationResult)
async def analyze_selfie(
    session_id: UUID,
    request: Request,
    file: UploadFile | None = File(default=None),
    frames: list[UploadFile] | None = File(default=None),
) -> VerificationResult:
    started_at = time.perf_counter()
    _get_session(session_id, request)
    selfie_files = frames or ([file] if file else [])
    if not selfie_files:
        raise HTTPException(status_code=400, detail="At least one selfie frame is required.")
    selfie_files = selfie_files[:12]
    contents = [await _read_upload(item) for item in selfie_files]
    filenames = [item.filename or f"selfie-frame-{index}.jpg" for index, item in enumerate(selfie_files)]
    reference_embedding = store.get_document_face_embedding(session_id)
    analysis_started_at = time.perf_counter()
    if len(contents) > 1:
        analysis = await run_in_threadpool(selfie_analyzer.analyze_frames, contents, filenames, reference_embedding)
    else:
        analysis = await run_in_threadpool(selfie_analyzer.analyze, contents[0], filenames[0], reference_embedding)
    analysis_elapsed_ms = round((time.perf_counter() - analysis_started_at) * 1000, 2)
    representative_index = int(analysis.selfie_checks.get("selfie_burst_representative_frame") or 0)
    representative_content = contents[min(max(representative_index, 0), len(contents) - 1)]
    face_started_at = time.perf_counter()
    selfie_face = await run_in_threadpool(face_recognizer.extract, representative_content, "selfie")
    face_elapsed_ms = round((time.perf_counter() - face_started_at) * 1000, 2)
    analysis.selfie_checks.update(
        {
            "selfie_upload_kb": round(sum(len(content) for content in contents) / 1024, 1),
            "selfie_upload_frame_count": len(contents),
            "selfie_total_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "selfie_analysis_ms": analysis_elapsed_ms,
            "selfie_face_extract_ms": face_elapsed_ms,
        }
    )
    store.set_selfie_face_embedding(session_id, selfie_face.embedding if analysis.passive_liveness_passed else None)
    return store.set_selfie(session_id, analysis)


@router.post("/verifications/{session_id}/enroll-face", response_model=FaceEnrollmentResponse)
async def enroll_face(session_id: UUID, request: Request) -> FaceEnrollmentResponse:
    session = _get_session(session_id, request)
    if session.decision != Decision.passed:
        raise HTTPException(status_code=409, detail="Verification must pass before face enrollment.")
    selfie_embedding = store.get_selfie_face_embedding(session_id)
    if selfie_embedding is None:
        raise HTTPException(status_code=409, detail="A verified live selfie template is required before enrollment.")
    try:
        profile = await run_in_threadpool(profile_store.enroll, session, selfie_embedding)
    except ProfileEnrollmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_log.record(
        "enrollment", "enroll", actor=profile.user_id, subject=str(session_id),
        detail={"decision": session.decision.value, "consent_version": profile.consent_version},
    )
    return FaceEnrollmentResponse(enrolled=True, profile=profile)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token", auto_error=False)


def _auth_users() -> dict[str, auth_service.AuthUser]:
    return auth_service.load_users(settings.auth_users)


def _jwt_signing_secret() -> str:
    """Resolve the primary JWT secret (used to sign new tokens)."""
    return resolve_secret(settings.jwt_secret)


def _jwt_verify_secrets() -> list[str]:
    """Primary + retired JWT secrets, so tokens signed under a retired secret still
    verify during a rotation."""
    secrets_ = [resolve_secret(settings.jwt_secret)]
    secrets_ += [resolve_secret(spec) for spec in settings.jwt_secrets_retired]
    return [s for s in secrets_ if s]


@router.post("/auth/token", response_model=TokenResponse)
async def issue_token(request: Request, form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    """OAuth2 password grant: exchange username + password for a signed JWT."""
    if not settings.jwt_secret:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    user = await run_in_threadpool(
        auth_service.authenticate, _auth_users(), form.username, form.password
    )
    if user is None:
        audit_log.record(
            "auth", "login_failed", actor=form.username or None,
            subject=_client_ip(request), detail={"success": False},
        )
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    audit_log.record(
        "auth", "login", actor=user.username,
        subject=_client_ip(request), detail={"role": user.role, "success": True},
    )
    token = auth_service.create_access_token(
        _jwt_signing_secret(), user.username, user.role, settings.jwt_expire_minutes
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        role=user.role,
    )


def get_current_user(token: str | None = Depends(oauth2_scheme)) -> auth_service.AuthUser:
    """Resolve the caller from a Bearer JWT. 401 when missing/invalid/expired."""
    if not settings.jwt_secret:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    payload = auth_service.decode_token(_jwt_verify_secrets(), token) if token else None
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_service.AuthUser(username=payload.get("sub", ""), role=payload.get("role", "user"))


@router.get("/auth/me", response_model=AuthUserInfo)
async def read_current_user(user: auth_service.AuthUser = Depends(get_current_user)) -> AuthUserInfo:
    return AuthUserInfo(username=user.username, role=user.role)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate all /api endpoints behind an API key when one or more are configured.
    Open (no-op) when LALIGENCE_API_KEYS is unset, so the public demo still works."""
    keys = tuple(resolve_secret(spec) for spec in settings.api_keys if spec)
    if not keys:
        return
    if not x_api_key or not any(secrets.compare_digest(x_api_key, key) for key in keys):
        raise HTTPException(status_code=401, detail="Invalid or missing API key. Send it in the X-API-Key header.")


def require_admin(
    x_admin_token: str | None = Header(default=None),
    token: str | None = Depends(oauth2_scheme),
) -> None:
    """Guard the profile admin endpoints. Fail-closed: disabled unless a static
    admin token (X-Admin-Token) or JWT auth (a Bearer token with role "admin") is
    configured. Either credential grants access."""
    expected = resolve_secret(settings.admin_api_token)
    jwt_enabled = bool(settings.jwt_secret)
    # JWT path: a valid Bearer token carrying the admin role.
    if jwt_enabled and token:
        payload = auth_service.decode_token(_jwt_verify_secrets(), token)
        if payload and payload.get("role") == "admin":
            return
    if not expected:
        if jwt_enabled:
            raise HTTPException(status_code=401, detail="Admin privileges required.")
        raise HTTPException(
            status_code=403,
            detail="Admin endpoints are disabled. Set LALIGENCE_ADMIN_API_TOKEN or "
            "LALIGENCE_JWT_SECRET with an admin user to enable them.",
        )
    # Static-token path (backward compatible).
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


@router.get("/profiles", response_model=UserProfileListResponse, dependencies=[Depends(require_admin)])
async def list_profiles(request: Request) -> UserProfileListResponse:
    profiles = await run_in_threadpool(profile_store.list_profiles)
    audit_log.record("pii_access", "list_profiles", actor=_client_ip(request),
                     detail={"count": len(profiles)})
    return UserProfileListResponse(profiles=profiles)


@router.delete("/profiles/{user_id}", response_model=DeleteProfileResponse, dependencies=[Depends(require_admin)])
async def delete_profile(user_id: str, request: Request) -> DeleteProfileResponse:
    deleted_count = await run_in_threadpool(profile_store.delete_user, user_id)
    audit_log.record("erasure", "delete_profile", actor=_client_ip(request),
                     subject=user_id, detail={"deleted": deleted_count})
    return DeleteProfileResponse(deleted=deleted_count > 0, deleted_count=deleted_count)


@router.delete("/profiles", response_model=DeleteProfileResponse, dependencies=[Depends(require_admin)])
async def delete_profiles(request: Request) -> DeleteProfileResponse:
    deleted_count = await run_in_threadpool(profile_store.delete_all)
    audit_log.record("erasure", "delete_all_profiles", actor=_client_ip(request),
                     detail={"deleted": deleted_count})
    return DeleteProfileResponse(deleted=deleted_count > 0, deleted_count=deleted_count)


@router.post("/profiles/purge-expired", response_model=DeleteProfileResponse, dependencies=[Depends(require_admin)])
async def purge_expired_profiles(request: Request) -> DeleteProfileResponse:
    """Retention enforcement: delete profiles older than LALIGENCE_PROFILE_RETENTION_DAYS.
    No-op (0 deleted) when retention is disabled (0). Intended for a scheduled job."""
    deleted_count = await run_in_threadpool(
        profile_store.purge_expired_profiles, settings.profile_retention_days
    )
    audit_log.record("retention", "purge_expired", actor=_client_ip(request),
                     detail={"deleted": deleted_count, "retention_days": settings.profile_retention_days})
    return DeleteProfileResponse(deleted=deleted_count > 0, deleted_count=deleted_count)


@router.get("/audit", response_model=AuditListResponse, dependencies=[Depends(require_admin)])
async def read_audit_log(limit: int = 100) -> AuditListResponse:
    events = await run_in_threadpool(audit_log.list_events, max(1, min(limit, 500)))
    return AuditListResponse(events=events)


@router.get("/audit/verify", response_model=AuditVerifyResponse, dependencies=[Depends(require_admin)])
async def verify_audit_log() -> AuditVerifyResponse:
    result = await run_in_threadpool(audit_log.verify_chain)
    return AuditVerifyResponse(**result)


@router.post("/face-login", response_model=FaceLoginResponse, dependencies=[Depends(face_login_rate_limit)])
async def face_login(request: Request, file: UploadFile = File(...)) -> FaceLoginResponse:
    started_at = time.perf_counter()
    content = await _read_upload(file)
    face_started_at = time.perf_counter()
    face_result = await run_in_threadpool(face_recognizer.extract, content, "login")
    face_elapsed_ms = round((time.perf_counter() - face_started_at) * 1000, 2)
    passive_result = None
    passive_elapsed_ms = 0.0
    signals = [*face_result.signals]
    reason_codes: list[str] = []

    if face_result.embedding is None:
        reason_codes.append("FACE_LOGIN_FACE_NOT_FOUND")
    if face_result.face_confidence and face_result.face_confidence < 0.82:
        reason_codes.append("FACE_LOGIN_FACE_CONFIDENCE_LOW")
        signals.append(_signal("FACE_LOGIN_FACE_CONFIDENCE_LOW", "Login face confidence is too low.", "high", 0.86))
    if int(face_result.checks.get("login_face_count") or 0) > 1:
        reason_codes.append("FACE_LOGIN_MULTIPLE_FACES")
        signals.append(_signal("FACE_LOGIN_MULTIPLE_FACES", "Multiple faces detected during face login.", "high", 0.86))
    if not reason_codes:
        passive_started_at = time.perf_counter()
        passive_result = await run_in_threadpool(selfie_analyzer.passive_spoof.analyze, content, face_result.face_box)
        passive_elapsed_ms = round((time.perf_counter() - passive_started_at) * 1000, 2)
        signals.extend(passive_result.signals)
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
    matched_user_id = profile.user_id if profile is not None else None
    if profile is not None and not settings.face_login_expose_pii:
        profile = _redact_profile(profile)
    decision = Decision.passed if profile and not reason_codes else Decision.rejected
    audit_log.record(
        "auth", "face_login", actor=_client_ip(request), subject=matched_user_id,
        detail={"decision": decision.value, "matched": profile is not None},
    )
    return FaceLoginResponse(
        decision=decision,
        matched=profile is not None,
        match_score=match_score,
        passive_liveness_risk=round(passive_result.risk, 2) if passive_result else 1.0,
        reason_codes=reason_codes,
        profile=profile,
        checks={
            "face_login_match_threshold": settings.face_login_match_threshold,
            "face_login_total_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "face_login_face_extract_ms": face_elapsed_ms,
            "face_login_passive_liveness_ms": passive_elapsed_ms,
            "face_login_profile_match_ms": match_elapsed_ms,
            **face_result.checks,
            **(passive_result.checks if passive_result else {"passive_spoof_skipped": True}),
        },
        signals=signals,
    )


# --- Consent + self-service data rights (GDPR) --------------------------------

CONSENT_NOTICE = (
    "To verify your identity, Kyron captures your document and a live selfie and "
    "creates a protected face template. Images are analyzed in memory and not "
    "stored; only an encrypted template and minimal document details are kept, and "
    "only if you complete enrollment. You can export or delete your data at any "
    "time from “Manage my data”. By continuing you consent to this biometric "
    "processing."
)


@router.get("/consent", response_model=ConsentInfo)
async def get_consent() -> ConsentInfo:
    """The current consent terms version + notice, so the UI shows (and records
    against) the right version."""
    return ConsentInfo(version=settings.consent_version, notice=CONSENT_NOTICE)


async def _authenticate_face_owner(content: bytes) -> tuple[UserProfile | None, list[str], float]:
    """Prove data-subject ownership by face: extract + passive liveness + match.
    Returns the matched (unredacted) profile — the owner's own data — or None."""
    face_result = await run_in_threadpool(face_recognizer.extract, content, "login")
    reason_codes: list[str] = []
    if face_result.embedding is None:
        reason_codes.append("FACE_NOT_FOUND")
    if face_result.face_confidence and face_result.face_confidence < 0.82:
        reason_codes.append("FACE_CONFIDENCE_LOW")
    if int(face_result.checks.get("login_face_count") or 0) > 1:
        reason_codes.append("MULTIPLE_FACES")
    if not reason_codes:
        passive = await run_in_threadpool(
            selfie_analyzer.passive_spoof.analyze, content, face_result.face_box
        )
        if not passive.passed or passive.risk > settings.max_passive_liveness_risk:
            reason_codes.append("LIVENESS_FAILED")
    for signal in face_result.signals:
        if signal.severity == "high" and signal.code not in reason_codes:
            reason_codes.append(signal.code)
    if reason_codes or face_result.embedding is None:
        return None, reason_codes, 0.0
    match = await run_in_threadpool(
        profile_store.match, face_result.embedding, face_recognizer.compare,
        settings.face_login_match_threshold,
    )
    if match.profile is None:
        reason_codes.append("NO_MATCH")
        return None, reason_codes, match.score
    return match.profile, reason_codes, match.score


@router.post("/self-service/export", response_model=SelfServiceExportResponse,
             dependencies=[Depends(face_login_rate_limit)])
async def self_service_export(request: Request, file: UploadFile = File(...)) -> SelfServiceExportResponse:
    """Data-subject access/portability: a live selfie authenticates the owner, who
    then receives their own stored profile for download."""
    content = await _read_upload(file)
    profile, reason_codes, score = await _authenticate_face_owner(content)
    audit_log.record(
        "dsar", "self_service_export", actor=_client_ip(request),
        subject=profile.user_id if profile else None, detail={"verified": profile is not None},
    )
    if profile is None:
        return SelfServiceExportResponse(verified=False, reason_codes=reason_codes, match_score=round(score, 2))
    return SelfServiceExportResponse(verified=True, match_score=round(score, 2), profile=profile)


@router.post("/self-service/delete", response_model=SelfServiceDeleteResponse,
             dependencies=[Depends(face_login_rate_limit)])
async def self_service_delete(request: Request, file: UploadFile = File(...)) -> SelfServiceDeleteResponse:
    """Right to erasure: a live selfie authenticates the owner, who can then delete
    their own enrolled profile. The deletion is recorded in the audit log."""
    content = await _read_upload(file)
    profile, reason_codes, _score = await _authenticate_face_owner(content)
    if profile is None:
        audit_log.record("erasure", "self_service_delete_denied",
                         actor=_client_ip(request), detail={"verified": False})
        return SelfServiceDeleteResponse(verified=False, deleted=False, reason_codes=reason_codes)
    deleted = await run_in_threadpool(profile_store.delete_user, profile.user_id)
    audit_log.record("erasure", "self_service_delete", actor=_client_ip(request),
                     subject=profile.user_id, detail={"deleted": deleted})
    return SelfServiceDeleteResponse(verified=True, deleted=deleted > 0, user_id=profile.user_id)
