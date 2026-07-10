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
# Optional but recommended for Lao ID card names:
brew install tesseract-lang
```

For stronger Lao ID card OCR, install the optional Surya OCR stack and keep the default engine order:

```bash
pip install -r backend/requirements-surya.txt
export LALIGENCE_LAO_ID_OCR_ENGINE=surya,tesseract
```

Surya is used first for Lao ID cards when installed. Tesseract remains the fallback. Docker builds can include Surya with:

```bash
docker build --build-arg INSTALL_SURYA_OCR=true -t laligence-ekyc-api .
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
- `POST /api/verifications/{session_id}/document`: upload passport or Lao ID card image. Optional multipart field `ocr_text` can be supplied when an OCR adapter extracts document text.
- `POST /api/verifications/{session_id}/active-liveness`: submit the server-verified active liveness evidence frame or burst for one challenge.
- `POST /api/verifications/{session_id}/challenge`: mark one hand challenge result.
- `POST /api/verifications/{session_id}/selfie`: submit selfie analysis image or live burst.
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
- A full-frame passive heuristic layer for screen/phone/tablet display cues, including held-phone replay cues from visible side borders and fingers around the displayed face.
- The web active liveness step submits a 3-frame evidence burst after each blink/head/mouth action. The backend rejects strong display-surface replay evidence and repeated screen/tablet cues before marking the challenge as passed.
- The web selfie step submits a 10-frame live burst. The backend rejects recurring display/held-phone cues, strong model spoof signals, and bursts with almost no natural frame-to-frame motion or lighting change.

Install model files:

```bash
python3 scripts/install_face_models.py
```

The facenox classifier is treated as the primary passive anti-spoof model. Its two-class output follows the upstream order: class `0` is real and class `1` is spoof. The backend converts the two logits to a spoof risk, combines that with the companion MiniFASNet exports by default, and still hard-fails obvious phone/screen/tablet-frame attacks. Optional DeepPixBiS/CDCN ONNX exports can be added with `LALIGENCE_PAD_EXTRA_MODEL_PATHS` or by placing `DeepPixBiS.onnx` / `CDCN.onnx` in `backend/models/anti_spoof/`.

The passport upload route extracts an in-memory passport portrait embedding. The selfie route compares the selfie embedding against that session reference and rejects low matches or high passive spoof risk. Raw passport/selfie images are not stored by the backend.

## Hand Gesture Challenge

Each verification session assigns 3 random hand gestures from a 23-gesture catalog defined in `backend/app/services/session_store.py`. Sampling is easy-weighted: at least 2 of the 3 gestures always come from the easy pool (counting fingers, open palm, fist, thumb up, OK, pinched fingers, L shape), and at most one tricky gesture (rock on, call me, I love you, thumb down, crossed fingers) appears per session.

Detection runs in the browser with MediaPipe Hands (`frontend/src/components/HandGestureCapture.tsx`): the user moves a hand into a randomly placed circle, performs the prompted gesture, and holds it until the progress ring completes. Challenge cards and the full-screen view show each gesture's visual and a per-gesture instruction.

A user-facing guide for all gestures lives at `docs/hand-gesture-guide.md`, with branded one-page PDF/PNG exports:

```bash
python3 scripts/build_hand_gesture_guide_pdf.py
```

The script renders the guide with headless Google Chrome so gesture emoji match the web app. Rerun it after changing `HAND_PROMPTS`.

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

The backend warms Face ID models in the background after startup and caches active profile templates in memory, so repeated returning-user login attempts avoid repeated model/database cold starts. Face login responses include timing fields under `checks` for troubleshooting.

Storage note: enrolled face templates and verified profile fields are stored through SQLAlchemy. Local development defaults to SQLite at `backend/data/laligence_profiles.sqlite3`; hosted deployments should set `DATABASE_URL` to PostgreSQL. Production still needs encrypted biometric-template storage, explicit consent, access controls, audit logs, retention limits, and account deletion.

For local retesting, list or clear enrolled users:

```bash
curl http://localhost:8000/api/profiles
curl -X DELETE http://localhost:8000/api/profiles/user-001
curl -X DELETE http://localhost:8000/api/profiles
```

These profile admin endpoints are for local demo/testing only. Protect or remove them before a real public deployment.

## Mobile SDK

This repo includes mobile SDKs that wrap the eKYC backend API.

