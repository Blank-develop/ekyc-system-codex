import os
from functools import lru_cache
from pydantic import BaseModel


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _str_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


class Settings(BaseModel):
    app_name: str = "LALIGENCE eKYC API"
    api_prefix: str = "/api"
    database_url: str = _str_env("DATABASE_URL", "sqlite:///backend/data/laligence_profiles.sqlite3")
    min_face_match_score: float = _float_env("LALIGENCE_MIN_FACE_MATCH_SCORE", 0.68)
    max_passive_liveness_risk: float = _float_env("LALIGENCE_MAX_PASSIVE_LIVENESS_RISK", 0.34)
    max_active_liveness_spoof_risk: float = _float_env("LALIGENCE_MAX_ACTIVE_LIVENESS_SPOOF_RISK", 0.82)
    max_document_fraud_risk: float = _float_env("LALIGENCE_MAX_DOCUMENT_FRAUD_RISK", 0.42)
    face_login_match_threshold: float = _float_env("LALIGENCE_FACE_LOGIN_MATCH_THRESHOLD", 0.72)
    pad_enable_companion_models: bool = _bool_env("LALIGENCE_PAD_ENABLE_COMPANION_MODELS", True)
    pad_extra_model_paths: tuple[str, ...] = _csv_env("LALIGENCE_PAD_EXTRA_MODEL_PATHS", ())
    lao_id_ocr_engine: str = _str_env("LALIGENCE_LAO_ID_OCR_ENGINE", "surya,tesseract")
    cors_origins: tuple[str, ...] = _csv_env(
        "LALIGENCE_CORS_ORIGINS",
        ("http://localhost:5173", "http://127.0.0.1:5173"),
    )
    frontend_dist: str = _str_env("LALIGENCE_FRONTEND_DIST", "")
    # Admin profile endpoints (list/delete) are disabled unless this token is set.
    # When set, callers must send it in the X-Admin-Token header. Fail-closed.
    admin_api_token: str = _str_env("LALIGENCE_ADMIN_API_TOKEN", "")
    # API authentication for all /api endpoints. When one or more keys are set
    # (comma-separated), callers must send a matching key in the X-API-Key header.
    # Unset = open (public demo). Set in production / for partner integrations.
    api_keys: tuple[str, ...] = _csv_env("LALIGENCE_API_KEYS", ())
    # Per-user OAuth2 password flow -> JWT (for the web console / operators). When
    # LALIGENCE_JWT_SECRET is set, POST /api/auth/token issues signed access tokens
    # and admin endpoints also accept a Bearer token whose role is "admin".
    # Users: LALIGENCE_AUTH_USERS = "user:pbkdf2_hash:role,..." (generate a hash with
    # scripts/hash_password.py). Unset = JWT auth disabled (public demo).
    jwt_secret: str = _str_env("LALIGENCE_JWT_SECRET", "")
    # Retired JWT secrets (comma-separated specs) still VERIFY previously issued
    # tokens during a rotation; the primary secret signs new tokens.
    jwt_secrets_retired: tuple[str, ...] = _csv_env("LALIGENCE_JWT_SECRETS_RETIRED", ())
    jwt_expire_minutes: int = _int_env("LALIGENCE_JWT_EXPIRE_MINUTES", 60)
    auth_users: tuple[str, ...] = _csv_env("LALIGENCE_AUTH_USERS", ())
    # Fernet key for encrypting biometric templates at rest. Unset = plaintext
    # (dev/demo). Set in production. Generate:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Secret values may be a bare literal (dev/demo) or a provider spec resolved at
    # runtime — file:/run/secrets/x, command:<vault/kms cli>, env:OTHER_VAR — so
    # production keys can come from a KMS/secret-manager, not a bare env var. See
    # services/key_provider.py.
    encryption_key: str = _str_env("LALIGENCE_ENCRYPTION_KEY", "")
    # Retired encryption keys (comma-separated specs) still DECRYPT existing data
    # during a key rotation; the primary key above is used to encrypt new data.
    encryption_keys_retired: tuple[str, ...] = _csv_env("LALIGENCE_ENCRYPTION_KEYS_RETIRED", ())
    # Cancelable/renewable biometric templates (ISO/IEC 24745). When set, stored
    # face templates are transformed by a key-derived orthonormal projection
    # (accuracy-preserving: matching scores are unchanged) so the raw biometric is
    # never stored even after decryption, and templates can be revoked/renewed by
    # re-keying (which requires re-enrollment). Unset = no-op (raw template).
    template_protection_key: str = _str_env("LALIGENCE_TEMPLATE_PROTECTION_KEY", "")
    # Privacy: consent terms version recorded against each enrolled profile, and
    # data-retention period in days (0 = retain indefinitely; >0 enables purge of
    # profiles whose last activity is older than the window).
    consent_version: str = _str_env("LALIGENCE_CONSENT_VERSION", "2026-06-v1")
    profile_retention_days: int = _int_env("LALIGENCE_PROFILE_RETENTION_DAYS", 0)
    # Tamper-evident audit log (hash-chained). Keyed with a key derived from
    # LALIGENCE_ENCRYPTION_KEY when set. On by default; records auth, PII access,
    # admin actions, and identity enrollment/decisions (no raw PII/biometrics).
    audit_log_enabled: bool = _bool_env("LALIGENCE_AUDIT_LOG_ENABLED", True)
    # Face login is unauthenticated, so by default it returns a redacted profile
    # (no full document number / DOB / expiry). Enable only in trusted/authenticated
    # deployments where returning the full identity to the caller is intended.
    face_login_expose_pii: bool = _bool_env("LALIGENCE_FACE_LOGIN_EXPOSE_PII", False)
    # Behind a trusted reverse proxy (HF, Cloudflare), derive the client IP from
    # CF-Connecting-IP / X-Forwarded-For so per-client rate limiting works.
    trust_proxy_headers: bool = _bool_env("LALIGENCE_TRUST_PROXY_HEADERS", False)
    # Anti brute-force / face-harvesting throttle on /api/face-login.
    face_login_max_per_minute: int = _int_env("LALIGENCE_FACE_LOGIN_MAX_PER_MINUTE", 12)
    face_login_global_max_per_minute: int = _int_env("LALIGENCE_FACE_LOGIN_GLOBAL_MAX_PER_MINUTE", 60)
    max_upload_size_bytes: int = _int_env("LALIGENCE_MAX_UPLOAD_SIZE_BYTES", 8 * 1024 * 1024)
    max_requests_per_minute: int = _int_env("LALIGENCE_MAX_REQUESTS_PER_MINUTE", 240)
    allowed_upload_content_types: tuple[str, ...] = _csv_env(
        "LALIGENCE_ALLOWED_UPLOAD_CONTENT_TYPES",
        ("image/jpeg", "image/jpg", "image/png", "image/webp"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
