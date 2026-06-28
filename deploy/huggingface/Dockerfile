# Hugging Face Space (Docker SDK) — serves the FULL Kyron eKYC app on one port.
#
# Stage 1 builds the Vite frontend. Stage 2 installs the FastAPI backend + models
# and serves the built frontend from the same origin (port 7860), so the Space
# URL runs the whole verification flow over HTTPS (camera works).
#
# The app source is pulled from GitHub at build time, so this Space repo only
# needs this Dockerfile and README.md. Bump REF or rebuild to pick up changes.

ARG REPO=https://github.com/Blank-develop/ekyc-system-codex.git
ARG REF=main

# ---- Stage 1: build frontend ----
FROM node:20-slim AS web
ARG REPO
ARG REF
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /web
RUN git clone --depth 1 --branch ${REF} ${REPO} src
WORKDIR /web/src/frontend
RUN npm install && npm run build

# ---- Stage 2: backend + serve ----
FROM python:3.12-slim
ARG REPO
ARG REF
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
        libglib2.0-0 libgomp1 libgl1 \
        tesseract-ocr tesseract-ocr-lao \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 --branch ${REF} ${REPO} .
RUN pip install --upgrade pip && pip install -r backend/requirements.txt
RUN python scripts/install_face_models.py

# Bring in the built frontend and serve it from the backend (same origin).
COPY --from=web /web/src/frontend/dist /app/frontend/dist
ENV LALIGENCE_FRONTEND_DIST=/app/frontend/dist

# HF writes SQLite/profiles here; storage is ephemeral on the free tier.
ENV DATABASE_URL=sqlite:////tmp/laligence_profiles.sqlite3

# Speed: on the free 2-vCPU tier, run only the primary anti-spoof model (skip the
# companion PAD models) so selfie/liveness frames are ~3x faster to score.
# If/when the Space is on upgraded hardware (e.g. CPU Upgrade, 8 vCPU), set this
# to true for the stronger, more accurate full PAD ensemble.
ENV LALIGENCE_PAD_ENABLE_COMPANION_MODELS=false

# Behind the HF reverse proxy: derive the real client IP from forwarded headers
# so the per-client face-login throttle works (not bucketed under one proxy IP).
ENV LALIGENCE_TRUST_PROXY_HEADERS=true

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 7860"]
