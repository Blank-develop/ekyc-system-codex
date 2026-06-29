# Security

Kyron eKYC handles **biometric data and identity documents** — the most
sensitive and most heavily regulated category of personal data. This document
captures the current security posture, what is already protected, and the work
required before processing real identities in production.

> **Status: demo / prototype.** The public demo is for testing with **sample or
> redacted documents only**. Do **not** enroll real identity documents on the
> public demo or on a personal-computer tunnel. See "Production readiness" below.

## Threat model (what this system must resist)

- **Presentation attacks** — printed photos, screen/video replay, masks/cutouts
  used to impersonate someone during liveness or face match.
- **Injection attacks** — virtual cameras / deepfakes feeding synthetic media
  directly, bypassing the physical camera.
- **Replay attacks** — re-submitting a previously captured legitimate burst.
- **Direct-API abuse** — bypassing the frontend to submit crafted requests.
- **Data exposure** — leakage of biometric templates or document PII (name,
  document number, date of birth, nationality, expiry).
- **Abuse / DoS** — overwhelming expensive ML inference; brute-forcing face match.

## What is already protected

- **No raw biometric media is stored.** Document, selfie, and liveness images are
  analyzed **in memory** and never written to disk during verification.
- **Face embeddings stay in the in-memory session** during a verification and are
  not persisted unless the user completes enrollment.
- **Profile admin endpoints are locked (fail-closed).** `GET /api/profiles`,
  `DELETE /api/profiles/{user_id}`, and `DELETE /api/profiles` are **disabled**
  unless `LALIGENCE_ADMIN_API_TOKEN` is set, and then require a matching
  `X-Admin-Token` header (constant-time compare).
- **Backend-verified active liveness.** Active-liveness face actions are verified
  from server-side evidence bursts, not trusted from frontend landmarks.
- **Passive anti-spoof (PAD)** with burst-mode voting, face-size quality gating,
  and screen/photo/held-phone heuristics; printed-photo and phone-screen replay
  attack sets are rejected in testing.
- **MRZ hard-fail** — passports without a readable/valid TD3 MRZ are rejected.
- **Upload guards** — content-type allowlist, size cap, empty/corrupt-file checks.
- **Per-IP rate limiting** and an **explicit CORS allowlist**
  (`LALIGENCE_CORS_ORIGINS`, no wildcard).
- **HTTPS everywhere** in hosted deployments (required for camera access; Caddy
  sets HSTS and security headers on the DigitalOcean path).
- Embeddings are **not exposed through API response schemas**.

## Production readiness — required before real data

Prioritized. Tier 1 items are blockers.

### Tier 1 — blockers
- [~] **API authentication & authorization.** Optional API-key gate on all `/api`
  endpoints (`LALIGENCE_API_KEYS`, `X-API-Key` header) — off for the public demo,
  required in production / for partner integrations. Still needed: per-user
  OAuth2/JWT for the web frontend, RBAC, and mTLS for high-trust partners.
- [ ] **Encrypt biometric templates at rest** (KMS-managed keys / encrypted
  columns); prefer protected/cancelable templates (ISO/IEC 24745) over raw
  embeddings.
- [ ] **Consent, retention & deletion** — explicit recorded consent for biometric
  processing, retention limits with auto-purge, and a real erasure workflow.
- [ ] **Data residency** — host real Lao/SEA identity data in-region per local
  law; do **not** use a public third-party demo platform for real PII.
- [ ] **Session security** — unguessable, short-lived, client-bound session
  tokens with expiry to prevent hijack/replay.

### Tier 2 — fraud / integrity
- [x] Admin endpoints locked (fail-closed token guard).
- [x] Face-login PII redacted by default (masked document number, no full
  name/DOB/expiry for unauthenticated callers; full PII behind
  `LALIGENCE_FACE_LOGIN_EXPOSE_PII`). **Still needs real authentication.**
- [~] **Do not trust the client** — hand-gesture completion is now ordering-enforced
  (requires the server-verified active-liveness step first) and nonce-gated.
  Still needed: full server-side gesture classification (a backend hand model)
  instead of trusting client-side MediaPipe detection.