```bash
npm --workspace @laligence/ekyc-sdk run build
cd sdk/flutter && dart pub get && dart analyze && dart test
```

- TypeScript SDK: `sdk/typescript` for React Native, Expo, or any mobile JavaScript client.
- Flutter SDK: `sdk/flutter`, published as `laligence_ekyc` for Dart/Flutter apps.

Both SDKs expose `createVerification`, `uploadDocument`, `completeChallenge`, `analyzeSelfie`, `enrollFace`, `faceLogin`, and testing-only profile admin helpers. See `docs/mobile-sdk.md` and `docs/flutter-sdk.md` for mobile examples.

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

## Selfie Spoof Test Dataset

Install a small public selfie PAD sample set with screen-replay images and print/paper spoof frames:

```bash
.venv/bin/python scripts/install_selfie_spoof_dataset.py --max-screen-images 5 --max-paper-videos 1 --frames-per-paper-video 2
```

Install a larger 1000-image spoof benchmark by extracting still frames from the public AxonData video set:

```bash
.venv/bin/python scripts/install_selfie_spoof_dataset.py --max-screen-images 0 --max-paper-videos 0 --target-axon-large-images 1000 --axon-large-frames-per-video 10
```

Add your own real live selfies so false rejects can be measured:

```bash
.venv/bin/python scripts/install_selfie_spoof_dataset.py --skip-public --live-source /path/to/live-selfies
```

Evaluate the current passive liveness pipeline:

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_selfie_spoof.py --dataset test_dataset/selfie_spoof
```

The public installer uses Hugging Face datasets `AxonData/Display_replay_attacks`, `AxonData/print-cardboard-mask-face-spoofing`, and `AxonData/face-anti-spoofing-dataset`. The print/paper and larger AxonData sources are video-based, so the installer extracts still frames for the selfie route.

## Public Demo Deployment

This project now includes the deployment baseline for a public tester demo:

- `Dockerfile`: containerized FastAPI backend with Tesseract and local model install.
- `render.yaml`: Render Blueprint for a Docker API service and static Vite frontend.
- `deploy/digitalocean/`: Docker Compose deployment for a Singapore Droplet with FastAPI, PostgreSQL, and Caddy HTTPS.
- `vercel.json`: Vercel frontend deployment config for the Vite app.
- `backend/.env.example`: backend production settings.
- `frontend/.env.example`: deployed API URL setting.
- `.dockerignore`: keeps local datasets, virtualenvs, and build output out of the container context.
- SQLAlchemy profile storage: PostgreSQL on Render through `DATABASE_URL`, SQLite fallback locally.

Public demo safety: use sample or redacted documents only. The backend does not persist raw uploads, but sensitive identity images still pass through the server process during analysis.

### Recommended Deployment: DigitalOcean + Vercel

For a faster company demo in Laos/Southeast Asia, prefer:

- Backend: DigitalOcean Droplet in Singapore.
- Backend HTTPS: Caddy reverse proxy.
- Database: PostgreSQL in Docker Compose on the Droplet for demos, or DigitalOcean Managed PostgreSQL for stronger production durability.
- Frontend: Vercel static Vite deployment.

See the full guide:

```bash
deploy/digitalocean/README.md
```

Quick backend commands on the Droplet:

```bash
git clone https://github.com/Blank-develop/ekyc-system-codex.git
cd ekyc-system-codex
cp deploy/digitalocean/.env.example deploy/digitalocean/.env
# edit API_DOMAIN, LALIGENCE_CORS_ORIGINS, and POSTGRES_PASSWORD
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml up -d --build
curl -i https://api.your-domain.com/health
```

Vercel must set:

```bash
VITE_API_BASE_URL=https://api.your-domain.com
```

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
- `LALIGENCE_PAD_ENABLE_COMPANION_MODELS`: run the extra MiniFAS companion anti-spoof models. Default `true`; set `false` only for speed tests.
- `LALIGENCE_PAD_EXTRA_MODEL_PATHS`: comma-separated ONNX paths for additional PAD companions such as DeepPixBiS/CDCN exports.

## Notes

This first build includes working session flow and local heuristic document analysis. OCR, face matching, active liveness, hand gesture detection, and passive anti-spoofing are intentionally isolated behind service boundaries so production-grade open-source models can be integrated without changing the API contract.
