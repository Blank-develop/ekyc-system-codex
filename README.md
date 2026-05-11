# LALIGENCE eKYC System

Web-first eKYC prototype for passport verification, active liveness, hand gesture challenge, selfie matching, passive liveness, and NIST IAL2-aligned decision results.

## Stack

- Backend: Python, FastAPI
- Frontend: React, Vite, TypeScript
- Design: LALIGENCE navy/gold brand system
- AI direction: local/open-source model adapters

## Run Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python3 scripts/install_face_models.py
uvicorn app.main:app --reload --app-dir backend --host 0.0.0.0 --port 8000
```

The OCR/MRZ adapter uses Tesseract through `pytesseract`. Install the Tesseract binary before running OCR:

```bash
brew install tesseract
```

## Run Frontend

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

For local development, the frontend uses Vite's `/api` proxy. For a hosted frontend, set:

```bash
cp frontend/.env.example frontend/.env
# then set VITE_API_BASE_URL to your deployed backend origin, for example:
# VITE_API_BASE_URL=https://laligence-ekyc-api.onrender.com
```

## API

- `POST /api/verifications`: create verification session with required JSON body `{ "user_id": "..." }`.
- `POST /api/verifications/{session_id}/document`: upload passport image. Optional multipart field `ocr_text` can be supplied when an OCR adapter extracts MRZ text.
- `POST /api/verifications/{session_id}/challenge`: mark one active liveness or hand challenge result.
- `POST /api/verifications/{session_id}/selfie`: submit selfie analysis result.
- `POST /api/verifications/{session_id}/enroll-face`: enroll a passed verification session as a returning-user Face ID.
- `POST /api/face-login`: capture a returning-user face, run passive liveness, and match against enrolled Face IDs.
- `GET /api/profiles`: list enrolled demo profiles.
- `DELETE /api/profiles/{user_id}`: delete one enrolled demo profile.
- `DELETE /api/profiles`: delete all enrolled demo profiles.
- `GET /api/verifications/{session_id}`: fetch current result.

## Fraud Detection Module

The backend document fraud pipeline is implemented in `backend/app/services/fraud.py` as layered analyzers:

- image loading and metadata extraction
- quality scoring for resolution, brightness, contrast, sharpness, and glare
- document-likeness scoring for passport/document structure
- ICAO TD3 MRZ parsing and check-digit validation when OCR text is available
- Tesseract OCR extraction for passport MRZ regions
- recapture-risk heuristics for screen, print, and photocopy artifacts
- tamper-risk heuristics based on compression and error-level signals
- risk scoring with explainable fraud signals

The current implementation is local and lightweight. It is ready for heavier open-source adapters such as PaddleOCR/docTR for OCR, DLC-2021-trained document liveness models, and DocTamper/TruFor/CAT-Net-style tamper localization.

## Face Matching And Passive Liveness

The selfie step now uses local OpenCV biometric models:

- YuNet ONNX for face detection.
- SFace ONNX for face embeddings and passport/selfie face matching.
- ONNX Runtime anti-spoof ensemble under `backend/models/anti_spoof/`:
  - `best_model_quantized.onnx`: facenox MiniFASNetV2-SE model, 128x128 RGB, 2-class real/spoof output.
  - `facenox_detector_quantized.onnx`: facenox face detector asset, installed for parity with the upstream demo. The backend currently uses YuNet for face boxes.
  - `MiniFASNetV2.onnx`: 80x80, 3-class MiniFASNet model.
  - `MiniFASNetV1SE.onnx`: 80x80, 3-class MiniFASNet model.
- A full-frame passive heuristic layer for screen/phone rectangle cues.

Install model files:

```bash
python3 scripts/install_face_models.py
```

The facenox classifier is treated as the primary passive anti-spoof model. Its two-class output follows the upstream order: class `0` is real and class `1` is spoof. The backend converts the two logits to a spoof risk, combines that with the companion MiniFASNet exports when available, and still hard-fails obvious phone/screen-frame attacks.

The passport upload route extracts an in-memory passport portrait embedding. The selfie route compares the selfie embedding against that session reference and rejects low matches or high passive spoof risk. Raw passport/selfie images are not stored by the backend.

## Returning User Face Login

After a verification reaches `passed`, call:

```bash
POST /api/verifications/{session_id}/enroll-face
```

The prototype creates a verified profile containing `user_id`, one active `face_id`, name fields, age/date of birth, nationality, passport number, passport expiry, verification session ID, and enrollment timestamp.

Enrollment uniqueness rules:

- one `user_id` maps to one active `face_id`; enrolling the same `user_id` again updates the existing active Face ID record.
- one `passport_number` maps to one verified profile; enrolling the same passport under a different `user_id` is rejected.

Returning users can then submit a live selfie to:

```bash
POST /api/face-login
```

The backend runs face detection, passive liveness/anti-spoofing, and SFace matching against enrolled templates. The default returning-user match threshold is controlled by `LALIGENCE_FACE_LOGIN_MATCH_THRESHOLD`.

Storage note: enrolled face templates and verified profile fields are stored through SQLAlchemy. Local development defaults to SQLite at `backend/data/laligence_profiles.sqlite3`; hosted deployments should set `DATABASE_URL` to PostgreSQL. Production still needs encrypted biometric-template storage, explicit consent, access controls, audit logs, retention limits, and account deletion.

For local retesting, list or clear enrolled users:

```bash
curl http://localhost:8000/api/profiles
curl -X DELETE http://localhost:8000/api/profiles/user-001
curl -X DELETE http://localhost:8000/api/profiles
```

These profile admin endpoints are for local demo/testing only. Protect or remove them before a real public deployment.

## Document Fraud Test Dataset

Local test data lives in `test_dataset/`. Seed it from the existing local labeled examples:

```bash
python3 scripts/install_test_dataset.py --seed-local
```

Evaluate the detector:

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_document_fraud.py --dataset test_dataset
```

