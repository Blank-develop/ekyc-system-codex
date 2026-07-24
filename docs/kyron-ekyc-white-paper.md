# Kyron eKYC: A Robust, Explainable, IAL2-Aligned Pipeline for Remote Identity Proofing and Face Login

**White Paper — Draft v1.0**
*Prepared: 2026-07-22*

**Authors:** Kyron Research Team ⟨add names/affiliations⟩
**Correspondence:** ⟨add contact⟩

> **Disclaimer.** Kyron is *designed toward* NIST SP 800-63A IAL2 alignment. This paper does not claim NIST, ISO, bank-grade, or government certification. All quantitative results are measured on the datasets described in §7 and are operating-point estimates pending a larger, independently labelled validation study.

---

## Abstract

Remote ("unsupervised") identity proofing must simultaneously (i) read and validate a government identity document, (ii) establish that a live human — not a photograph, screen, or mask — is present, and (iii) bind that human to the document portrait, all from consumer cameras under uncontrolled lighting and capture conditions. We present **Kyron eKYC**, a web-first pipeline (Python/FastAPI backend, React/Vite client) that composes document fraud detection, ICAO 9303 machine-readable-zone (MRZ) reading, passive presentation-attack detection (PAD), browser-side active liveness, and face matching into a single explainable risk decision aligned to NIST SP 800-63A Identity Assurance Level 2. We describe the architecture and, in particular, a set of **robustness fixes** that materially improve real-world read rates: correct handling of ICAO two-letter document types, MRZ-crop super-resolution, conditional illumination normalization, positional re-alignment of the OCR name line, and a mirrored-document detector. On a 150-image passport benchmark, MRZ detection rises from **52.9% → 67.3%** and fully check-digit-valid reads from **35.1% → 46.0%**; conditional on a valid read, date-of-birth and sex accuracy are **100%**, expiry **99%**, and document number **93%**. For selfie capture, face-region light metering plus a low-light rescue path raise dark-room face detection from **25% → 95%** with no regression on well-lit images. We discuss privacy-preserving data handling (no raw-image retention; embedding-only session state), the IAL2 alignment matrix, and the hardening required before formal certification.

**Keywords:** identity proofing, eKYC, NIST IAL2, presentation attack detection, liveness, MRZ/OCR, face recognition, ISO/IEC 30107.

---

## 1. Introduction

Digital onboarding for banking, telecom, and government services increasingly relies on **remote identity proofing**: a user, alone with a phone or laptop, presents an identity document and their face, and an automated system decides whether to trust the claimed identity. Unlike supervised (in-person) proofing, the system cannot control lighting, camera quality, document handling, or the presence of an operator to detect obvious spoofs. The adversary, by contrast, can present printed photos, replayed video, screen captures, masks, and tampered or substituted documents.

This paper describes Kyron eKYC, a prototype that treats remote proofing as a **composition of independent, individually-explainable checks** rather than a single black-box classifier. Each stage emits typed *reason codes* and calibrated risk contributions, and the final decision is an auditable function of those signals. This design is motivated by two requirements that pure end-to-end models struggle to satisfy: (a) regulatory expectations for explainability and redress, and (b) operational debuggability when a genuine user is wrongly rejected.

### 1.1 Contributions

1. **An explainable, standards-aligned pipeline** spanning document fraud detection, MRZ/OCR, passive and active liveness, and face matching, with a per-signal risk model (§3–§5).
2. **Robustness engineering for real-world capture** (§6): six OCR/MRZ correctness and legibility fixes and a two-part lighting-robustness change for selfies, each isolated and measured.
3. **An empirical evaluation** (§7) on document, spoof, and liveness datasets, reporting before/after effects of each robustness change and honest failure analysis.
4. **A NIST IAL2 alignment matrix and a hardening roadmap** (§8–§10) that separates what is demonstrated from what remains for certification.

---

## 2. Background and Standards Basis

Kyron is designed against four normative references:

