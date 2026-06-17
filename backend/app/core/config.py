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
    max_upload_size_bytes: int = _int_env("LALIGENCE_MAX_UPLOAD_SIZE_BYTES", 8 * 1024 * 1024)
    max_requests_per_minute: int = _int_env("LALIGENCE_MAX_REQUESTS_PER_MINUTE", 240)
    allowed_upload_content_types: tuple[str, ...] = _csv_env(
        "LALIGENCE_ALLOWED_UPLOAD_CONTENT_TYPES",
        ("image/jpeg", "image/jpg", "image/png", "image/webp"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
