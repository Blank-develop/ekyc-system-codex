import time
import logging
import threading
from collections import defaultdict, deque

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import require_api_key, router, warm_face_login_dependencies
from app.core.config import get_settings

settings = get_settings()
request_log: dict[str, deque[float]] = defaultdict(deque)
logger = logging.getLogger("laligence.api")

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit(request, call_next):
    started_at = time.perf_counter()
    if settings.max_requests_per_minute <= 0:
        response = await call_next(request)
        return _with_timing(request, response, started_at)
    client_host = request.client.host if request.client else "unknown"
    if client_host == "testclient":
        response = await call_next(request)
        return _with_timing(request, response, started_at)

    now = time.monotonic()
    window_start = now - 60
    entries = request_log[client_host]
    while entries and entries[0] < window_start:
        entries.popleft()
    if len(entries) >= settings.max_requests_per_minute:
        response = JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please try again shortly."})
        return _with_timing(request, response, started_at)
    entries.append(now)
    response = await call_next(request)
    return _with_timing(request, response, started_at)


def _with_timing(request, response, started_at: float):
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
    if elapsed_ms >= 1000:
        logger.warning("slow_request path=%s method=%s elapsed_ms=%.2f", request.url.path, request.method, elapsed_ms)
    return response


app.include_router(router, prefix=settings.api_prefix, dependencies=[Depends(require_api_key)])


@app.on_event("startup")
async def warm_models_after_startup() -> None:
    threading.Thread(target=_warm_models, daemon=True).start()


def _warm_models() -> None:
    try:
        warm_face_login_dependencies()
    except Exception:
        logger.exception("face_login_warmup_failed")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Optionally serve the built Vite frontend from the same origin (single-port
# deployments such as Hugging Face Spaces). Mounted last so /api and /health
# keep priority. No-op for local dev/tests when the dist dir is not configured.
def _mount_frontend() -> None:
    dist = settings.frontend_dist
    if not dist:
        return
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    dist_path = Path(dist)
    if not (dist_path / "index.html").exists():
        logger.warning("frontend_dist set but index.html not found at %s", dist_path)
        return
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")
    logger.info("serving frontend from %s", dist_path)


_mount_frontend()
