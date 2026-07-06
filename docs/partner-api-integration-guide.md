# Partner API Integration Guide

How an external application connects to **Kyron eKYC** to verify a person's identity
(document + live face), enroll a reusable Face ID, and log returning users in by
face — over a REST API, with ready-made TypeScript and Flutter SDKs.

> **Draft.** Endpoint shapes reflect the current implementation. Some production
> partner features (per-partner keys/quotas, webhooks, API versioning) are noted as
> **planned** — see §11.

---

## 1. How it works

Kyron is a **thin-client** model: **your app owns the camera and UX**; **Kyron owns
the identity work** — OCR, document fraud checks, face matching, liveness, the risk
decision, and the encrypted Face ID store.

```
Your app (captures images)  ──HTTPS + API key──▶  Kyron eKYC API  ──▶  decision + reason codes
```

Nothing about the biometric pipeline runs in your systems; you send captured images
and receive typed results. Raw images are analyzed in memory and are not stored.

## 2. Base URL, environments, and docs

- **Base URL:** `https://<your-kyron-host>` — all endpoints are under `/api`.
- **Interactive API docs:** `GET /docs` (Swagger UI) · **OpenAPI spec:** `GET /openapi.json`
  (generate a typed client in any language from this).
- Use a **sandbox / test host** with sample documents for development; never send real
  identity documents to a shared demo.

## 3. Authentication

Two headers are involved:

| Header | Purpose | When |
| --- | --- | --- |
| `X-API-Key` | Identifies **your company** to Kyron | **Every** `/api` request |
| `X-Session-Token` | Binds a verification session to the caller | Every request **after** you create a session |

- **API key** — Kyron issues your company a key; send it as `X-API-Key` on every call.
  When keys are configured server-side (`LALIGENCE_API_KEYS`) an unauthenticated call
  returns **401**.
- **Session token** — `POST /api/verifications` returns a one-time `session_token`.
  Store it and send it as `X-Session-Token` on every subsequent call for that session.
  A missing/wrong token returns **403**; an expired session returns **410**.
- **CORS (browser apps)** — if you call Kyron directly from a web frontend, your
  origin must be on Kyron's allowlist (`LALIGENCE_CORS_ORIGINS`). Server-to-server
  calls are unaffected.

```bash
# Every request carries your API key:
curl -H "X-API-Key: $KYRON_API_KEY" https://<host>/api/consent
```

## 4. The verification flow

A verification is a short-lived **session** that progresses through steps. Each step
returns the full `VerificationResult` (decision + reason codes + per-step detail).

| # | Call | Body | Purpose |
| --- | --- | --- | --- |
| 1 | `POST /api/verifications` | JSON `{ "user_id": "..." }` | Start a session → returns `session_id` + `session_token` |
| 2 | `POST /api/verifications/{id}/document` | multipart: `file`, `document_type` | Upload passport/ID → OCR, fraud, MRZ check |
| 3 | `POST /api/verifications/{id}/active-liveness` | multipart: `challenge_id`, `frames` | Liveness action frames |
| 4 | `POST /api/verifications/{id}/challenge` | JSON `{ challenge_id, passed, nonce }` | Gesture result |
| 5 | `POST /api/verifications/{id}/selfie` | multipart: `frames` (or `file`) | 1:1 match to the document portrait + PAD |
| 6 | `GET /api/verifications/{id}` | — | Read the current decision |
| 7 | `POST /api/verifications/{id}/enroll-face` | — | On pass, enroll a reusable Face ID |

**Ordering rules enforced by the server:** the document must pass before active
liveness; the gesture step requires the server-verified active-liveness step first
(and is protected by one-time nonces). The `active_challenges` and `hand_challenges`
arrays in the session tell your app which prompts to show and carry the `challenge_id`
(and gesture `nonce`) you echo back.

### Example — start a session

```bash
curl -X POST https://<host>/api/verifications \
  -H "X-API-Key: $KYRON_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"partner-user-12345"}'
```
```json
{
  "session_id": "3f2a...", "user_id": "partner-user-12345",
  "decision": "pending", "reason_codes": [],
  "active_challenges": [{ "id": "turn_left", "prompt": "Turn left", ... }],
  "hand_challenges":  [{ "id": "two", "prompt": "Show 2", "nonce": "…", ... }],
  "session_token": "KEEP-THIS-send-as-X-Session-Token"
}
```

### Example — upload the document

```bash
curl -X POST https://<host>/api/verifications/$SID/document \
  -H "X-API-Key: $KYRON_API_KEY" \
  -H "X-Session-Token: $STOKEN" \
  -F "document_type=passport" \
  -F "file=@passport.jpg"
```
`document_type` is `passport` or `lao_id_card`.

### Example — read the decision

```bash
curl https://<host>/api/verifications/$SID \
  -H "X-API-Key: $KYRON_API_KEY" -H "X-Session-Token: $STOKEN"
```
Poll this (or read the response of the last step) for `decision`.