- **NIST SP 800-63A (Digital Identity Guidelines — Enrollment & Identity Proofing).** IAL2 requires validation of a *strong* or *superior* piece of evidence, verification that the evidence belongs to the applicant (typically a biometric comparison with liveness), and fraud/duplicate checks. Kyron's document-plus-liveness-plus-match flow is structured around these obligations (§8).
- **ICAO Doc 9303 (Machine Readable Travel Documents).** Defines the TD3 passport MRZ: two 44-character lines, field offsets, the 7-3-1 weighted check-digit scheme, and the composite check. Kyron's reader implements TD3 parsing and check-digit validation directly (§4.2).
- **ISO/IEC 30107-3 (Biometric Presentation Attack Detection).** Frames PAD evaluation in terms of Attack Presentation Classification Error Rate (APCER) and Bona-fide Presentation Classification Error Rate (BPCER). Kyron's passive and active liveness stages target this trade-off (§4.3–§4.4, §7).
- **FATF Digital ID Guidance.** Motivates risk-based assurance, auditability, and ongoing monitoring; reflected in the reason-code/audit design (§8).

---

## 3. System Architecture

### 3.1 End-to-end flow

```
Start / user_id
   │
   ▼
Document capture (passport / Lao ID)
   │   quality • document-likeness • MRZ/OCR • forensics • fraud ensemble
   ├─ reject ──► retake (with specific reason code)
   ▼ pass
Active liveness  (browser MediaPipe FaceMesh: blink / mouth / head-turn)
   │            + backend evidence-burst PAD (anti screen/replay)
   ▼
Randomized hand-gesture challenge  (3 of 23 gestures, easy-weighted)
   ▼
Selfie passive liveness + face match  (10-frame burst; YuNet+SFace vs. document portrait)
   ▼
Risk decision  (typed reason codes; document / fraud / match / passive-risk)
   ▼
Enroll one active Face ID  ──►  Returning-user face login
```

### 3.2 Design principles

- **Composition over monolith.** Every stage is independently testable and emits reason codes; the decision layer is a transparent aggregation, not a learned end-to-end score.
- **Client/edge split.** Latency-sensitive, privacy-sensitive work (landmark tracking, image optimisation, live lighting feedback) runs in the browser; trust-bearing decisions (PAD models, MRZ validation, face matching) run server-side so they cannot be forged by a modified client.
- **Fail-explainable.** A rejection always carries a human-actionable reason (e.g. *MRZ_NOT_READ*, *DOCUMENT_MIRRORED*, *SELFIE_FACE_UNDEREXPOSED*) rather than a bare score.
- **Privacy by construction.** Raw document/selfie images are not persisted during verification; only transient face embeddings live in session state, and only a template + minimal profile are stored on enrollment (§8.2).

### 3.3 Implementation

Backend: Python/FastAPI, with service boundaries for document fraud (`fraud.py`), model-style document adapters (`document_models.py`), face biometrics and PAD (`face_biometrics.py`), and selfie aggregation (`selfie.py`). Profiles persist via SQLAlchemy (SQLite locally, PostgreSQL in deployment). Frontend: React/Vite with camera-capture components and in-browser MediaPipe FaceMesh/Hands. OCR uses Tesseract; face detection/recognition uses OpenCV YuNet + SFace; PAD uses an ONNX MiniFASNet-family ensemble with heuristic corroboration.

---

## 4. Methods

### 4.1 Document quality, likeness, and forensics

Before OCR, each upload is scored for resolution, brightness, contrast, sharpness, and glare, and for *document-likeness* (edge density, rectangularity) to reject non-document uploads (selfies, screenshots, PDFs). Forensic analyzers estimate recapture risk (screen/photo-of-photo), tamper risk (error-level and block-artifact cues), and **portrait substitution** (a common attack where the MRZ/body is genuine but the photo is swapped, detected via saturation/noise discontinuities in the portrait region conditioned on `mrz_valid`). A heuristic + optional-ONNX **document-fraud ensemble** fuses these into a fraud-risk score.

### 4.2 MRZ / OCR (ICAO TD3)

Passport reading extracts the two MRZ lines, parses TD3 field offsets, and validates the document-number, birth-date, expiry, optional, and composite check digits with the 7-3-1 weighting. A valid read yields document number, nationality, name, date of birth, sex, and expiry. Crucially, **validity is anchored on the check-digit-protected line-2 data**, so the number/DOB/expiry are trustworthy whenever `mrz_valid` is true; the alphabetic line-1 name field, which carries no check digit, is treated as best-effort and corrected by the heuristics in §6.

### 4.3 Passive liveness / PAD (selfie)

The selfie stage captures a **10-frame burst** and aggregates per-frame PAD. Detection combines an ONNX MiniFASNet-family model with corroborating heuristics for screen-frame borders, display-surface texture (moiré), paper-photo texture, and hand-held-phone cues, plus **temporal burst checks** (near-static frames and absent natural brightness variation indicate a replay). A single-frame model spike is deliberately *not* sufficient to reject a bona-fide user; a held-phone verdict requires recurrence *and* corroboration, which is the fix that eliminated the eyeglass false-positive described in §7.3.

