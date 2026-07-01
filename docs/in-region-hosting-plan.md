# In-Region Hosting Plan

**Phase 2 blocker · data residency.** Moving Kyron eKYC off the public demo
platform (Hugging Face Spaces, ephemeral, shared, out-of-region) onto hosting
that keeps **real Lao / SEA identity data in-region**, under our control, with the
production security controls already built (encryption at rest, per-user JWT auth,
consent/retention/deletion).

> This is a **hosting & operations** decision, not a code change. The application
> is already deployable (see `deploy/digitalocean/`); this plan chooses *where* and
> *how* to run it for real data, and the steps to get there.

---

## 1. Why in-region (the requirement)

Biometric data and identity-document PII are **special-category personal data**.
Most jurisdictions — including Lao PDR's data-protection direction and neighbouring
SEA regimes (Thailand PDPA, Vietnam PDPD, Indonesia PDP Law) — require that such
data about residents be **stored and processed inside the country/region**, or only
transferred abroad under strict conditions.

The current public demo **fails** this on three counts, which is why it is
**sample-documents-only**:

| Property | Public demo (HF Spaces) | Required for real data |
| --- | --- | --- |
| Location | Shared US/EU infra | In-country / in-region |
| Tenancy | Shared, ephemeral `/tmp` | Dedicated, persistent, isolated |
| Control | Third-party platform | Our cloud account / contract |
| Data at rest | Wiped on rebuild | Encrypted, backed up, retained per policy |

---

## 2. Hosting options (ranked)

### Option A — In-country / in-region cloud VPS *(recommended to start)*
A dedicated VM from a provider with a **region inside or nearest to Laos** — e.g.
AWS `ap-southeast-1` (Singapore) / `ap-southeast-3` (Jakarta), Google Cloud
`asia-southeast1`, Alibaba Cloud (Bangkok/Singapore), or a **Lao/Thai national
cloud / licensed local data-centre** where required by law.

- **Pros:** fast to stand up, our account, full control, meets residency when the
  region is legally acceptable, scales later.
- **Cons:** "nearest region" (Singapore) may still be **out-of-country** — confirm
  with counsel whether in-region is sufficient or in-*country* is mandated.
- **Fit:** best balance of speed, control, and cost for launch.

### Option B — Local licensed data centre / national cloud
Host with a Lao-licensed data-centre or government-approved cloud when the law
mandates in-**country** storage for resident biometric data.

- **Pros:** strongest residency compliance.
- **Cons:** fewer managed services, more ops work, procurement lead time.
- **Fit:** if regulators require in-country; can pair with Option A for non-resident traffic.

### Option C — On-premise (customer/partner data centre)
For a bank/government partner that requires data never leave their premises.

- **Pros:** maximum control; fits high-trust enterprise deals.
- **Cons:** we own hardware, patching, physical security, DR.
- **Fit:** enterprise / regulated-partner deployments.

**Recommendation:** launch on **Option A** in the closest legally-acceptable region,
with a documented path to **Option B/C** per regulator or partner requirements.

---

## 3. Target architecture (single-region, hardened)

```
                         ┌─────────────────────────── In-region cloud (private VPC) ──┐
   User (browser)        │                                                             │
        │ HTTPS          │   ┌────────────┐     ┌──────────────┐    ┌──────────────┐   │
        └───────────────►│──►│  Caddy /   │────►│  FastAPI app │───►│ PostgreSQL   │   │
                         │   │  reverse   │     │  (Kyron API) │    │ (encrypted,  │   │
        camera media     │   │  proxy TLS │     │  + frontend  │    │  private)    │   │
        analyzed in RAM  │   │  HSTS/CSP  │     └──────┬───────┘    └──────────────┘   │
        never to disk    │   └────────────┘            │                               │
                         │                             ▼                               │
                         │                      ┌──────────────┐   ┌───────────────┐   │
                         │                      │  KMS / Vault │   │ Audit log +   │   │
                         │                      │ (enc. keys)  │   │ backups (enc) │   │
                         │                      └──────────────┘   └───────────────┘   │
                         └─────────────────────────────────────────────────────────────┘
```

The `deploy/digitalocean/` bundle already provides most of this (single branded
domain, Caddy TLS + security headers, PostgreSQL in a private network, all the
`LALIGENCE_*` secrets). "In-region" = **run that same bundle in an in-region
account/region**, plus the hardening in §4.

---

## 4. What changes vs. the demo

