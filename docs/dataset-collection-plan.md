# Dataset Collection Plan (Accuracy Measurement & Tuning)

Goal: collect the data needed to put **real accuracy numbers** (FAR / FRR) on
each function and tune its thresholds. Most models here are **pretrained**
(YuNet, SFace, facenox PAD, MediaPipe, Tesseract/Surya) — so the priority is
**measuring and tuning**, with optional **fine-tuning of the anti-spoof model**.

Reuse only **sample / redacted / consented** data. Do not commit real identity
images (`test_dataset/` and `backend/data/` are gitignored).

## Priority 1 — functions we cannot measure at all today

### 1A. Document upload (genuine passports)
The headline step is currently unmeasurable: the "genuine" folder is Estonian
ID cards (no TD3 MRZ), and `genuine_midv2020_passport/` is empty.

| Folder | Target | What to collect |
| --- | --- | --- |
| `test_dataset/genuine_midv2020_passport/` | full set | MIDV-2020 passport subset (needs the dataset licence request) — the real benchmark |
| `test_dataset/document_print_copy/real_camera_passport/` | 30+ (have 6) | Real/sample passport bio-pages photographed by phone, **MRZ clearly readable** |
| `test_dataset/document_print_copy/fake_printed_passport_on_paper/` | 30 (have 7) | Print a passport, photograph the paper |
| `test_dataset/document_print_copy/fake_photocopy_or_scan/` | 30 (have 0) | Photocopy / flatbed scan of a passport |
| `test_dataset/document_print_copy/fake_screen_display/` | 30 (have 0) | Passport shown on a screen, photographed |
| `test_dataset/document_print_copy/real_camera_lao_id/` | 30 (have 5) | Real Lao ID photographed by phone |

Run with: `scripts/evaluate_document_print_copy_dataset.py`.

### 1B. Face matching (selfie ↔ document) — the core of eKYC
Completely unmeasured; the 0.68 / 0.72 thresholds are unvalidated. Lay out one
folder per identity:

```
test_dataset/face_matching/
    person_001/
        reference.jpg     # the document portrait
        selfie_1.jpg      # live selfies of the SAME person (different angles/light)
        selfie_2.jpg
    person_002/
        reference.jpg
        selfie_1.jpg
    ...
```

| Need | Target | Why |
| --- | --- | --- |
| Identities (distinct people) | **50+** | The harness pairs them automatically |
| Selfies per identity | 2–4 | Genuine pairs (same person) → measures **false-reject** |
| Distinct people | as many as possible | Impostor pairs (different people) → measures **false-accept** |

Run with: `PYTHONPATH=backend .venv/bin/python scripts/evaluate_face_matching.py`
→ outputs FAR / FRR per threshold + the equal-error point, so you can validate
or retune `LALIGENCE_MIN_FACE_MATCH_SCORE`.

## Priority 2 — measured but incomplete

### 2A. Active liveness — live variety + missing attack types
Attacks are tested (printed photo, phone replay = 100%), but the live
false-reject rate is from ~30 images of essentially one person, and 3 attack
types are empty.

| Folder | Target | Notes |
| --- | --- | --- |
| `active_liveness/real_live_face/` | 120+ (have 30) | **Many people**, devices, indoor/outdoor — for a real FRR |
| `active_liveness/real_live_poor_lighting/` | 60 (have 31) | Dim / backlit / harsh light |
| `active_liveness/fake_tablet_screen_replay/` | 50 (have 0) | Face replayed on a tablet |
| `active_liveness/fake_laptop_screen_replay/` | 50 (have 0) | Face replayed on a laptop |
| `active_liveness/fake_video_replay_closeup/` | 50 (have 0) | Close-up phone video held to the camera |

Run with: `scripts/evaluate_active_liveness_dataset.py`.

### 2B. Selfie passive anti-spoof (PAD) — live selfies
You have 1000+ spoof samples but almost no live, so false-reject is unmeasured
(and FRR is exactly the issue we kept hitting). This is also the dataset to
**fine-tune** the PAD model if you choose to.

| Folder | Target | Notes |
| --- | --- | --- |
| `selfie_spoof/live_user_provided/` | 100–200 (have 0) | Real live selfies, many people / lighting |
| `selfie_passive_liveness_face_login/real_live_match/` | 100+ (have 36) | Live selfie matching the enrolled face |
| `selfie_passive_liveness_face_login/real_live_nonmatch/` | 50 (have 0) | Live selfie of a different person |
| `selfie_passive_liveness_face_login/real_live_poor_quality/` | 50 (have 0) | Blurry / dim / far live selfies |
| `selfie_passive_liveness_face_login/fake_tablet_laptop_screen/` | 40 (have 0) | Screen replay on tablet/laptop |
| `selfie_passive_liveness_face_login/fake_video_replay/` | 40 (have 0) | Video replay |

## Priority 3 — later / low

- **Face login (1:N returning user):** `test_dataset/face_login/*` are all empty.
  Collect `enrolled_real_live`, `unknown_real_live`, `enrolled_screen_replay`,
  `unknown_screen_replay`, `multiple_faces`, `no_valid_face` only if the
  returning-user / Face Pay flow is a priority.
- **Hand gesture:** client-side heuristic on MediaPipe — not dataset-trained.
  Skip unless gesture recognition is actually failing for users.

## Capture tips (consistency matters more than volume)

- Use the browser collector: `scripts/capture_selfie_dataset.py` (countdown +
  per-batch counter), choosing the target folder.
- For **live FRR**: maximise *variety* — many people, phones/laptops, lighting,
  glasses, hats, indoor/outdoor. A clean FRR needs ≥ ~10 people, not 100 shots
  of one person.
- For **attacks**: capture the spoof the way a real attacker would (hold the
  phone/photo at arm's length, fill the frame as a real face would).
- Label by putting each image in the correct folder — the evaluation scripts
  read the folder name as the ground-truth label.

## What "good" looks like

| Function | Target metric |
| --- | --- |
| Document upload | Genuine-passport read rate + print/screen rejection rate, on a real passport set |
| Face matching | FRR and FAR at the chosen threshold (near the equal-error point) |
| Active liveness | Attack detection ≥ high, with a measured live FRR across many people |
| Selfie PAD | Balanced FAR/FRR on a live + spoof set; FRR is the user-experience risk |
