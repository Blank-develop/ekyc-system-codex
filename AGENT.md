# LALIGENCE eKYC Agent Guide

## Product Goal

Build a web-first, mobile-ready eKYC system for passport identity proofing aligned with NIST IAL2. The first version uses a Python backend, local/open-source AI model adapters, and stores verification results only.

## Current Scope

- Passport capture by upload or browser camera.
- Active face liveness challenge.
- Hand gesture challenge with three randomized prompts.
- Selfie capture for face match and passive liveness.
- Automatic pass, reject, or pending decisions.
- No permanent storage of raw passport images, selfies, or biometric video.
- Returning-user login stores a local face template / Face ID plus verified OCR profile fields for demo matching.
- Verification sessions require a real `user_id` so enrollment can enforce one active Face ID per user.

## Architecture

- `backend/`: FastAPI API, verification result schema, fraud/liveness/model service boundaries.
- `frontend/`: Vite React web app with camera capture and branded verification workflow.
- `frontend/src/assets/logo.png`: LALIGENCE logo and brand anchor.
- `Dockerfile`: deployable backend container with Tesseract and local face model installation.
- `render.yaml`: public-demo Render Blueprint for the API and static frontend.
- `sdk/typescript`: mobile-ready TypeScript SDK for React Native, Expo, and other mobile clients calling the eKYC backend.
- `sdk/flutter`: Flutter/Dart SDK for mobile apps calling the eKYC backend, published as `laligence_ekyc`.
- Profile storage uses SQLAlchemy: PostgreSQL when `DATABASE_URL` is set, SQLite fallback at `backend/data/laligence_profiles.sqlite3` for local development.

## Design System

Use the local `ui-ux-pro-max` skill before major UI work:

```bash
python3 .codex/skills/ui-ux-pro-max/scripts/search.py "passport ekyc identity verification security fraud detection SaaS professional" --design-system -p "LALIGENCE eKYC" -f markdown
```

Brand adaptation:

- Primary: deep navy `#081632`, `#10255a`, `#18336f`.
- Accent: gold `#e7bf35`, `#d9ae27`.
- Background: quiet operational gray `#f6f8fc`.
- UI should feel like a serious security/finance workflow, not a marketing landing page.
- Use clear panels, compact controls, stable camera dimensions, visible focus/hover states, and no emoji icons.

## Backend Rules

- Use Python and FastAPI.
- Keep AI integrations behind service boundaries in `backend/app/services`.
- Document fraud detection uses a layered ensemble architecture:
  - `backend/app/services/fraud.py` orchestrates image loading, quality, document likeness, OCR/MRZ, forensics, model ensemble, and decision scoring.
  - `backend/app/services/document_models.py` owns document fraud model adapters.
  - Every model adapter returns a normalized finding with `model_id`, family, score, confidence, status, version, and reason.
  - The default ensemble runs baseline local heuristic adapters for document liveness/recapture, global tamper risk, passport portrait substitution risk, plus an optional ONNX adapter.
  - Portrait substitution checks must be MRZ-aware: a valid MRZ can lower weak portrait-region mismatch, because real printed passport portraits often have higher contrast than the document body.
  - Passport upload must contain readable TD3 MRZ evidence. `MRZ_NOT_READ`, `MRZ_INVALID`, and `MRZ_CHECK_DIGIT_MISMATCH` are hard-fail signals for passport proofing, because generic photos can otherwise look document-like from edge/quality heuristics.
  - A trained model can be added without changing the API by implementing the `DocumentFraudModel` protocol and adding it to `DocumentFraudModelEnsemble`.
- Prefer local/open-source models:
  - Passport OCR/MRZ: PaddleOCR, docTR, PassportEye, or equivalent.
  - Document liveness/recapture: a DLC-2021-style classifier for printed, screen-replayed, photocopied, and original document captures.
  - Document tamper localization: DocTamper-style text tamper detector, CAT-Net-style compression artifact detector, or TruFor-style image forgery model.
  - Face detection/matching: OpenCV YuNet + SFace is the current local backend implementation; InsightFace can be evaluated later if model licensing is acceptable.
  - Face/hand landmarks: MediaPipe or equivalent.
  - Passive liveness: current backend uses facenox/Silent-Face-Anti-Spoofing ONNX models plus a local heuristic PAD layer for screen/photo replay cues.
