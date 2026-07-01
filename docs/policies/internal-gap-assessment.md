# Internal Gap Assessment & Statement of Applicability

| | |
| --- | --- |
| **Assessment of** | Kyron eKYC — security & privacy posture vs. target standards |
| **Assessed against** | ISO/IEC 27001:2022 Annex A · NIST SP 800-63A (IAL2) · GDPR · ISO/IEC 30107-3 / 24745 |
| **Owner** | Security Lead / DPO (to be appointed) |
| **Version / date** | Draft v0.1 · 2026-07-01 |
| **Related** | [Controls→Standards Mapping](../controls-standards-mapping.md) · [DPIA](dpia-biometric-ekyc.md) · [Data Protection Policy](data-protection-and-retention-policy.md) · [Incident Response Plan](incident-response-plan.md) · `SECURITY.md` |

> **Status:** internal self-assessment of a demo/prototype. It is **not** an
> independent audit or certification, and does not substitute for one (Phase 4).
> Its purpose is to know, honestly, where we stand and what to close next.

## 1. Purpose & scope

Provide an honest, evidence-based view of which controls are in place, which are
partial, and which are missing — and turn that into a **prioritized closure plan**.
Scope: the eKYC backend, frontend/console, profile store, and hosting posture.

## 2. Method & rating scale

Each control area is rated on **implementation** and, where a gap exists, on
**severity** (risk if left unaddressed for real-data processing).

| Implementation | Meaning |
| --- | --- |
| ✓ Implemented | In place with evidence (file/test/config) |
| ◐ Partial | Present but incomplete or not production-grade |
| ○ Planned | Documented/intended, not built |
| ⧉ External | Can only be closed by an independent assessor/lab |
| N/A | Not applicable to this system |

| Gap severity | Meaning |
| --- | --- |
| 🔴 Critical | Blocks any real-data processing |
| 🟠 High | Required before production launch |
| 🟡 Medium | Important; can follow a controlled launch |
| ⚪ Low | Hardening / hygiene |

## 3. Statement of Applicability — ISO/IEC 27001:2022 Annex A

Material controls (representative; a full 93-control SoA is a Phase 3 follow-up).
"Appl." = applicable.

### A.5 Organizational

| Control | Appl. | Status | Evidence / Gap |
| --- | --- | --- | --- |
| A.5.1 Policies for information security | Y | ◐ | `SECURITY.md` + `docs/policies/`; needs formal approval/owners |
| A.5.7 Threat intelligence | Y | ○ | Gap: no feed/process |
| A.5.9–5.10 Asset inventory / acceptable use | Y | ○ | Gap: asset register |
| A.5.12–5.14 Classification / labelling / transfer | Y | ◐ | Data categories classified in policy; labelling informal |
| A.5.15 Access control | Y | ✓ | `services/auth.py` (JWT+RBAC), API-key gate, fail-closed admin |
| A.5.16 Identity management | Y | ◐ | Env-seeded users; needs DB-backed store + lifecycle |
| A.5.17 Authentication information | Y | ✓ | PBKDF2 hashing, HS256 tokens (`services/auth.py`, `test_auth.py`) |
| A.5.18 Access rights (review/revoke) | Y | ◐ | Rotate/revoke documented (IR plan); no periodic review yet |
| A.5.23 Cloud services security | Y | ◐ | Demo on shared platform; in-region plan written |
| A.5.24–5.28 Incident management | Y | ◐ | [Incident Response Plan](incident-response-plan.md); untested (no drill yet) |
| A.5.30 ICT readiness for continuity | Y | ○ | Gap: backup/restore + DR not implemented |
| A.5.31 Legal/contractual (privacy) | Y | ◐ | DPIA + policy drafted; legal review pending |
| A.5.34 Privacy & PII protection | Y | ◐ | Encryption, minimization, consent/retention; consent UI pending |

### A.6 People

| Control | Appl. | Status | Evidence / Gap |
| --- | --- | --- | --- |
| A.6.1–6.6 Screening, terms, awareness, NDA | Y | ○ | Gap: HR/onboarding controls (org-level, once staffed) |
| A.6.8 Security event reporting | Y | ◐ | Reporting path in IR plan; no tooling |

### A.7 Physical

| Control | Appl. | Status | Evidence / Gap |
| --- | --- | --- | --- |
| A.7.x Physical/environmental security | Partial | N/A→◐ | Delegated to hosting provider; on-prem option in hosting plan |

### A.8 Technological

| Control | Appl. | Status | Evidence / Gap |
| --- | --- | --- | --- |
| A.8.1–8.5 Endpoint / privileged access / auth | Y | ◐ | JWT+RBAC; MFA + privileged-access mgmt pending |
| A.8.6 Capacity management | Y | ◐ | Rate limits; no ML concurrency/queue control |
| A.8.9 Configuration management | Y | ◐ | Config via env vars; no baseline/hardening guide |
| A.8.11 Data masking | Y | ✓ | Face-login redaction (`test_face_login_redaction.py`) |
| A.8.12 Data leakage prevention | Y | ◐ | No raw media stored; embeddings not exposed; no DLP tooling |
| A.8.13 Backup | Y | ○ | 🟠 Gap: encrypted in-region backups + restore test |
| A.8.15–8.16 Logging & monitoring | Y | ◐ | **Tamper-evident audit log** (`services/audit.py`); no SIEM/alerting |
| A.8.20–8.24 Network / crypto | Y | ◐ | TLS/HSTS in deploy; **encryption at rest** (`crypto.py`); KMS + CSP pending |
| A.8.25–8.29 Secure development & testing | Y | ◐ | Test suite (120 passing), input/upload guards; no SCA/pentest |
| A.8.31–8.34 Separation / change / audit test protection | Y | ◐ | Audit-chain integrity; change mgmt informal |

