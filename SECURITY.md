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
- [~] **API authentication & authorization.** Two layers: (1) an optional API-key
  gate on all `/api` endpoints (`LALIGENCE_API_KEYS`, `X-API-Key`) for partner
  integrations; (2) **per-user OAuth2 password → JWT** (`LALIGENCE_JWT_SECRET`,
  `POST /api/auth/token`, `GET /api/auth/me`) with **RBAC** — admin endpoints
  accept a Bearer token whose role is `admin` (or the legacy `X-Admin-Token`).
  Passwords are PBKDF2-hashed; tokens are HS256, signed, expiring. A **staff login
  console** (`#admin` in the web app) uses this to sign operators in and authorize
  the profiles / purge / delete views. Both layers are off in the public demo.
  Still needed: a **DB-backed user store** with self-service signup, **refresh
  tokens** / rotation, and **mTLS** for high-trust partners.
- [~] **Encrypt biometric templates + PII at rest.** When `LALIGENCE_ENCRYPTION_KEY`
  is set, face templates **and** PII (name, DOB, nationality, passport number,
  expiry) are encrypted with authenticated symmetric encryption (Fernet) — the
  PII lives in an encrypted blob and `passport_number` keeps a **blind index**
  (keyed hash) so the one-document-one-profile rule still works; plaintext columns
  are nulled. No-op for the demo; legacy plaintext rows stay readable.
  **Cancelable/renewable templates** (ISO/IEC 24745) are also available: when
  `LALIGENCE_TEMPLATE_PROTECTION_KEY` is set, templates are transformed by a
  key-derived **orthonormal projection** before encryption — matching scores are
  preserved **exactly** (rotation preserves the dot product), the raw biometric is
  never stored even after decrypt, and templates are **revocable/renewable** by
  re-keying (and unlinkable across keys). Still needed: a fully one-way
  (irreversible) transform.
- [~] **KMS-ready secret sourcing & key rotation.** Every secret
  (`LALIGENCE_ENCRYPTION_KEY`, `LALIGENCE_JWT_SECRET`, `LALIGENCE_TEMPLATE_PROTECTION_KEY`,
  admin token, API keys) may be a bare literal (dev/demo) **or a provider spec**
  resolved at runtime — `file:/run/secrets/x` (K8s/Docker/KMS-CSI mount),
  `command:<vault/aws-kms/gcloud cli>`, or `env:OTHER_VAR` — so production keys
  come from a **secret manager, not a bare env var** (`services/key_provider.py`).
  **Rotation** is supported: retired encryption keys still decrypt existing data
  (MultiFernet via `LALIGENCE_ENCRYPTION_KEYS_RETIRED`) and retired JWT secrets
  still verify live tokens (`LALIGENCE_JWT_SECRETS_RETIRED`). Still needed: a fully
  managed KMS/HSM with automated rotation + envelope encryption.
- [~] **Consent, retention & deletion.** A **consumer consent gate** (opt-in
  checkbox with a versioned notice from `GET /api/consent`) blocks the biometric
  flow until accepted, and each enrolled profile records the **consent terms
  version + timestamp** (`LALIGENCE_CONSENT_VERSION`). **Retention** auto-purge is
  available (`LALIGENCE_PROFILE_RETENTION_DAYS` + admin `POST /api/profiles/purge-expired`);
  0 = retain indefinitely (demo default). **Self-service data rights**: a data
  subject authenticates with a **live selfie** (`POST /api/self-service/export` /
  `/delete`, liveness + face match, rate-limited, audited) to **export** or
  **erase** their own record; admins can also erase via `DELETE /api/profiles/{user_id}`.
  Still needed: a scheduled purge job and identity-proofed DSAR for non-enrolled requests.
- [~] **Data residency** — host real Lao/SEA identity data in-region per local
  law; do **not** use a public third-party demo platform for real PII. **Plan
  written** (`docs/in-region-hosting-plan.md`): options, target architecture,
  migration steps, and a go-live checklist. Still needed: **execute** the move
  (provision in-region, managed PostgreSQL, KMS keys) — a hosting/ops task.
