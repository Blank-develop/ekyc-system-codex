import time
from collections import defaultdict, deque

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()
request_log: dict[str, deque[float]] = defaultdict(deque)

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
    if settings.max_requests_per_minute <= 0:
        return await call_next(request)
    client_host = request.client.host if request.client else "unknown"
    if client_host == "testclient":
        return await call_next(request)

    now = time.monotonic()
    window_start = now - 60
    entries = request_log[client_host]
    while entries and entries[0] < window_start:
        entries.popleft()
    if len(entries) >= settings.max_requests_per_minute:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please try again shortly."})
    entries.append(now)
    return await call_next(request)


app.include_router(router, prefix=settings.api_prefix)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