### 4.4 Active liveness (challenge–response)

The client runs MediaPipe FaceMesh and issues randomized action challenges — blink, open mouth, turn left/right — detected from landmark geometry (eye-aspect ratio, mouth-open ratio, and a nose-offset yaw estimate). On detection, the client sends a short **evidence burst** to the backend, which re-runs face detection and PAD so that a challenge cannot be satisfied by a modified client alone. A randomized **hand-gesture challenge** (three gestures drawn from a 23-gesture set, easy-weighted so at most one "tricky" gesture appears per session) adds an interaction that is expensive to pre-render for replay.

### 4.5 Face matching and Face ID

Face matching uses OpenCV **YuNet** detection and **SFace** embeddings, comparing the live selfie embedding to the document-portrait embedding by cosine similarity against a pass threshold (with a borderline band that raises a medium signal). On a passed session, exactly one active face template is enrolled per `user_id`, and one verified profile per document number, enabling returning-user **face login** that re-checks passive liveness before matching against stored templates.

### 4.6 Decisioning

The final decision is a transparent aggregation: any high-severity signal hard-fails; otherwise medium signals accumulate into quality/passive-risk scores that must fall below calibrated thresholds, and the face-match score must clear its pass threshold. Every response carries the contributing reason codes, which drive both the user-facing retake guidance and the admin audit view.

---

## 5. Threat Model

We assume a remote attacker who may: present a **printed photo, photocopy, or scan** of a genuine document; **replay a screen/video** of a face; wear a **paper/cutout mask**; present a **tampered or portrait-substituted** document; hold a **phone/tablet screen** to the camera; or exploit **capture artifacts** (mirroring from a front camera, extreme back-light) to slip a spoof through as "just poor quality." We do *not* claim defense against high-fidelity 3-D masks, injection attacks on a compromised device/OS, or coerced-genuine-user scenarios; these are out of scope for a software-only prototype and are noted in §9.

---

## 6. Robustness Engineering (this work)

Field testing surfaced that the dominant cause of *bona-fide* failures was not the models but the **capture front-end**: real documents that would not read, and real faces that would not detect, under ordinary phone-camera conditions. We isolated and measured six document/MRZ fixes and one two-part lighting fix.

### 6.1 ICAO two-letter document type acceptance

The MRZ line-1 selector required a `P<` prefix, silently rejecting every passport whose type sub-category is a *letter* (Lao `PO`, diplomatic `PD`, service `PS`, …) — before any check digit was evaluated. We broadened acceptance to `P` + (`<` or letter) + a 3-letter issuing country, using a digit-count guard to keep the alphabetic name line distinct from the numeric data line. This was the single largest driver of the read-rate gain (§7.2); a *perfect* `PO`-type MRZ that previously failed now validates.

### 6.2 MRZ-crop super-resolution

Dataset images are small (median 726 px wide), so a TD3 glyph is ~6–10 px tall — near Tesseract's floor. MRZ crops are now upscaled with smooth fractional LANCZOS to ~2600 px on the long side, and upright bottom-band crops were added (the prior region set was rotation-only).

### 6.3 Conditional illumination normalization

Dark or washed-out captures are normalized (CLAHE + gamma pull toward mid-tone) before OCR. Normalization is **conditional** — well-exposed images (mean luminance 0.20–0.80) stay on the original path — after we observed that unconditional CLAHE over-sharpened crisp glyphs and *induced* errors (`P`→`M`). This is a recurring lesson: enhancement must be gated to the regime it helps.

### 6.4 Line-1 positional re-alignment and filler-letter stripping

Because line 1 has no check digit, OCR noise there is uncorrected. Two conservative fixes: (i) a **doubled leading type character** (`POLAO…` misread as `PPOLAO…`, which shifts the country and every name character right by one) is detected — `PP` is not a valid type — and realigned; (ii) when the deep-filler tail is dominated by one letter (OCR rendering `<` as, e.g., `K`), a single trailing instance that bled onto a name token is stripped. Together these recovered `OCHANTHABANDITH / KITSANAK` → `CHANTHABANDITH / KITSANA` on a live example.

### 6.5 Nationality cross-fill

The nationality field (line 2) and issuing country (line 1) are the same ICAO 3-letter code. When OCR mangles the line-2 value into non-letters (`LAO`→`1OO`) but line 1's issuer is a clean 3-letter code, the issuer is used. This depends on §6.4 having correctly aligned line 1.

