# ISMS Policies & Evidence

Phase 3 governance documents for Kyron eKYC. These are the **written policies** an
assessor asks for alongside the technical controls — drafted against the system as
actually built (each cites real controls: `services/crypto.py`, `services/audit.py`,
retention/consent config, JWT auth, etc.), so they double as **evidence**.

> **Status: drafts for a demo/prototype.** They describe the intended production
> posture and the controls already in place. They are **not** a substitute for
> legal review by a qualified data-protection advisor before processing real
> identities. Roles/contacts are placeholders to be filled by the operating entity.

| Document | Purpose | Maps to |
| --- | --- | --- |
| [Data Protection & Retention Policy](data-protection-and-retention-policy.md) | How personal/biometric data is handled, retained, and deleted | GDPR Art. 5/13/17/32, ISO 27001 A.5, FATF record-keeping |
| [DPIA — Biometric eKYC](dpia-biometric-ekyc.md) | Risk assessment for high-risk (biometric) processing | GDPR Art. 35 |
| [Incident Response Plan](incident-response-plan.md) | Detect, contain, and notify on security/biometric breaches | GDPR Art. 33/34, ISO 27001 A.5.24–28 |
| [Internal Gap Assessment & SoA](internal-gap-assessment.md) | Self-audit + Statement of Applicability + prioritized gap-closure plan | ISO 27001 Annex A, NIST 800-63A |

**Cross-references:** [`SECURITY.md`](../../SECURITY.md) ·
[`docs/controls-standards-mapping.md`](../controls-standards-mapping.md) ·
[`docs/in-region-hosting-plan.md`](../in-region-hosting-plan.md).

Document owners: *Project maintainer / Data Protection Officer (to be appointed).*
Review cadence: at least annually, and on any material change to processing.
Last drafted: 2026-07-01.