- Face biometric session handling:
  - Passport upload extracts a face embedding from the document portrait and stores it only in the in-memory session store.
  - Selfie upload extracts a selfie embedding, compares it with the passport portrait embedding, and rejects low matches.
  - Current SFace UI-normalized pass threshold is `0.68`, derived from OpenCV's published cosine threshold of `0.363`; scores around `0.68` to `0.74` should be treated as acceptable but worth monitoring during calibration.
  - Passive PAD checks the face crop plus the full frame for a phone/screen-like rectangle around the detected face. `SELFIE_PHONE_SCREEN_FRAME` is a high-risk hard fail.
  - Selfie capture requires exactly one usable face. `SELFIE_MULTIPLE_FACES` is a high-risk hard fail because it catches phone/screen replay where both the real holder and the replayed face are visible.
  - Selfie face confidence below the local threshold is a hard fail (`SELFIE_FACE_CONFIDENCE_LOW`) to prevent animal/object false positives from YuNet.
  - Passive PAD runs ONNX Runtime anti-spoofing from `backend/models/anti_spoof/`: facenox `best_model_quantized.onnx` as the primary classifier (MiniFASNetV2-SE, 2-class, 128x128 RGB, class 0 real/class 1 spoof). Silent-Face-Anti-Spoofing-style `MiniFASNetV2.onnx` and `MiniFASNetV1SE.onnx` companion signals are available when `LALIGENCE_PAD_ENABLE_COMPANION_MODELS=true`.
  - Facenox is the calibration authority when available. Companion MiniFAS models may raise risk when they agree with facenox, but they should not hard-reject a live selfie by themselves because they can false-positive on glasses, shadows, and webcam compression.
  - `scripts/install_face_models.py` installs OpenCV YuNet/SFace plus the facenox `best_model_quantized.onnx` and `facenox_detector_quantized.onnx` assets. The backend uses YuNet for face boxes and the facenox classifier for passive anti-spoof scoring.
  - Do not expose face embeddings through API schemas or write raw biometric media to disk.
- Returning-user Face ID:
  - Enrollment is allowed only after `VerificationResult.decision == passed`.
  - `POST /api/verifications` requires `{ "user_id": "..." }`.
  - One `user_id` maps to one active `face_id`; repeated enrollment for the same user updates that active profile.
  - One `passport_number` maps to one verified profile; enrolling the same passport under another `user_id` must be rejected.
  - Store verified profile fields plus a face template through `FaceProfileStore`, backed by SQLAlchemy.
  - Use PostgreSQL in hosted deployments through `DATABASE_URL`; local development falls back to SQLite.
  - The `face_profiles` table enforces unique `user_id`, `passport_number`, and `verification_session_id` values.
  - `backend/data/` is ignored by git and docker context.
  - `POST /api/face-login` must run passive liveness before matching a returning user.
  - Face ID model warmup runs in a background startup thread; keep `/health` cheap and do not block app startup on model or database warmup.
  - Face login may skip passive PAD only when the login face already fails basic extraction/confidence/multiple-face checks, because matching cannot safely proceed.
  - Local retesting can use `GET /api/profiles`, `DELETE /api/profiles/{user_id}`, and `DELETE /api/profiles`; these are demo admin endpoints and must be protected or removed for production.
  - Production must add encrypted biometric-template storage, consent, access controls, audit logs, retention limits, and deletion workflows around the database.
- OpenCV face model files live under `backend/models/face/`; install them with `python3 scripts/install_face_models.py`.
- Optional trained document fraud ONNX adapter:
  - Set `LALIGENCE_DOCUMENT_FRAUD_ONNX_PATH=/absolute/path/to/model.onnx`.
  - Optionally set `LALIGENCE_DOCUMENT_FRAUD_ONNX_INPUT=input_name`.
  - For multi-class outputs, set `LALIGENCE_DOCUMENT_FRAUD_ONNX_FRAUD_INDEX` to the fraud/spoof class index; default is the last class.
  - Install `onnxruntime` and `numpy` only when a real model artifact is available.
  - Do not hardcode model weights or store uploaded passport images in the repo.