### 6.6 Mirrored-document detection

Front (selfie) cameras horizontally flip the frame, so a held document reads *backwards* and never parses. On the failure path only, Kyron re-reads a horizontally-flipped copy; if the flip yields a valid MRZ, the original was mirrored and a specific high-severity **`DOCUMENT_MIRRORED`** signal is emitted with retake guidance, instead of a generic "MRZ not read." This adds no cost to a normal successful read.

### 6.7 Lighting robustness for selfies

Two changes. **(a) Face-region metering:** brightness/contrast/glare are measured on the detected face crop rather than the whole frame, so a bright background behind a dark (back-lit) face is correctly diagnosed instead of reading "frame looks fine." **(b) Low-light rescue:** when face detection fails or the frame is under-exposed, detection/embedding is retried on an illumination-normalized copy (geometry-preserving, so the box remains valid for PAD, which stays on the original image to avoid disturbing spoof cues). A client-side live warning and capture-gating (with a "capture anyway" escape) prevent many bad frames pre-emptively.

---

## 7. Evaluation

### 7.1 Datasets

Evaluation uses the project's labelled sets: a passport corpus of 864 image/ground-truth pairs (820 passports, 44 face-only/non-passport), selfie passive-liveness and face-login sets (real-live match/non-match, phone/tablet/laptop screen, video replay, printed photo, paper mask, multiple/no faces), an active-liveness attack set, and print-copy document attacks. Passport ground truth is taken from the MRZ lines, which are canonical and unambiguous, rather than the noisier printed fields.

### 7.2 Passport MRZ/OCR read rate

150-image sample, all §6 document fixes enabled, versus the pre-fix baseline:

| Metric | Baseline | With fixes | Δ |
|---|---:|---:|---:|
| MRZ detected (readable) | 52.9% | **67.3%** | +14.4 pp |
| MRZ fully valid (all check digits) | 35.1% | **46.0%** | +10.9 pp |
| Passport number | 34.9% | 46.7% | +11.8 pp |
| Date of birth | 42.7% | 57.3% | +14.6 pp |
| Expiry date | 43.8% | 59.1% | +15.3 pp |

**Conditional accuracy** (given a fully-valid MRZ) confirms the parser is sound and the ceiling is OCR legibility, not logic: date-of-birth **100%**, sex **100%**, expiry **99%**, passport number **93%**, nationality **83–91%**. Face-only/non-passport images are correctly *not* read as passports **85–88%** of the time, and mirrored documents are rejected with the specific reason code (§6.6).

*Failure analysis.* Remaining non-reads are dominated by capture geometry — hand-held photos at arbitrary angles/perspective and glare — which super-resolution cannot recover. The highest-value next step is MRZ localization + deskew (§10).

### 7.3 Selfie PAD (presentation attack detection)

Corroboration-based aggregation (§4.3) eliminated a systematic bona-fide failure: real faces **wearing eyeglasses** previously triggered a held-phone/screen false-reject at ~43%; after requiring recurrence plus model corroboration, this fell to **0%** while screen/photo spoofs continued to be rejected at the prior rate in the tested sets. A back-light/over-exposure diagnosis (`SELFIE_LIGHTING_TOO_BRIGHT`, `SELFIE_FACE_UNDEREXPOSED`) converts a class of silent PAD false-rejects into actionable retake guidance.

### 7.4 Active-liveness anti-spoof gate

On collected attacks, the server-side gate (small-face rejection + recurring PAD-model vote over 3-frame bursts) rejected `fake_printed_photo` (120 images / 40 bursts) and `fake_phone_screen_replay` (50 images / 17 bursts) at **100%** with **0% false-accept**.

### 7.5 Lighting robustness

On 20 genuine selfies synthetically darkened to simulate a dim room, face-detection success (old → new):

| Condition | Baseline | With §6.7 |
|---|---:|---:|
| Dim room (×0.18) | 75% (15/20) | **100%** |
| Very dark (×0.12) | 25% (5/20) | **95%** |

Well-lit images were unchanged (20/20 detected; embeddings untouched), so there is **no regression** on the common case — the rescue path activates only for images that were already failing.

> **On headline figures.** Earlier collateral cites ~95.7% document and ~96.4% liveness accuracy; these remain *target/operating-point estimates* pending a ≥10k-per-category labelled study and are not claimed as validated here. The numbers in §7.2–§7.5 are the directly measured results of this work.

