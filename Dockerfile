FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ARG INSTALL_SURYA_OCR=false

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libglib2.0-0 \
        libgomp1 \
        libgl1 \
        tesseract-ocr \
        tesseract-ocr-lao \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
COPY backend/requirements-surya.txt backend/requirements-surya.txt
RUN pip install --upgrade pip \
    && pip install -r backend/requirements.txt
RUN if [ "$INSTALL_SURYA_OCR" = "true" ]; then pip install -r backend/requirements-surya.txt; fi

COPY backend backend
COPY scripts scripts
RUN python scripts/install_face_models.py

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