- [~] **Session security.** Verification sessions are **unguessable** (random id
  + a 256-bit per-session token), **short-lived** (idle + absolute TTL, expired
  sessions return 410 and are evicted), and **client-bound** — the token
  (`X-Session-Token`, issued once at creation) is required on every session-scoped
  request, so a leaked session id alone can't be replayed/hijacked
  (`LALIGENCE_SESSION_*`, fail-closed via `LALIGENCE_SESSION_BINDING_ENFORCED`).
  Expired sessions are also swept on creation to bound memory. Still needed:
  distributed session storage for multi-instance.

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
- [~] **Secrets management** — secrets can be sourced from a manager via
  `file:`/`command:`/`env:` specs (`services/key_provider.py`), and encryption/JWT
  keys support **rotation** (retired keys still decrypt/verify). Still needed: a
  managed KMS/HSM with automated rotation.
- [x] **Dependency scanning** (SCA). A CI gate
  (`.github/workflows/security-scan.yml`) runs `pip-audit` (backend) and
  `npm audit` (frontend) on every push/PR and weekly, failing on known
  vulnerabilities; **Dependabot** (`.github/dependabot.yml`) opens the fix PRs.
  The initial scan found and cleared **20 backend + 1 frontend** advisories —
  notably in `python-multipart` (upload parsing) and `pillow` (image decode), our
  direct attack surface. Both stacks are currently clean.
- [ ] Strict **Content-Security-Policy**; verify TLS configuration.
- [ ] **PostgreSQL** not publicly exposed, TLS in transit, encrypted at rest,
  least-privilege DB user, encrypted backups.
- [~] **Audit logging** (tamper-evident): hash-chained append-only trail
  (`services/audit.py`) of auth events, PII access, admin actions, and identity
  enrollment/decisions — each entry's hash covers the previous, so edits/deletes
  are detectable via `GET /api/audit/verify`; keyed (HMAC) when
  `LALIGENCE_ENCRYPTION_KEY` is set. No raw PII/biometrics logged. Viewable + a
  one-click integrity check in the staff console. Still needed: ship logs to an
  external WORM/SIEM sink.
- [x] **Verification-attempts log** (`services/attempt_store.py`): every eKYC
  session's decision and per-step outcomes (document/liveness/gesture/face-match
  results, reason codes, client IP) are persisted — one row per session, upserted
  after each step — so operators can see every attempt and its result, not just
  live in-memory sessions. Same minimization principle as the audit log: no raw
  images, no biometric embeddings, no document PII. Retention via
  `LALIGENCE_ATTEMPT_RETENTION_DAYS` + `POST /api/attempts/purge-expired`.
  Viewable (with filters) in the staff console's Attempts tab, alongside an
  Overview dashboard (attempt counts by decision, enrolled Face ID count, audit
  chain status).
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

For a clause-by-clause map of **which control satisfies which requirement**, with
evidence (files/tests/config) and honest status, see
**`docs/controls-standards-mapping.md`** (the Phase 3 traceability matrix). The
supporting **ISMS policy set** — Data Protection & Retention Policy, DPIA,
Incident Response Plan, and an **Internal Gap Assessment + Statement of
Applicability** (with a prioritized G1–G21 closure plan) — is in **`docs/policies/`**.

## Security-relevant configuration

