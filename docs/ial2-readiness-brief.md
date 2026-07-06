# NIST IAL2 Readiness Brief — Kyron eKYC

**Date:** 2026-07-01 · **Prepared for:** leadership / assessor · **Standard:** NIST SP 800-63A, Identity Assurance Level 2 (remote, unattended)

> **Honest status:** Kyron is **aligned toward IAL2 and assessment-*preparing*, not certified.** Do not claim IAL2 until an independent assessment is complete. This brief states exactly what is in place and what remains.

## Bottom line
Every IAL2 requirement that can be satisfied **in software is now implemented and tested** (148→156 automated tests). What remains is **not code** — it is a **dataset**, two **external integrations**, and an **independent assessment + budget**. The system is ready to enter formal pre-assessment once those are arranged.

## Standing against the IAL2 proofing steps

| # | IAL2 step | Status | Basis |
| --- | --- | --- | --- |
| 1 | **Resolution** — collect core attributes → one identity | ✅ Met | OCR: name, DOB, nationality, document number |
| 2 | **Evidence collection** — 1 STRONG/SUPERIOR piece | ✅ Met | Passport (TD3) / Lao ID capture |
| 3 | **Evidence validation** — genuine & valid | ◐ Partial | Tamper/print-replay checks + MRZ check-digit hard-fail; **no authoritative-source check yet** |
| 4 | **Biometric binding** — 1:1 face match to the doc portrait + liveness | ◐ Partial | Real 1:1 match + passive & active PAD; **performance not lab-proven** |
| 5 | **Address/contact confirmation** — enrollment code | ✅ **Met (new)** | Expiring, attempt-limited code to email/phone |
| 6 | **Notification of proofing** | ✅ **Met (new)** | Applicant notified at the confirmed contact |
| 7 | **Biometric performance** — FMR ≤ 1:10,000, PAD per ISO 30107-3, bias | ❌ Gap | Only LFW ~1% EER measured (wrong task & threshold) |
| 8 | **Fraud / injection resistance** (remote unattended) | ◐ Partial | Heuristics; **no device/SDK attestation** |
| 9 | **Records & PII security** | ✅ Met | Encryption at rest, cancelable templates, tamper-evident audit log, retention, consent |
| 10 | **Independent assessment** (e.g., Kantara) | ❌ Gap | Required to *claim* IAL2 |

## What is already done (strengths)
Full proofing flow (document → liveness → gesture → 1:1 face match → decision); **contact confirmation + notification** (steps 5–6); and a **production-grade security/privacy base** — encryption + **cancelable/renewable templates** (ISO 24745), **KMS-ready key management + rotation**, **per-user auth + RBAC**, **client-bound expiring sessions**, **tamper-evident audit logging**, **dependency scanning in CI**, **consent gate + self-service export/erasure**, and a drafted **ISMS** (policy set, DPIA, incident-response, gap assessment).

## What remains — and who owns it (none of it is application code)

| Gap | Type | Action |
| --- | --- | --- |
| **A. Operational FMR ≤ 1:10,000** (step 7) | **Data** | Collect genuine **document↔selfie pairs**; measure & tune FMR/FRR on the real task |
| **B. Authoritative-source validation** (step 3) | **Integration** | ICAO PKD passive-auth (passport chip) or an issuer/government data check |
| **C. Independent PAD test** (ISO 30107-3) + **bias study** (step 7) | **External + $** | Accredited lab (e.g., iBeta) |
| **D. IAL2 assessment** (step 10) | **External + $** | Kantara-accredited assessor |
| **E. Injection resistance** (step 8) | **Engineering** | Mobile SDK / device attestation |
| **F. In-region hosting + ops** | **Infra** | Execute the hosting plan (residency, KMS, PostgreSQL, backups) |

## Go / no-go for real-data proofing
**Not yet.** Before processing real identities: execute **F** (in-region, hardened hosting), obtain **A** (a measured FMR at the IAL2 bar), and complete legal review. Certification then follows via **C** and **D**.

## Recommended next step
Arrange a **genuine document↔selfie dataset** (Gap A). It is the single blocker that unlocks the real accuracy numbers every downstream claim and assessment depends on — and it is the prerequisite the labs and assessor will ask for first.

*Evidence: `docs/controls-standards-mapping.md` (clause-by-clause), `docs/policies/internal-gap-assessment.md` (full register), `docs/face-matching-results.md`, `docs/dataset-collection-plan.md`, `docs/in-region-hosting-plan.md`, `SECURITY.md`.*
