# Incident Response Plan

| | |
| --- | --- |
| **Owner** | Data Protection Officer / Security Lead (to be appointed) |
| **Scope** | Security and privacy incidents affecting Kyron eKYC and its data |
| **Version / date** | Draft v0.1 · 2026-07-01 |
| **Related** | [Data Protection & Retention Policy](data-protection-and-retention-policy.md) · [DPIA](dpia-biometric-ekyc.md) · `SECURITY.md` |

> **Status:** draft for a demo/prototype. Contacts/timelines are placeholders for
> the operating entity to finalize. Biometric breaches are severe and often legally
> notifiable — treat this plan as mandatory before processing real data.

## 1. Purpose

Provide a repeatable process to **detect, contain, eradicate, recover from, and
report** incidents — with special attention to **biometric and identity-document
data**, whose compromise can cause irreversible harm.

## 2. What counts as an incident

- Unauthorized access to profiles, templates, or PII (or credible attempt).
- Compromise of an admin credential, JWT signing key, or **encryption key**.
- **Audit-chain integrity failure** (`GET /api/audit/verify` returns not-ok).
- Successful presentation/injection attack bypassing liveness at scale.
- Data loss, ransomware, or exposure of the database/backups.
- Processing outside the lawful basis (e.g. real PII on the public demo).

## 3. Severity classification

| Sev | Definition | Example |
| --- | --- | --- |
| **SEV-1 Critical** | Confirmed exposure of biometric/PII, or key compromise | Template/PII dump; encryption key leaked |
| **SEV-2 High** | Likely exposure or major control failure | Admin account takeover; audit chain broken |
| **SEV-3 Medium** | Contained/limited, no confirmed data exposure | Blocked brute-force; single redacted-data leak |
| **SEV-4 Low** | Policy/process issue, no data risk | Misconfiguration caught pre-exposure |

## 4. Roles

| Role | Responsibility |
| --- | --- |
| **Incident Lead** | Coordinates response, declares severity, owns the timeline |
| **DPO** | Assesses notification obligations; liaises with regulators/data subjects |
| **Security/Eng** | Technical containment, forensics, eradication, recovery |
| **Comms/Legal** | External communications, legal exposure, law-enforcement liaison |

## 5. Response phases

1. **Detect & report.** Any staff member reports to the Incident Lead. Sources:
   monitoring/alerts, `GET /api/audit/verify` failures, rate-limit spikes, user
   reports. Record time of detection.
2. **Triage & classify.** Assign SEV; open an incident record; start the timeline.
3. **Contain.** Limit blast radius, e.g.: rotate the **JWT secret** and **admin
   token** (invalidates sessions); revoke/rotate **API keys**; rotate the
   **encryption key** (re-encrypt); disable affected accounts; block source IPs /
   tighten rate limits; if needed, take the service offline.
4. **Eradicate.** Remove the root cause (patch, fix misconfig, remove attacker
   access, close the exploited path).
5. **Recover.** Restore from **encrypted, in-region backups**; verify integrity
   (incl. **audit-chain re-verification**); monitor for recurrence before all-clear.
6. **Notify** (§6).
7. **Post-incident review.** Within ~5 business days: root cause, timeline, what
   worked, corrective actions, and updates to controls/this plan.

## 6. Notification obligations

- **Regulator:** notify the supervisory authority **without undue delay and within
  72 hours** of becoming aware of a personal-data breach where required (GDPR Art.
  33 / analogous local law), unless unlikely to result in risk.
- **Data subjects:** where the breach is **high risk** to individuals — which a
  **biometric** breach typically is — notify affected individuals **without undue
  delay** (Art. 34), in clear language, with guidance.
- **Records:** every breach (including those not notified) is documented with facts,
  effects, and remedial action (Art. 33(5)).
- Maintain a **contact list** (DPO, regulator, hosting provider, legal, law
  enforcement) — *to be completed by the operating entity.*

## 7. Forensics & evidence

- The **tamper-evident audit log** (`services/audit.py`) is a primary evidence
  source: auth events, PII access, admin actions, enrollment — hash-chained so
  tampering is detectable (`GET /api/audit/verify`). Preserve it (export/copy) early
  and do not mutate it during response.
- Preserve host/app logs, DB snapshots, and relevant configuration.
- Note: raw biometric **images are not stored**, limiting exposure by design.

## 8. Key-compromise runbook (quick reference)

| Compromised | Immediate action |
| --- | --- |
| **JWT secret** (`LALIGENCE_JWT_SECRET`) | Rotate → all tokens invalid; force re-login |
| **Admin token** (`LALIGENCE_ADMIN_API_TOKEN`) | Rotate immediately |
| **API keys** (`LALIGENCE_API_KEYS`) | Revoke/rotate; notify partners |
| **Encryption key** (`LALIGENCE_ENCRYPTION_KEY`) | Rotate + re-encrypt at rest; assess exposure window; **SEV-1** — likely notifiable |
| **Database/backups** | Isolate, snapshot for forensics, restore clean, rotate all secrets |

## 9. Testing & maintenance

- **Tabletop exercise** at least annually (e.g. simulate a template-store breach).
- Verify backups restore and the audit chain re-verifies as part of the drill.
- Review and update this plan after every SEV-1/SEV-2 incident and annually.