---

## 8. NIST IAL2 Alignment and Assurance

### 8.1 Alignment matrix (abridged)

| IAL2 obligation | Kyron mechanism | Status |
|---|---|---|
| Validate strong evidence | TD3 MRZ parse + check-digit validation; document quality/forensics; fraud ensemble | Demonstrated (prototype) |
| Evidence belongs to applicant | Face match (YuNet+SFace) selfie ↔ document portrait | Demonstrated |
| Presence / anti-spoof | Passive PAD burst + active challenge–response + backend evidence bursts | Demonstrated; APCER/BPCER not yet independently certified |
| Fraud / duplicate checks | Portrait-substitution + recapture + tamper signals; one-profile-per-document rule | Partial |
| Explainability / redress | Typed reason codes; admin audit view | Demonstrated (prototype); manual-review workflow pending |

### 8.2 Privacy and data handling

During verification, Kyron does **not** persist raw document or selfie images; it holds only transient face embeddings in session state. This is the default product posture. **Border and immigration deployments** operate under statutory authority and instead retain, behind an explicit configuration flag, the frames from every step together with an action timeline and an access log for each crossing; that evidence is downscaled, encrypted at rest, access-logged on every view, and expires on a five-year schedule. The two profiles are mutually exclusive and selected at deployment time. On a passed session it stores one face template plus a minimal verified profile (document number, name, nationality, birth date/age, expiry). Session state is short-lived and client-bound by a per-session token to defeat id-only replay/hijack.

### 8.3 Remaining hardening for certification

Encrypted, revocable biometric-template storage; explicit consent and retention controls; authenticated admin APIs and tamper-evident audit logging; independent PAD validation against ISO/IEC 30107-3 with reported APCER/BPCER; threshold calibration from large labelled sets; manual review and redress; MFA for high-value actions; and third-party security/privacy assessment.

---

## 9. Limitations and Threats to Validity

- **Sample size and provenance.** §7 uses hundreds, not tens of thousands, of images; some are synthetically perturbed (darkening). Absolute rates will shift on larger, field-representative data.
- **Ground-truth from MRZ.** Using MRZ as truth measures OCR fidelity to the printed MRZ, not to civil-registry identity.
- **PAD generalization.** Heuristic corroboration is tuned to observed attacks; novel display hardware or high-fidelity masks are not represented.
- **Out-of-scope attacks.** Camera/OS injection, deepfake video injection, and coerced-genuine-user cases are not addressed by a software-only client.

---

## 10. Future Work

1. **MRZ localization + perspective rectification** (detect the document, deskew, then OCR) — the single highest-ROI change for the remaining ~33% of non-read passports.
2. **Independent PAD benchmarking** with reported APCER/BPCER and a bona-fide error budget.
3. **Calibrated, per-population thresholds** for face match and passive risk, with fairness analysis across demographics and eyewear.
4. **Deepfake / injection resistance** (device attestation, signed capture, challenge entropy).
5. **A large labelled validation study** to convert target headline figures into certified operating points.

---

## 11. Conclusion

Kyron eKYC shows that a **composed, explainable** remote-proofing pipeline can be made materially more robust to real-world capture without sacrificing spoof resistance, by fixing the *front-end* failure modes that dominate bona-fide rejections: document-type handling, MRZ legibility, mirrored capture, and lighting. The measured gains — passport read validity 35%→46%, dark-room face detection 25%→95%, and elimination of the eyeglass PAD false-reject, all without regressions on the well-behaved case — argue for treating capture robustness as a first-class research target alongside model accuracy. The path to certification is a disciplined hardening and independent-validation program, not a change of architecture.

---

## References (indicative)

1. NIST SP 800-63A, *Digital Identity Guidelines: Enrollment and Identity Proofing.*
2. ICAO Doc 9303, *Machine Readable Travel Documents*, Parts 3 & 4 (TD3).
3. ISO/IEC 30107-3, *Information technology — Biometric presentation attack detection — Part 3: Testing and reporting.*
4. FATF, *Guidance on Digital Identity.*
5. Deng et al., *SFace / ArcFace-family face representation.*
6. Wu et al., *YuNet: A Tiny Millisecond-level Face Detector.*
7. MediaPipe Face Mesh and Hands (Google).
8. MiniFASNet / Silent-Face anti-spoofing family (ONNX).

*⟨Replace indicative references with full citations before external release.⟩*