| Area | Demo today | In-region production |
| --- | --- | --- |
| **Region** | Shared US/EU | In-region VPC, single legal jurisdiction |
| **Database** | Ephemeral SQLite in `/tmp` | Managed **PostgreSQL**, private subnet, TLS in transit, encrypted volume, PITR backups (encrypted) |
| **Encryption keys** | `LALIGENCE_ENCRYPTION_KEY` env var | **KMS / Vault-managed** keys with rotation (not a bare env var) |
| **Auth** | Open (demo) | `LALIGENCE_API_KEYS` + per-user **JWT** on; admin locked |
| **Consent/retention** | Defaults (retain ∞) | `LALIGENCE_PROFILE_RETENTION_DAYS` set; scheduled purge job |
| **CORS** | Allowlist demo origins | Allowlist the branded production domain only |
| **Access** | Public URL | Restricted; admin console behind SSO/VPN or IP-allowlist |
| **Audit** | None | Tamper-evident audit log of PII access + decisions |
| **Backups/DR** | None | Encrypted backups **in-region**, tested restore, retention policy |
| **Monitoring** | HF logs | Centralized logs/metrics/alerting **in-region** |

Data-flow guarantees that already hold and must be preserved: **no raw biometric
media is written to disk** (analyzed in memory); **embeddings are never exposed
through API schemas**; **PII + templates are encrypted at rest**.

---

## 5. Migration steps (demo → in-region)

1. **Legal check** — confirm with counsel whether in-**region** (e.g. Singapore) is
   acceptable or in-**country** is mandated for Lao resident biometric data; pick
   Option A vs B/C accordingly. Record the lawful basis + cross-border stance.
2. **Provision** — create an in-region account/project, a private VPC, and a VM.
   Register the branded domain + in-region DNS (the DigitalOcean bundle documents a
   Route 53 example; use an in-region DNS/registrar as needed).
3. **Managed PostgreSQL** — provision in the private subnet; enable TLS, encrypted
   storage, encrypted automated backups; set `DATABASE_URL` to it.
4. **Keys** — generate the Fernet `LALIGENCE_ENCRYPTION_KEY` and JWT
   `LALIGENCE_JWT_SECRET` **inside** KMS/Vault; inject at runtime; enable rotation.
5. **Config** — set the production `.env` from `deploy/digitalocean/.env.example`:
   CORS = branded domain only, API keys, JWT + seeded admin user
   (`scripts/hash_password.py`), retention days, admin token.
6. **Deploy** — run the Caddy + app + PostgreSQL compose bundle; verify HTTPS, HSTS,
   CSP, and that `/api` requires auth.
7. **Scheduled purge** — add a cron/systemd timer calling
   `POST /api/profiles/purge-expired` (admin-auth) to enforce retention.
8. **Backups + DR** — verify encrypted backups land **in-region**; run a test
   restore; document RPO/RTO.
9. **Monitoring + audit** — ship logs/metrics to an in-region stack; enable audit
   logging of PII access and every verification decision.
10. **Lock the demo** — keep the public HF demo **sample-documents-only**; never
    point real users at it.

---

## 6. Go-live checklist (data-residency & privacy)

- [ ] Legal sign-off on region/country choice + cross-border transfer stance.
- [ ] All PII + biometric templates stored **only** in-region.
- [ ] PostgreSQL private (no public IP), TLS in transit, encrypted at rest.
- [ ] Encryption + JWT keys in **KMS/Vault**, rotation enabled (not bare env vars).
- [ ] API-key + per-user JWT auth **on**; admin endpoints locked; CORS = prod domain only.
- [ ] Retention window set + scheduled purge job running.
- [ ] Consent version current; deletion (erasure) workflow tested.
- [ ] Encrypted backups in-region; restore tested; RPO/RTO documented.
- [ ] Audit logging (PII access + decisions) enabled and tamper-evident.
- [ ] Monitoring/alerting in-region; incident-response + breach-notification plan.
- [ ] Public demo remains sample-only; no real data path to it.

---

## 7. Cost & effort (rough, launch tier)

| Item | Rough monthly | Notes |
| --- | --- | --- |
| App VM (2–4 vCPU) | $20–60 | Scales with traffic; ML inference is CPU-bound |
| Managed PostgreSQL | $15–50 | HA tier costs more |
| KMS / secrets | ~$1–5 | Per-key + API calls |
| Backups + egress | $5–20 | In-region storage |
| **Total (launch)** | **~$45–135/mo** | Before HA, WAF, DR replicas |

Effort: ~**1–2 engineer-days** to stand up Option A from the existing
`deploy/digitalocean/` bundle; legal review and audit/monitoring wiring run in
parallel and are the longer poles.

---

*Cross-references:* `SECURITY.md` (production-readiness tiers),
`deploy/digitalocean/` (the deployable bundle + `.env.example`),
`docs/roadmap.html` (Phase 2 · Production hardening).
