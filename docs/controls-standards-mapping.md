# Controls → Standards Mapping (Traceability Matrix)

**Phase 3 · pre-certification readiness.** This maps each Kyron eKYC **control**
we have built to the **standard requirement** it satisfies, with **evidence** (a
source file, test, config flag, or doc) an assessor can check. It is the backbone
of an audit: "for requirement X, show me the control and the proof."

> **Honest framing.** Status reflects *what is implemented and self-evidenced*, not
> certification. Items marked ⧉ **can only be closed by an independent assessor/lab**
> (e.g. ISO 30107-3 PAD testing, a Kantara IAL2 assessment). We do **not** claim
> NIST/ISO/bank-grade certification. See `SECURITY.md`.

## How to read a row

| Field | Meaning |
| --- | --- |
| **Requirement** | The standard's clause / obligation (paraphrased) |
| **Control** | What in Kyron satisfies it |
| **Status** | ✓ implemented · ◐ partial · ○ planned · ⧉ needs external assessor |
| **Evidence** | File / test / config / doc to inspect |

---

## 1. NIST SP 800-63A — Identity Proofing (target IAL2)

| Requirement | Control | Status | Evidence |
| --- | --- | --- | --- |
| Collect **STRONG/SUPERIOR** identity evidence | Passport / Lao ID capture + OCR | ✓ | `services/document_models.py`, `services/fraud.py` |
| **Validate evidence authenticity** (genuine, not tampered) | Document fraud analyzer (tamper, recapture/print-copy, likeness) + **TD3 MRZ hard-fail** | ✓ | `services/fraud.py` (`PassportFraudAnalyzer`), `tests/test_fraud.py` |
| MRZ / document integrity per ICAO | TD3 MRZ parse + check-digit validation; reject on invalid | ✓ | `test_fraud.py`, §8 below |
| **Verify** the applicant is the owner (biometric bind) | Face match (SFace) selfie ↔ document portrait | ◐ | `services/face_biometrics.py`; `docs/face-matching-results.md` (LFW: ~1% EER) |
| **Presentation-attack detection** during proofing | Passive PAD (MiniFASNet) + active liveness (gesture, FaceMesh) | ◐⧉ | `services/selfie.py`, `services/session_store.py`; `tests/test_active_liveness.py` |
| Bind proofing to a **verified live** subject, not a photo | Burst-mode PAD voting + active-liveness ordering + nonce | ✓ | `test_gesture_challenge.py`, `test_decision_passive_liveness.py` |
| **Record-keeping** of the proofing decision + reasons | Verification result with `reason_codes`; profile store | ✓ | `services/profile_store.py`, `models/schemas.py` |
| Protect collected PII / biometrics | Encryption at rest; no raw media to disk | ✓ | §4, §6 |
| **FMR/FNMR & PAD performance evidence** for IAL2 claim | Face-match measured (LFW); PAD not independently tested | ◐⧉ | `docs/face-matching-results.md`; `docs/dataset-collection-plan.md` |
| Independent IAL2 assessment (e.g. Kantara) | — | ⧉ | Phase 4 |

## 2. NIST SP 800-63B — Biometric Authenticator ("Face login" / Face Pay)

| Requirement | Control | Status | Evidence |
| --- | --- | --- | --- |
| Biometric used **with** liveness / PAD | Face login runs PAD before match | ◐ | `services/face_biometrics.py`, `api/routes.py` |
| **Rate-limit** biometric authentication attempts | Per-client + global throttle, proxy-aware IP | ✓ | `services/rate_limit.py`, `test_rate_limit.py`, `LALIGENCE_FACE_LOGIN_MAX_PER_MINUTE` |
| Limit information returned to unauthenticated callers | Face-login PII redaction (masked doc number, no DOB/expiry) | ✓ | `test_face_login_redaction.py`, `LALIGENCE_FACE_LOGIN_EXPOSE_PII` |
| FMR ≤ threshold for authenticator use | Match threshold configurable; measured on LFW | ◐ | `LALIGENCE_FACE_LOGIN_MATCH_THRESHOLD`, `docs/face-matching-results.md` |
| Don't transmit/store raw biometric | Embeddings only; never exposed in API schemas | ✓ | `models/schemas.py` (no embedding fields) |
| Session binding / freshness | Unguessable + short-lived (idle/absolute TTL) + **client-bound** session token (`X-Session-Token`) | ✓ | `services/session_store.py`, `tests/test_session_security.py` |