Large public datasets are not downloaded automatically. To list available IDNet-2025 archives:

```bash
python3 scripts/install_test_dataset.py --list-idnet2025
```

To intentionally download and sample one multi-GB archive:

```bash
python3 scripts/install_test_dataset.py --download-idnet2025 EST --yes-large-download --extract --max-per-class 50
```

## MIDV-2020 Upload Benchmark

MIDV-2020 is distributed by the University of La Rochelle through an sFTP server after accepting the dataset license form. After you download and extract it locally, sample passport images into this project's benchmark folder:

```bash
python3 scripts/install_test_dataset.py --prepare-midv2020 /path/to/MIDV-2020 --max-per-class 50
```

If your MIDV-2020 copy contains videos and you also want frame samples:

```bash
python3 scripts/install_test_dataset.py --prepare-midv2020 /path/to/MIDV-2020 --max-per-class 50 --midv2020-video-frames --frames-per-video 2
```

Evaluate the real document upload API route:

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_document_upload.py --dataset test_dataset --only-folder genuine_midv2020_passport
```

## Public Demo Deployment

This project now includes the deployment baseline for a public tester demo:

- `Dockerfile`: containerized FastAPI backend with Tesseract and local model install.
- `render.yaml`: Render Blueprint for a Docker API service and static Vite frontend.
- `backend/.env.example`: backend production settings.
- `frontend/.env.example`: deployed API URL setting.
- `.dockerignore`: keeps local datasets, virtualenvs, and build output out of the container context.
- SQLAlchemy profile storage: PostgreSQL on Render through `DATABASE_URL`, SQLite fallback locally.

Public demo safety: use sample or redacted documents only. The backend does not persist raw uploads, but sensitive identity images still pass through the server process during analysis.

### Deploy On Render

1. Push this repository to GitHub.
2. In Render, create a Blueprint from the repository. The included `render.yaml` follows Render's [Blueprint service format](https://render.com/docs/blueprint-spec).
3. After Render creates the services, confirm these environment variables:
   - Backend `LALIGENCE_CORS_ORIGINS`: your frontend URL, for example `https://laligence-ekyc-web.onrender.com`.
   - Backend `DATABASE_URL`: the Render PostgreSQL internal connection string. The Blueprint wires this from `laligence-ekyc-db`.
   - Frontend `VITE_API_BASE_URL`: your backend URL, for example `https://laligence-ekyc-api.onrender.com`.
4. Open the frontend URL and test with sample/redacted passport images.

The free Render tier can sleep between requests. Render free PostgreSQL is useful for demos but should not be treated as durable production storage. Use paid services when you want smoother camera demos, model warm starts, backups, and stable retention.

### Run Backend With Docker Locally

```bash
docker build -t laligence-ekyc-api .
docker run --rm -p 8000:8000 \
  -e LALIGENCE_CORS_ORIGINS=http://localhost:5173 \
  laligence-ekyc-api
```

### Production Settings

- `LALIGENCE_CORS_ORIGINS`: comma-separated allowed frontend origins.
- `DATABASE_URL`: PostgreSQL connection string for hosted profile storage; defaults to local SQLite when omitted.
- `LALIGENCE_MAX_UPLOAD_SIZE_BYTES`: upload cap, default `8388608`.
- `LALIGENCE_MAX_REQUESTS_PER_MINUTE`: simple per-IP API limit, default `240`; set `0` to disable.
- `LALIGENCE_ALLOWED_UPLOAD_CONTENT_TYPES`: allowed image MIME types.
- `LALIGENCE_MIN_FACE_MATCH_SCORE`: selfie/passport face-match threshold.
- `LALIGENCE_MAX_PASSIVE_LIVENESS_RISK`: passive anti-spoof rejection threshold.
- `LALIGENCE_MAX_DOCUMENT_FRAUD_RISK`: document fraud rejection threshold.
- `LALIGENCE_FACE_LOGIN_MATCH_THRESHOLD`: returning-user face login match threshold.

## Notes

This first build includes working session flow and local heuristic document analysis. OCR, face matching, active liveness, hand gesture detection, and passive anti-spoofing are intentionally isolated behind service boundaries so production-grade open-source models can be integrated without changing the API contract.
