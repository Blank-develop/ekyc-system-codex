# Data Protection & Retention Policy

| | |
| --- | --- |
| **Owner** | Data Protection Officer (to be appointed) |
| **Applies to** | Kyron eKYC identity-verification system and all personnel/processors |
| **Version / date** | Draft v0.1 · 2026-07-01 |
| **Review** | Annually and on material change to processing |
| **Related** | [DPIA](dpia-biometric-ekyc.md) · [Incident Response Plan](incident-response-plan.md) · `SECURITY.md` |

> **Status:** draft for a demo/prototype. Requires legal review before real data.

## 1. Purpose & scope

This policy governs how Kyron eKYC collects, processes, secures, retains, and
deletes personal data — including **special-category biometric data** — during
identity proofing (document + face verification) and face-based login/payment.

It applies to all data captured through the verification flow, the profile store,
and any operational access to that data.

## 2. Roles & responsibilities

| Role | Responsibility |
| --- | --- |
| **Data Controller** | The operating entity; determines purposes/means, accountable for compliance |
| **Data Protection Officer (DPO)** | Owns this policy, DPIA, and breach handling; point of contact for data subjects/regulators |
| **System Operators** | Authenticated staff who access the console under least privilege (JWT + RBAC) |
| **Processors** | Hosting/infra providers under a written data-processing agreement (DPA) |

## 3. Lawful basis & principles

- **Lawful basis:** explicit **consent** for biometric processing and/or performance
  of a KYC obligation (FATF/AML). Biometric data is **special-category** — it
  requires an Art. 9 condition (explicit consent) in addition to an Art. 6 basis.
- **Consent evidence:** every enrolled profile records the **consent terms version
  and timestamp** (`LALIGENCE_CONSENT_VERSION`; `consent_version` / `consented_at`).
- **Principles applied:** lawfulness/fairness/transparency, **purpose limitation**
  (identity verification only), **data minimization**, accuracy, **storage
  limitation** (§6), integrity/confidentiality (§7), and accountability (§8).

## 4. Categories of data

| Category | Examples | Sensitivity |
| --- | --- | --- |
| **Biometric templates** | Face embedding (SFace vector) | Special category |
| **Identity-document PII** | Name, DOB, nationality, passport/document number, expiry | High |
| **Verification metadata** | Decision, reason codes, timestamps, consent version | Moderate |
| **Operational/technical** | Client IP, rate-limit counters, audit events | Moderate |

**Not stored:** raw document/selfie/liveness **images** are analyzed **in memory
only** and never written to disk. Face **embeddings are never exposed** through API
response schemas.

## 5. Data-minimization & security measures (summary)

| Measure | Control | Evidence |
| --- | --- | --- |
| No raw biometric media at rest | In-memory analysis only | verification pipeline |
| Encryption at rest | Fernet (AES-128-CBC+HMAC); PII in encrypted blob; passport number via **blind index** | `services/crypto.py`, `LALIGENCE_ENCRYPTION_KEY` |
| Access control | API-key gate + per-user OAuth2/JWT + RBAC; fail-closed admin | `services/auth.py`, `LALIGENCE_JWT_SECRET` |
| Masking | Redacted face-login response for unauthenticated callers | `LALIGENCE_FACE_LOGIN_EXPOSE_PII` |
| Rate limiting | Per-client + global throttles | `services/rate_limit.py` |
| **Audit trail** | Tamper-evident, hash-chained log of access/actions | `services/audit.py` |
| Transport security | HTTPS/HSTS in hosted deployments | `deploy/` (Caddy) |

Full posture: `SECURITY.md`. Standards mapping: `docs/controls-standards-mapping.md`.

## 6. Retention schedule

| Data | Retention | Mechanism |
| --- | --- | --- |
| Enrolled profile (template + PII) | For the retention window, then purged when **idle** past it | `LALIGENCE_PROFILE_RETENTION_DAYS` + `POST /api/profiles/purge-expired` |
| Verification session (in-memory) | Ephemeral; not persisted unless enrolled | session store |
| Audit events | Retained for the accountability period (set per jurisdiction/AML rules) | `services/audit.py` |

- **Default retention** is set by policy of the operating entity (AML rules commonly
  require multi-year record-keeping for KYC data; align the value accordingly).
- **Purge basis:** a profile is purged when its **last activity** (last login, else
  enrollment) is older than the window — recently-used profiles are retained.
- A **scheduled job** must invoke the purge endpoint (e.g. daily) in production.
- Retention is set to `0` (retain indefinitely) on the public demo, which holds
  **sample data only**.

## 7. Data-subject rights

| Right | How it is served |
| --- | --- |
| **Access / portability** | Operator can retrieve a profile via the console; self-service export is planned |
| **Erasure** ("right to be forgotten") | Admin `DELETE /api/profiles/{user_id}`; deletion is recorded in the audit log |
| **Rectification** | Re-verification / re-enrollment updates the profile |
| **Withdraw consent** | Triggers erasure of the associated profile |
| **Object / restrict** | Handled by the DPO case-by-case |

Requests are directed to the DPO and actioned within the statutory timeframe
(e.g. 30 days under GDPR-aligned regimes). Every erasure is auditable.

## 8. Accountability, transfers & processors

- **Records of processing** (GDPR Art. 30) are supported by the tamper-evident
  audit log of PII access and processing actions.
- **Cross-border / residency:** real Lao/SEA identity data must be hosted
  **in-region** per local law — see `docs/in-region-hosting-plan.md`. The public
  demo platform must never hold real PII.
- **Processors** (hosting, KMS) must be bound by a DPA and provide adequate
  security guarantees.

## 9. Breach handling

Suspected or actual breaches follow the [Incident Response Plan](incident-response-plan.md),
including regulator notification (≤72h where required) and data-subject
notification for high-risk biometric breaches.

## 10. Review

This policy is reviewed at least annually, on material change to processing, and
after any significant incident. Changes are versioned.