## 3. ISO/IEC 30107-3 — Presentation Attack Detection (PAD)

| Requirement | Control | Status | Evidence |
| --- | --- | --- | --- |
| Detect **presentation attack instruments** (print, screen, replay) | Passive PAD + screen/print/held-phone heuristics | ◐ | `services/face_biometrics.py`, `services/selfie.py` |
| Detect video/replay & injected media | Active liveness (randomized gesture + face actions), burst voting | ◐ | `services/session_store.py`, `test_active_liveness.py` |
| Attack-set testing (our internal) | Print-photo + phone-screen replay sets rejected in testing | ◐ | `scripts/evaluate_active_liveness_dataset.py`, `docs/security-test-cases.md` |
| **APCER / BPCER** reported under lab conditions | Not independently measured | ⧉ | Phase 4 (iBeta / accredited lab) |
| Injection-attack defense (virtual camera, deepfake) | Device attestation / SDK integrity | ○ | `SECURITY.md` Tier 2 |

## 4. ISO/IEC 24745 — Biometric Template Protection

| Requirement | Control | Status | Evidence |
| --- | --- | --- | --- |
| **Confidentiality** of stored templates | Fernet (AES-128-CBC + HMAC) encryption at rest | ✓ | `services/crypto.py`, `test_crypto.py`, `LALIGENCE_ENCRYPTION_KEY` |
| PII confidentiality | PII encrypted blob + plaintext columns nulled | ✓ | `services/profile_store.py` (`_apply_profile`), `test_privacy.py` |
| Queries without exposing the value | **Blind index** (keyed HMAC) for passport uniqueness | ✓ | `crypto.py` (`blind_index`), `test_crypto.py` |
| **Irreversibility** (can't reconstruct biometric) | Embeddings not images; key-derived transform + encryption so raw biometric never stored | ◐ | `services/template_protection.py`, `crypto.py` |
| **Unlinkability / renewability** (cancelable templates) | **Key-derived orthonormal transform** — revocable/renewable by re-keying, unlinkable across keys, score-preserving | ✓ | `services/template_protection.py`, `tests/test_template_protection.py`, `LALIGENCE_TEMPLATE_PROTECTION_KEY` |
| **Key management** (protect the key) | **KMS-ready sourcing** (`file:`/`command:`/`env:` specs) + **rotation** (retired keys decrypt/verify); managed KMS/HSM still to wire | ◐ | `services/key_provider.py`, `tests/test_key_provider.py` |

## 5. ISO/IEC 27001 — ISMS (Annex A themes)

| Theme (A.5–A.8) | Control | Status | Evidence |
| --- | --- | --- | --- |
| **Access control** (A.5.15–18) | API-key gate + per-user OAuth2/JWT + RBAC + fail-closed admin | ✓ | `services/auth.py`, `test_auth.py`, `test_admin_endpoints.py`, `test_api_auth.py` |
| **Cryptography** (A.8.24) | Encryption at rest; TLS/HSTS in hosted deploys | ✓ | `crypto.py`, `deploy/digitalocean/` (Caddy) |
| **Secure development** (A.8.25–28) | Input validation, upload guards, tests in CI | ◐ | upload allowlist/size cap in `api/routes.py`; test suite |
| **Logging & monitoring** (A.8.15–16) | **Tamper-evident hash-chained audit log** of auth, PII access, admin actions, enrollment; integrity-verify endpoint | ◐ | `services/audit.py`, `tests/test_audit.py`, `GET /api/audit/verify` |
| **Data masking** (A.8.11) | Face-login redaction | ✓ | `test_face_login_redaction.py` |
| **Rate limiting / DoS** (A.8.6 capacity) | Per-IP + face-login throttles | ◐ | `services/rate_limit.py` |
| **Backup** (A.8.13) | Encrypted in-region backups | ○ | Planned — `docs/in-region-hosting-plan.md` §5 |
| ISMS policies, risk assessment, SoA, internal audit | **Policy set + internal gap assessment (partial SoA + G1–G21 register)** done; full 93-control SoA, risk-treatment plan, and internal audit programme still to do | ◐ | `docs/policies/` (incl. `internal-gap-assessment.md`) |

## 6. GDPR / Data-Protection Law (biometric = special category)

| Requirement | Control | Status | Evidence |
| --- | --- | --- | --- |
| **Lawful basis / explicit consent** for special-category data | Consent version + timestamp recorded per profile | ◐ | `test_privacy.py`, `LALIGENCE_CONSENT_VERSION` (backend record; consumer consent **UI** still needed) |
| **Data minimization** | No raw media stored; embeddings only; redaction | ✓ | `profile_store.py`, `test_face_login_redaction.py` |
| **Storage limitation / retention** | Retention window + auto-purge endpoint | ✓ | `purge_expired_profiles`, `test_privacy.py`, `LALIGENCE_PROFILE_RETENTION_DAYS` |
| **Right to erasure** | Admin delete endpoint (+ planned self-service) | ◐ | `test_privacy.py`, admin `DELETE /api/profiles/{user_id}` |
| **Security of processing** (Art. 32) | Encryption, access control, throttling | ✓ | §4, §5 |
| **Records of processing / accountability** (Art. 30) | Tamper-evident audit log of PII access + processing actions | ◐ | `services/audit.py`, `tests/test_audit.py` |
| **Data residency / transfers** | In-region hosting **plan** written; not executed | ○ | `docs/in-region-hosting-plan.md` |
| **Breach notification**, DPIA | Not documented | ○ | Phase 3/4 |

## 7. FATF — AML / KYC (CDD)

| Requirement | Control | Status | Evidence |
| --- | --- | --- | --- |
| **Customer identification & verification** (CDD) | Full identity-proofing flow (doc + biometric) | ◐ | §1 |
| **Record-keeping** of identification data | Profile store + verification records; retention config | ✓ | `profile_store.py`, `LALIGENCE_PROFILE_RETENTION_DAYS` |
| Ongoing monitoring / sanctions / PEP screening | Not in scope of this system | ○ | Out of scope (upstream AML system) |

## 8. ICAO Doc 9303 — Machine-Readable Passports

| Requirement | Control | Status | Evidence |
| --- | --- | --- | --- |
| Parse **TD3 MRZ** (2×44) | MRZ extraction | ✓ | `services/fraud.py` |
| **Check-digit** validation of MRZ fields | Validated; hard-fail on mismatch | ✓ | `tests/test_fraud.py` |
| Cross-check MRZ ↔ visual zone | Partial (OCR vs MRZ consistency) | ◐ | `services/fraud.py` |
| Chip (eMRTD / BAC/PACE) verification | Not implemented (no NFC chip read) | ○ | Out of current scope |

---

## Readiness summary by standard

| Standard | Coverage | Blocking gap to assessment |
| --- | --- | --- |
| NIST 800-63A (IAL2) | ◐ strong | Independent assessment; end-to-end FRR on genuine pairs |
| NIST 800-63B (authenticator) | ◐ | PAD performance evidence |
| ISO/IEC 30107-3 (PAD) | ◐ | ⧉ Accredited-lab APCER/BPCER |
| ISO/IEC 24745 (template protection) | ◐ strong | Cancelable/renewable templates **done**; remaining: KMS keys, one-way transform |
| ISO/IEC 27001 (ISMS) | ◐ | Audit logging, full ISMS docs, internal audit |
| GDPR / local law | ◐ | Consumer consent UI, residency execution, DPIA |
| FATF (KYC) | ◐ | (Screening handled upstream) |
| ICAO 9303 | ✓ (MRZ) | Chip read out of scope |

## Top gaps to close next (Phase 3 → 4)

1. ~~Audit logging (tamper-evident)~~ — **done** (`services/audit.py`, hash-chained + integrity-verify). Remaining: ship to an external WORM/SIEM sink and cover per-step decisions.
2. **Cancelable/renewable biometric templates** (ISO 24745) beyond encryption; **KMS-managed keys**.
3. **Independent PAD evaluation** (ISO 30107-3) and an **IAL2 assessment** (Kantara) — ⧉ external, budgeted (Phase 4).
4. **End-to-end FRR** on genuine document↔selfie pairs (the real accuracy number) — `docs/dataset-collection-plan.md`.
5. **Consumer consent UI** + **self-service erasure/export**, and **execute** in-region hosting.
6. **Full ISMS documentation** — core policies + **internal gap assessment** (partial SoA + prioritized G1–G21 register) **done** (`docs/policies/`). Remaining: full 93-control SoA, risk-treatment plan, and internal audit programme.

---

*Cross-references:* `SECURITY.md` (posture + production-readiness tiers),
`docs/security-test-cases.md` (A1–A16 attack/security tests), `docs/face-matching-results.md`,
`docs/dataset-collection-plan.md`, `docs/in-region-hosting-plan.md`, `docs/roadmap.html`,
`docs/nist-ial2-test-case-plan.md`.