## 4. NIST SP 800-63A (IAL2) gap summary

| Proofing requirement | Status | Gap |
| --- | --- | --- |
| Strong/superior evidence collection | ✓ | — |
| Evidence validation (fraud, MRZ) | ✓ | — |
| Applicant↔evidence binding (face match) | ◐ | End-to-end FRR on genuine pairs |
| Liveness / PAD during proofing | ◐⧉ | Independent PAD evaluation |
| Records of the proofing decision | ✓ | Now also in the audit log |
| Independent IAL2 assessment | ⧉ | Phase 4 (e.g. Kantara) |

## 5. Consolidated gap register (prioritized)

| ID | Gap | Standard(s) | Severity | Effort | Phase |
| --- | --- | --- | --- | --- | --- |
| G1 | Execute **in-region hosting** (residency) | GDPR, ISO A.5.23 | 🔴 Critical | M | 2 |
| G2 | **KMS-managed keys** (not bare env var) + rotation | ISO 24745, A.8.24 | 🟠 High | M | 2 |
| G3 | **PostgreSQL hardening** (private, TLS, encrypted, least-priv) | ISO A.8.24 | 🟠 High | M | 2 |
| G4 | **Encrypted backups + restore/DR test** | ISO A.8.13, A.5.30 | 🟠 High | M | 2 |
| G5 | **Cancelable/renewable templates** | ISO 24745 | 🟠 High | L | 3/4 |
| G6 | **Independent PAD evaluation** | ISO 30107-3 | 🟠 High | ⧉/$$ | 4 |
| G7 | **Independent IAL2 assessment** | NIST 800-63A | 🟠 High | ⧉/$$ | 4 |
| G8 | **End-to-end FRR** on genuine doc↔selfie pairs | NIST 800-63A | 🟠 High | M | 1 |
| G9 | **Consumer consent UI** + self-service erasure/export | GDPR | 🟡 Medium | M | 2/3 |
| G10 | **Audit → external WORM/SIEM** + monitoring/alerting | ISO A.8.15-16 | 🟡 Medium | M | 3 |
| G11 | **Session security** (short-lived, client-bound tokens) | NIST 800-63B | 🟡 Medium | S | 2 |
| G12 | **Injection defense** / device attestation | ISO 30107-4 | 🟡 Medium | L | 4 |
| G13 | **Dependency scanning** (SCA/Dependabot) | ISO A.8.8 | 🟡 Medium | S | 2 |
| G14 | **Secrets management** + rotation | ISO A.8.24 | 🟡 Medium | S | 2 |
| G15 | **Image-parsing hardening** (bombs, dimension caps) | ISO A.8.26 | 🟡 Medium | S | 3 |
| G16 | **DB-backed users + refresh tokens + mTLS** | ISO A.5.16 | 🟡 Medium | M | 2 |
| G17 | **Independent pen test + privacy review** | ISO/GDPR | 🟠 High | ⧉/$$ | 4 |
| G18 | **Full ISMS artifacts** (full SoA, risk-treatment plan, internal audit programme) | ISO 27001 | 🟡 Medium | M | 3 |
| G19 | **Distributed rate limiting (Redis) + WAF** | ISO A.8.6 | ⚪ Low | M | 3 |
| G20 | **ML concurrency limits / queueing** (DoS) | ISO A.8.6 | ⚪ Low | S | 3 |
| G21 | **Strict CSP** + TLS config verification | ISO A.8.23 | ⚪ Low | S | 3 |

Effort: S ≈ ≤1 day · M ≈ days · L ≈ weeks · ⧉/$$ = external + budget.

## 6. Prioritized closure plan

**Now (blockers to any real data) — Phase 2 tail**
G1 in-region hosting · G2 KMS keys · G3 PostgreSQL hardening · G4 backups/DR ·
G11 session security · G13 SCA · G14 secrets mgmt.

**Next (before/at launch) — Phase 2–3**
G8 end-to-end FRR · G9 consent UI + self-service erasure · G10 SIEM/monitoring ·
G16 DB-backed users/refresh tokens · G5 cancelable templates · G15 image hardening ·
G18 finish ISMS artifacts.

**Later (independent assessment) — Phase 4**
G6 PAD lab (ISO 30107-3) · G7 IAL2 assessment · G17 pen test + privacy review ·
G12 injection/attestation · G19–G21 infra hardening.

## 7. Conclusion & sign-off

- **Readiness:** the **assessment-readiness artifacts are complete** — controls
  mapping, tamper-evident audit trail, ISMS policy set (DP/DPIA/IR), and this gap
  assessment with a prioritized plan. Governance for Phase 3 is substantially done.
- **Not yet:** the system is **not certified and not cleared for real data.** The
  🔴/🟠 register items (led by **in-region hosting, KMS, PostgreSQL/backups**) must
  close first, followed by independent assessment (Phase 4).
- **Overall posture:** strong control coverage for a prototype; the remaining work
  is **execution and independent validation**, not discovery.
- **Sign-off (to complete):** Security Lead ⬚ · DPO ⬚ · Controller ⬚ · Date ⬚
- **Next review:** on closure of the "Now" tranche, or in 6 months.