- [x] **Replay/freshness** — hand-gesture challenges use server-issued one-time,
  session-bound nonces, consumed on use (replay-proof). Extending the same
  nonce binding to submitted media frames remains future work.
- [ ] **Injection-attack defense** — mobile SDK integrity / device attestation.
- [ ] **Independent PAD evaluation** (ISO/IEC 30107-3) before any accuracy claim.

### Tier 3 — application & infrastructure hardening
- [ ] Harden image parsing (decompression bombs, dimension caps, parser CVEs).
- [~] **Rate limiting.** Face-login has a dedicated per-client + global throttle
  with proxy-aware client IP (`LALIGENCE_TRUST_PROXY_HEADERS`). Still needed:
  **distributed** rate limiting (Redis) for multi-instance, per-account limits,
  escalating lockout, and a WAF.
- [ ] **Concurrency limits / queueing** for expensive ML inference (DoS).
- [ ] **Secrets management** (no secrets in git/env-in-repo); key rotation.
- [ ] **Dependency scanning** (SCA / Dependabot) across the ML stack; resolve
  known advisories.
- [ ] Strict **Content-Security-Policy**; verify TLS configuration.
- [ ] **PostgreSQL** not publicly exposed, TLS in transit, encrypted at rest,
  least-privilege DB user, encrypted backups.
- [ ] **Audit logging** (tamper-evident): PII access + every verification
  decision and reason codes.
- [ ] **Monitoring/alerting** (SIEM), anomaly detection, patch management.
- [ ] **Independent penetration test + privacy review** before launch.
- [ ] **Incident-response & breach-notification** plan (biometric breaches are
  severe and often legally notifiable).

## Relevant standards

- **NIST SP 800-63 / IAL2** — identity proofing (the system is *aligned*, not
  certified).
- **ISO/IEC 30107-3** — presentation-attack detection testing.
- **ISO/IEC 24745** — biometric template protection.
- **ISO/IEC 27001** — information security management.
- **GDPR / local data-protection law** — biometric data is special-category.
- **FATF** — AML/KYC obligations.

> Do not claim NIST, ISO, bank-grade, or government certification unless an
> independent assessment has been completed.

## Security-relevant configuration

| Env var | Purpose |
| --- | --- |
| `LALIGENCE_ADMIN_API_TOKEN` | Enables the profile admin endpoints; required in the `X-Admin-Token` header. Unset = endpoints disabled. |
| `LALIGENCE_API_KEYS` | Comma-separated API keys. When set, all `/api` endpoints require a matching `X-API-Key` header. Unset = open (public demo). |
| `LALIGENCE_FACE_LOGIN_EXPOSE_PII` | `false` (default) returns a redacted face-login profile; set `true` only in trusted/authenticated deployments. |
| `LALIGENCE_TRUST_PROXY_HEADERS` | `true` behind a trusted proxy (HF/Cloudflare) so client IP comes from `CF-Connecting-IP` / `X-Forwarded-For` for per-client throttling. |
| `LALIGENCE_FACE_LOGIN_MAX_PER_MINUTE` | Per-client face-login attempt limit (default 12). |
| `LALIGENCE_FACE_LOGIN_GLOBAL_MAX_PER_MINUTE` | Global face-login attempt cap / harvesting backstop (default 60). |
| `LALIGENCE_CORS_ORIGINS` | Explicit CORS allowlist (no wildcard). |
| `LALIGENCE_MAX_UPLOAD_SIZE_BYTES` | Upload size cap. |
| `LALIGENCE_MAX_REQUESTS_PER_MINUTE` | Global per-IP rate limit (all endpoints). |
| `DATABASE_URL` | Profile store; use PostgreSQL with TLS + encryption at rest in production. |

## Reporting a vulnerability

Report suspected vulnerabilities privately to the project maintainer rather than
opening a public issue. Do not include real identity documents or biometric data
in reports.
