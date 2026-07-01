# Data Protection Impact Assessment (DPIA) — Biometric eKYC

| | |
| --- | --- |
| **Assessment of** | Kyron eKYC — biometric identity proofing + face login/payment |
| **Why a DPIA** | Large-scale processing of **special-category biometric data** and identity documents = **high risk** → DPIA required (GDPR Art. 35) |
| **Owner** | Data Protection Officer (to be appointed) |
| **Version / date** | Draft v0.1 · 2026-07-01 |
| **Related** | [Data Protection & Retention Policy](data-protection-and-retention-policy.md) · [Incident Response Plan](incident-response-plan.md) · `docs/controls-standards-mapping.md` |

> **Status:** draft for a demo/prototype; to be completed and signed off by the DPO/
> controller before processing real identities.

## 1. Description of the processing

**Purpose.** Verify a person's identity from a government document and a live selfie
(IAL2-aligned proofing), and optionally authenticate returning users by face
(login / "Face Pay").

**Nature / data flow.**
1. User submits a passport / Lao ID and a live selfie + gesture/liveness actions.
2. The document is OCR'd and fraud-checked (tamper, print/replay, **TD3 MRZ** hard-fail).
3. Face is matched to the document portrait; **passive + active liveness (PAD)** run.
4. A decision (passed/rejected + reason codes) is produced.
5. On pass + consent, a **face template + minimized PII** is enrolled (encrypted).
6. Face login compares a fresh selfie against enrolled templates.

**Data subjects.** Individuals undergoing KYC (potentially the general public in a
target market). **Volume:** potentially large-scale.

**Data categories.** Biometric templates (special category), document PII (name,
DOB, nationality, document number, expiry), verification metadata, technical data
(IP). Raw images are **not** retained.

## 2. Necessity & proportionality

- **Necessity:** identity proofing is required to meet KYC/AML obligations and to
  prevent impersonation fraud; biometric verification is the means of binding the
  person to the document.
- **Proportionality / minimization:** raw media is analyzed **in memory** and
  discarded; only a template + minimal PII is stored, **encrypted**; embeddings are
  never exposed via the API; unauthenticated responses are **redacted**.
- **Lawful basis:** explicit **consent** (recorded, versioned) and/or legal KYC
  obligation. Consent can be withdrawn (→ erasure).
- **Retention:** limited by policy with automated purge of idle profiles.

## 3. Consultation

To be completed: input from the DPO, security lead, and — where required — the
supervisory authority (prior consultation if high residual risk remains). Data
subjects are informed via a consent notice at capture time.

## 4. Risk assessment

Likelihood/impact are rated **Low / Medium / High**; residual risk is **after** the
listed mitigations.

| # | Risk to individuals | Inherent | Mitigations (control) | Residual |
| --- | --- | --- | --- | --- |
| R1 | **Biometric breach** (template theft → irreversible harm) | High | Encryption at rest (`crypto.py`); **cancelable/renewable templates** (`template_protection.py`) so a leaked template is revocable by re-keying and the raw biometric is never stored; embeddings never in API; no raw images; access control | **Low–Medium** ⤓ (needs KMS keys to reach Low) |
| R2 | **PII exposure** (name/DOB/passport number) | High | Encrypted PII blob + blind index; redacted face-login; TLS | Medium |
| R3 | **Unauthorized access** to profiles | High | JWT + RBAC, fail-closed admin, API-key gate | Low |
| R4 | **Presentation/injection attack** → wrong person verified | High | Passive+active PAD, MRZ hard-fail, burst voting, nonce/ordering | Medium ⤓ (needs ⧉ independent PAD eval) |
| R5 | **Excessive retention** | Medium | Retention window + automated purge | Low |
| R6 | **No accountability / silent tampering** of records | Medium | **Tamper-evident hash-chained audit log** (`audit.py`) | Low |
| R7 | **Function creep / secondary use** | Medium | Purpose limitation policy; minimal storage | Low |
| R8 | **Cross-border transfer** to non-compliant jurisdiction | High | In-region hosting plan; demo is sample-only | Medium ⤓ (until in-region move executed) |
| R9 | **False rejection** excludes a legitimate user | Medium | Tunable thresholds; measured on LFW; fallback path | Medium (needs genuine-pair FRR) |
| R10 | **Brute-force / face harvesting** via API | Medium | Per-client + global rate limits | Low |

⤓ = residual risk still trending down as the noted item is completed.

## 5. Measures to reduce risk (planned to close residuals)

- **Cancelable/renewable templates** (ISO 24745) — **done** (`template_protection.py`); add **KMS-managed keys** to lower R1 to Low.
- **Independent PAD evaluation** (ISO 30107-3) and IAL2 assessment → lowers R4.
- **Execute in-region hosting** (`docs/in-region-hosting-plan.md`) → lowers R8.
- **End-to-end FRR** on genuine document↔selfie pairs → quantifies/lowers R9.
- **Consumer consent UI** + self-service erasure/export → strengthens R7/rights.

## 6. Outcome & sign-off

- **Residual risk:** **Medium**, trending to Low as §5 items complete. Acceptable for
  a **sample-only demo**; **not** acceptable for real data until R1/R4/R8 residuals
  are addressed and legal review is done.
- **Sign-off (to complete):** DPO ⬚ · Security lead ⬚ · Controller ⬚ · Date ⬚
- **Review:** re-run this DPIA on any material change (new data, new model, new
  jurisdiction) and at least annually.