| Env var | Purpose |
| --- | --- |
| `LALIGENCE_ADMIN_API_TOKEN` | Enables the profile admin endpoints; required in the `X-Admin-Token` header. Unset = endpoints disabled. |
| `LALIGENCE_API_KEYS` | Comma-separated API keys for partner integrations. When set, all `/api` endpoints require a matching `X-API-Key` header. Unset = open (public demo). See `docs/partner-api-integration-guide.md`. |
| `LALIGENCE_JWT_SECRET` | Enables per-user OAuth2/JWT auth. When set, `POST /api/auth/token` issues signed access tokens and admin endpoints accept an `admin`-role Bearer token. Generate: `openssl rand -hex 32`. Unset = JWT auth off. |
| `LALIGENCE_AUTH_USERS` | Comma-separated `username:pbkdf2_hash:role` entries (generate a hash with `scripts/hash_password.py`). |
| `LALIGENCE_JWT_EXPIRE_MINUTES` | Access-token lifetime in minutes (default 60). |
| `LALIGENCE_ENCRYPTION_KEY` | Fernet key — when set, biometric templates are encrypted at rest. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Unset = plaintext (dev/demo). |
| `LALIGENCE_TEMPLATE_PROTECTION_KEY` | Enables cancelable/renewable templates (ISO/IEC 24745): a key-derived orthonormal transform of the template (accuracy-preserving). Re-key to revoke/renew (requires re-enrollment). Unset = raw template. |
| *(secret sourcing)* | Any secret above may be a bare literal **or** a provider spec: `file:/path`, `command:<cli>`, `env:VAR`, or `literal:VALUE` — resolved by `services/key_provider.py` so production keys come from a KMS/secret-manager, not the env. |
| `LALIGENCE_ENCRYPTION_KEYS_RETIRED` | Comma-separated retired encryption-key specs that still **decrypt** existing data during rotation (new data uses the primary key). |
| `LALIGENCE_JWT_SECRETS_RETIRED` | Comma-separated retired JWT-secret specs that still **verify** live tokens during rotation (new tokens use the primary secret). |
| `LALIGENCE_CONSENT_VERSION` | Consent terms version stamped on each enrolled profile (with a timestamp) for an auditable consent record. Default `2026-06-v1`. |
| `LALIGENCE_PROFILE_RETENTION_DAYS` | Data-retention window in days. `>0` lets `POST /api/profiles/purge-expired` delete profiles idle longer than this. `0` (default) = retain indefinitely. |
| `LALIGENCE_AUDIT_LOG_ENABLED` | Tamper-evident hash-chained audit log of auth/PII-access/admin/enrollment events. `true` (default). Keyed with `LALIGENCE_ENCRYPTION_KEY` when set. |
| `LALIGENCE_ATTEMPT_RETENTION_DAYS` | Retention window for the verification-attempts admin log. `>0` lets `POST /api/attempts/purge-expired` delete attempts idle longer than this. `0` (default) = retain indefinitely. |
| `LALIGENCE_FACE_LOGIN_EXPOSE_PII` | `false` (default) returns a redacted face-login profile; set `true` only in trusted/authenticated deployments. |
| `LALIGENCE_TRUST_PROXY_HEADERS` | `true` behind a trusted proxy (HF/Cloudflare) so client IP comes from `CF-Connecting-IP` / `X-Forwarded-For` for per-client throttling. |
| `LALIGENCE_FACE_LOGIN_MAX_PER_MINUTE` | Per-client face-login attempt limit (default 12). |
| `LALIGENCE_FACE_LOGIN_GLOBAL_MAX_PER_MINUTE` | Global face-login attempt cap / harvesting backstop (default 60). |
| `LALIGENCE_CORS_ORIGINS` | Explicit CORS allowlist (no wildcard). |
| `LALIGENCE_SESSION_IDLE_TTL_MINUTES` | Verification-session idle timeout (default 30). |
| `LALIGENCE_SESSION_ABSOLUTE_TTL_MINUTES` | Verification-session absolute lifetime cap (default 120). |
| `LALIGENCE_SESSION_BINDING_ENFORCED` | Require the per-session `X-Session-Token` on session-scoped requests. `true` (default). |
| `LALIGENCE_REQUIRE_CONTACT_CONFIRMATION` | IAL2 steps 5–6: require an enrollment-code contact confirmation to pass, and notify on proofing. `false` (default; demo skips it). |
| `LALIGENCE_NOTIFIER` | Delivery channel for codes/notifications: `console` (log only) or `command:<shell>` to shell out to a mailer/SMS CLI. |
| `LALIGENCE_NOTIFIER_ECHO_CODE` | Demo-only: echo the enrollment code in the request response. Never enable in production. |
| `LALIGENCE_MAX_UPLOAD_SIZE_BYTES` | Upload size cap. |
| `LALIGENCE_MAX_REQUESTS_PER_MINUTE` | Global per-IP rate limit (all endpoints). |
| `DATABASE_URL` | Profile store; use PostgreSQL with TLS + encryption at rest in production. |

## Reporting a vulnerability

Report suspected vulnerabilities privately to the project maintainer rather than
opening a public issue. Do not include real identity documents or biometric data
in reports.