## 5. Returning users — Face Login

Once a Face ID is enrolled, a returning user is authenticated from a fresh live
selfie (liveness + 1:1 match, rate-limited):

```bash
curl -X POST https://<host>/api/face-login \
  -H "X-API-Key: $KYRON_API_KEY" \
  -F "file=@selfie.jpg"
```
Returns `{ decision, matched, match_score, profile, reason_codes, ... }`. For
unauthenticated callers the returned profile is **redacted** by default.

## 6. Optional steps

- **Consent (IAL2 / GDPR):** `GET /api/consent` returns the current consent terms
  version + notice to display; enrollment records the accepted version.
- **Contact confirmation (IAL2 steps 5–6):** when enabled server-side,
  `POST /api/verifications/{id}/contact/request` sends an enrollment code to an
  email/phone and `.../contact/confirm` verifies it.
- **Data-subject rights:** `POST /api/self-service/export` and `/self-service/delete`
  let an end user export or erase their own record, authenticated by a live selfie.

## 7. Decisions & reason codes

`decision` is one of:

| Value | Meaning |
| --- | --- |
| `passed` | All checks passed; you may enroll a Face ID |
| `pending` | More steps are required (see reason codes ending in `_REQUIRED`) |
| `rejected` | A hard failure (fraud, spoof, low match, invalid MRZ, …) |

`reason_codes` is a machine-readable list explaining the state — e.g.
`DOCUMENT_REQUIRED`, `ACTIVE_LIVENESS_REQUIRED`, `HAND_GESTURE_REQUIRED`,
`PASSIVE_LIVENESS_REQUIRED`, `CONTACT_CONFIRMATION_REQUIRED` (incomplete steps), or
hard failures such as `DOCUMENT_FRAUD_RISK_HIGH`, `FACE_MATCH_LOW`, and MRZ/anti-spoof
signal codes. Drive your UI from these codes, not from free text.

## 8. Error handling

| HTTP | Meaning | Action |
| --- | --- | --- |
| `401` | Missing/invalid `X-API-Key` | Check your key |
| `403` | Missing/invalid `X-Session-Token`, or admin-only route | Send the session token |
| `409` | Step out of order (e.g. gesture before liveness) | Follow the flow ordering |
| `410` | Session expired | Start a new session |
| `413` / `415` | Upload too large / unsupported type | JPG/PNG/WebP within the size cap |
| `429` | Rate limited | Back off and retry |

## 9. Rate limits

Requests are rate-limited per client (with a dedicated throttle on `face-login`).
Handle `429` with exponential backoff. Per-partner quotas are **planned** (§11).

## 10. SDKs

Two thin clients wrap the flow so you don't hand-roll HTTP or multipart:

- **TypeScript** — `sdk/typescript` (`EkycClient`), for web/Node apps.
- **Flutter / Dart** — `sdk/flutter` (`laligence_ekyc`), for mobile apps.

```ts
import { EkycClient } from "@laligence/ekyc-sdk";

const client = new EkycClient({ baseUrl: "https://<host>" /*, apiKey: KEY */ });
const session = await client.createSession("partner-user-12345");
await client.uploadDocument(session.session_id, passportFile, "passport");
// …active liveness, gesture, selfie…
const result = await client.getVerification(session.session_id);
if (result.decision === "passed") await client.enrollFace(session.session_id);
```

> The SDK owns HTTP + typed models; **your app owns the camera**. Confirm your SDK
> version forwards `X-API-Key` and `X-Session-Token` (adding a first-class `apiKey`
> option is a small enhancement if missing).

## 11. Going to production — current vs. planned

**Available today:** REST API + OpenAPI docs, API-key auth (`X-API-Key`), session
binding, TypeScript & Flutter SDKs, per-client rate limiting, explicit CORS, TLS/HSTS
in hosted deployments, encrypted Face ID storage, and a tamper-evident audit log.

**Planned for a full partner programme:**
- **Per-partner API keys** with identity, **usage quotas**, and rotation/revocation
  (today keys are a shared allowlist without per-key metering).
- **Webhooks / callbacks** — a decision POSTed to your URL, so you don't poll.
- **API versioning** (`/api/v1`) and a published changelog.
- **mTLS or OAuth2 client-credentials** for high-trust (financial) partners.
- A **sandbox** environment with test keys and sample documents.

## 12. Security & compliance notes for integrators

- Always call over **HTTPS**; never log the `X-API-Key`, `X-Session-Token`, or images.
- Do **not** send real identity documents to a shared/demo host — use a sandbox.
- Kyron processes special-category biometric data; ensure your own **consent, lawful
  basis, and data-residency** obligations are met on your side of the integration.

---

*Related:* `SECURITY.md` (security posture + config), `docs/controls-standards-mapping.md`
(standards), `docs/in-region-hosting-plan.md` (hosting), and the live `GET /docs` /
`GET /openapi.json` for the authoritative, always-current API reference.