- Store only result metadata, scores, reason codes, and audit timestamps unless the product owner explicitly changes retention policy.
- Expired passport evidence must be rejected once OCR/MRZ expiry extraction is implemented.
- Public deployment must keep CORS origin allowlists explicit through `LALIGENCE_CORS_ORIGINS`; do not use wildcard CORS for the hosted demo.
- Uploaded images are capped by `LALIGENCE_MAX_UPLOAD_SIZE_BYTES` and restricted by `LALIGENCE_ALLOWED_UPLOAD_CONTENT_TYPES`.
- The simple per-IP rate limit is controlled by `LALIGENCE_MAX_REQUESTS_PER_MINUTE`; set it to `0` only for trusted internal testing.
- Mobile SDK clients should call the same backend API contract rather than duplicating fraud, OCR, face matching, or PAD logic on-device. Keep mobile camera capture and UI in the mobile app, then send image evidence to the backend with `@laligence/ekyc-sdk` or the Flutter `laligence_ekyc` package.

## Frontend Rules

- Build the actual verification application as the first screen.
- Match the logo: navy, gold, white, and restrained neutral surfaces.
- Use lucide-react icons for controls.
- Keep camera, document, and gesture frames dimensionally stable across viewport sizes.
- Use ARIA labels and live regions for dynamic status or errors.
- Do not add decorative hero sections, oversized marketing cards, or unrelated visual flourishes.
- Hosted frontends must set `VITE_API_BASE_URL` to the backend origin; local dev may leave it blank and use the Vite `/api` proxy.
- Public demos must show a visible warning telling testers to use sample or redacted documents only.

## Decision Policy

Automatic rejection is required when a hard-fail signal is present:

- Non-passport or unreadable evidence.
- Expired passport.
- High document fraud risk.
- Active liveness failure.
- Hand challenge failure.
- Passive liveness failure.
- Face match below threshold.
- Returning face login liveness failure or template match below `LALIGENCE_FACE_LOGIN_MATCH_THRESHOLD`.

Pending is allowed only while required checks have not been completed.

## Verification

Before handing off changes:

- Run backend import/compile checks.
- Run frontend TypeScript build.
- Start backend and frontend when practical.
- Check desktop and mobile layouts after significant UI work.
- For deployment changes, verify `npm run build`, `PYTHONPATH=backend .venv/bin/python -m compileall backend/app`, and Docker/Render config syntax by inspection.

## Fraud Benchmark Data

- Local benchmark data is organized under `test_dataset/`.
- `genuine/` means expected pass; every `fraud_*` folder means expected rejection.
- Use `scripts/install_test_dataset.py --seed-local` to copy known local test cases.
- Public sources such as IDNet-2025 are multi-GB archives; list sizes with `scripts/install_test_dataset.py --list-idnet2025` and require `--yes-large-download` before downloading.
- MIDV-2020 is license-gated and distributed by University of La Rochelle over sFTP after the user accepts the form. Use `scripts/install_test_dataset.py --prepare-midv2020 /path/to/MIDV-2020 --max-per-class 50` after the dataset is extracted locally.
- Use `backend/scripts/evaluate_document_fraud.py --dataset test_dataset` to report accuracy, false reject rate, false accept rate, precision, recall, per-folder results, and mistakes.
- Use `backend/scripts/evaluate_document_upload.py --dataset test_dataset --only-folder genuine_midv2020_passport` to test the actual FastAPI document upload route.
- Selfie PAD benchmark data lives under `test_dataset/selfie_spoof/`.
- Use `.venv/bin/python scripts/install_selfie_spoof_dataset.py --max-screen-images 5 --max-paper-videos 1 --frames-per-paper-video 2` to install a small public screen-replay plus print/paper spoof sample.
- Use `.venv/bin/python scripts/install_selfie_spoof_dataset.py --max-screen-images 0 --max-paper-videos 0 --target-axon-large-images 1000 --axon-large-frames-per-video 10` to install a larger 1000-image spoof benchmark from AxonData videos.
- Use `.venv/bin/python scripts/install_selfie_spoof_dataset.py --skip-public --live-source /path/to/live-selfies` to add genuine samples captured on real devices.
- Use `PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_selfie_spoof.py --dataset test_dataset/selfie_spoof` to report passive anti-spoof accuracy, false accept rate, false reject rate, and per-folder mistakes.
